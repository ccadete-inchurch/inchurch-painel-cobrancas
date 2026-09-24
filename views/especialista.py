from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from auth import current_role
from data import _EMAIL_GRUPO, fetch_pagamentos_creditados, fetch_eventos_regularizacao, fetch_cobertura_por_especialista, fetch_inadimplentes_fim_periodo, fetch_cids_por_situacao, fetch_contatos_janela, fetch_serie_carteira_mensal
from helpers import fmt_moeda_plain, hoje_brt, carimbo_dia_cache


# Paleta categórica — verde InChurch pras atendentes ativas + cinza forte
# pra "Sem especialista". Tons sofisticados sem brigar com fundo escuro.
# Ordem: Priscila e Ana primeiro (vão receber as 2 primeiras cores pelo
# sort alfabético do Altair), depois Sem especialista.
_CHART_PALETTE = [
    "#7cc243",  # verde InChurch
    "#3e7a1f",  # verde escuro (variação da marca)
    "#4b5563",  # cinza forte (Sem especialista)
    "#a3d672",  # verde claro
    "#6b7280",  # cinza médio
    "#2d5a14",  # verde profundo
    "#9ca3af",  # cinza claro
    "#dc2626",  # vermelho — só se passar dos 7 atendentes
]


def _norm_atendente_raw(s: str) -> str:
    """Padroniza só strings — vazio/'—' viram 'Sem especialista'."""
    s = str(s or "").strip()
    return s if s and s not in ("—", "nan", "NaN", "Sistema (BigQuery)") else "Sem especialista"


def _build_overlay_rows(clientes, df_bq, dt_inicio, dt_fim):
    """Constrói linhas do overlay pra acrescentar ao df do BQ.

    Cada cliente com _regularizado_hoje OU _pago_parcial_hoje vira 1 linha
    com a DATA REAL da liquidação (_dt_liquidacao_real). Se a data real
    cair fora do período [dt_inicio, dt_fim], a linha é descartada.

    Deduplica contra BQ por (id, dt) — se BQ já replicou aquele pagamento,
    não duplica.

    Retorna lista de dicts pronta pra virar DataFrame.
    """
    if not clientes:
        return []
    # IDs por dia que já estão no BQ — evita dupla contagem
    ids_por_dia_bq = {}
    if not df_bq.empty:
        for _, row in df_bq.iterrows():
            d = row["data_dt"].date() if hasattr(row["data_dt"], "date") else row["data_dt"]
            ids_por_dia_bq.setdefault(d, set()).add(str(row["id"]))

    # Contatos da janela [dt_inicio-30d, dt_fim] por cliente, do mais recente
    # pro mais antigo — mesma regra do BQ (fetch_pagamentos_creditados).
    contatos_por_cid = {}
    df_cont = fetch_contatos_janela(dt_inicio.isoformat(), dt_fim.isoformat())
    if not df_cont.empty:
        for _, r in df_cont.sort_values("data_tarefa", ascending=False).iterrows():
            _d = r["data_tarefa"]
            _d = _d.date() if hasattr(_d, "date") else _d
            contatos_por_cid.setdefault(str(r["cid"]), []).append((_d, str(r["atendente"])))

    rows = []
    for c in clientes:
        eh_reg = bool(c.get("_regularizado_hoje"))
        eh_parc = bool(c.get("_pago_parcial_hoje"))
        if not (eh_reg or eh_parc):
            continue
        # Só a parte ATRASADA: esta tela mede pagamento de cobrança vencida,
        # igual ao filtro do BQ (dt_liquidacao > dt_vencimento). Antes usava o
        # valor total do overlay e entrava quem pagou em dia — em set/2026 o
        # overlay somava 230 linhas quando só 132 pagamentos do mês tinham
        # atraso.
        dt_real = c.get("_dt_liquidacao_atraso")
        if dt_real is None:
            continue
        # Filtra por período
        if dt_real < dt_inicio or dt_real > dt_fim:
            continue
        cid = str(c.get("id") or "")
        # Deduplica contra BQ
        if cid in ids_por_dia_bq.get(dt_real, set()):
            continue
        valor = float(c.get("_valor_pago_atraso") or 0)
        if valor <= 0:
            continue
        # Atribuição igual ao BQ: contato mais recente até o dia do pagamento
        # (janela de 30 dias) credita quem fez o contato; sem contato, vai
        # pelo grupo (espontâneo). Antes todo cliente com grupo virava
        # via_contato, inflando "Pag. via contato" do mês corrente.
        # Inicio do atraso quitado (vencimento do boleto mais antigo pago com
        # atraso). Contato so vale se foi DURANTE esse atraso — mesma regra
        # de fetch_pagamentos_creditados.
        _inicio = c.get("_venc_atraso")
        contato = next(
            (at for d, at in contatos_por_cid.get(cid, [])
             if d <= dt_real and (dt_real - d).days <= 30
             and (_inicio is None or d >= _inicio)),
            None,
        )
        if contato:
            atendente, tipo_atrib = _norm_atendente_raw(contato), "via_contato"
        else:
            atendente = _norm_atendente_raw(c.get("_grupo"))
            tipo_atrib = "sem_atribuicao" if atendente == "Sem especialista" else "via_grupo"
        rows.append({
            "id": cid,
            "atendente": atendente,
            "valor": valor,
            "dt_pagamento": dt_real.isoformat(),
            "data_dt": pd.to_datetime(dt_real),
            "eh_regularizacao": eh_reg,
            "eh_parcial": eh_parc,
            "tipo_atribuicao": tipo_atrib,
            "atraso_dias": (dt_real - _inicio).days if _inicio else None,
        })
    return rows


# Carência de 4 dias: a tela do Especialista só olha quem chegou a 5+ dias de
# atraso — a partir daí o cliente pode entrar no lote (mensagem com 5 dias).
# Quem paga com 1 a 4 dias (compensação bancária, esquecimento) não é mérito
# nem falha da cobrança, então fica fora da carteira, dos pagamentos e das
# regularizações daqui. As telas operacionais (Inadimplência, Atividades)
# continuam mostrando todo mundo.
_CARENCIA_DIAS = 5


def _so_regua(df):
    """Pagamentos feitos com 5+ dias de atraso. Atraso desconhecido (overlay
    sem vencimento) fica, como antes."""
    if df.empty or "atraso_dias" not in df.columns:
        return df
    _atr = pd.to_numeric(df["atraso_dias"], errors="coerce").fillna(99)
    return df[_atr >= _CARENCIA_DIAS]


def _legenda_html(itens):
    """Legenda própria em cima do gráfico: quadrado pra barra, traço
    pontilhado pra linha. A legenda do Altair desenha tudo com o mesmo
    símbolo, e a linha do total parecia uma terceira barra (branca)."""
    partes = []
    for rotulo, cor, tipo in itens:
        if tipo in ("linha", "linha_cheia"):
            _estilo = "dashed" if tipo == "linha" else "solid"
            simbolo = (f'<span style="display:inline-block;width:18px;height:0;'
                       f'border-top:{"2px" if tipo == "linha" else "3px"} {_estilo} {cor};'
                       f'vertical-align:middle"></span>')
        else:
            simbolo = (f'<span style="display:inline-block;width:10px;height:10px;'
                       f'border-radius:2px;background:{cor};vertical-align:middle"></span>')
        partes.append(
            f'<span style="display:inline-flex;align-items:center;gap:6px;'
            f'margin-right:16px">{simbolo}<span>{rotulo}</span></span>'
        )
    return (f'<div style="font-size:12px;color:#9ca3af;margin-bottom:6px">'
            f'{"".join(partes)}</div>')


def _altair_theme():
    """Tema escuro pros gráficos Altair — combina com o painel."""
    return {
        "config": {
            "background": "transparent",
            "view": {"stroke": "transparent"},
            "axis": {
                "labelColor": "#9ca3af",
                "titleColor": "#e8eaf0",
                "gridColor": "#2a2f42",
                "domainColor": "#2a2f42",
                "tickColor": "#2a2f42",
                "labelFontSize": 12,
                "titleFontSize": 13,
                "titleFontWeight": 600,
            },
            "legend": {
                "labelColor": "#9ca3af",
                "titleColor": "#e8eaf0",
            },
            "title": {"color": "#e8eaf0", "fontSize": 16, "fontWeight": 700},
        }
    }


# Registra o tema 1x (idempotente)
alt.themes.register("inchurch_dark", _altair_theme)
alt.themes.enable("inchurch_dark")


def _render_especialista(store, clientes, role):
    # Liberada pra todos os perfis (admin e atendente)

    # ── Header ────────────────────────────────────────────────────────────
    st.markdown(
        '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:36px;'
        'font-weight:800;color:#e8eaf0;margin-top:24px;margin-bottom:24px;letter-spacing:-1px;line-height:1.1">'
        'Resultados da Cobrança</div>',
        unsafe_allow_html=True,
    )

    # ── Filtros: Mês, Especialista, Situação ──────────────────────────────
    # Seletor MENSAL, não range livre. Eficácia e Regularizações são
    # ACUMULADAS — contam quem regularizou em QUALQUER momento do período —
    # então janela longa satura e a leitura perde sentido: em 01/01-30/09/2026
    # apareciam 1.461 de 1.468 clientes com pagamento como regularizados, e as
    # duas especialistas empatadas em "50%". Mês a mês é a comparação honesta.
    #
    # Piso 06/2026: primeiro mês COMPLETO de operação. Maio saiu da lista —
    # o lote começou em 05/05 (19 dias) e os snapshots diários só em 20/05
    # (5 dias), então carteira, cobertura e eficácia do mês não são
    # comparáveis com os seguintes. Antes de maio não havia registro de
    # contato: todo pagamento aparecia como espontâneo e a eficácia como 0%.
    hoje = date.fromisoformat(hoje_brt())
    _MES_INICIAL = (2026, 6)
    _MESES_PT = {1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
                 7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez"}

    _meses = []
    _y, _m = _MES_INICIAL
    while (_y, _m) <= (hoje.year, hoje.month):
        _meses.append((_y, _m))
        _y, _m = (_y + 1, 1) if _m == 12 else (_y, _m + 1)

    fp1, fp2, fp3, _ = st.columns([2, 2, 2, 2])
    with fp1:
        _mes_sel = st.selectbox(
            "Mês",
            _meses,
            index=len(_meses) - 1,
            format_func=lambda ym: f"{_MESES_PT[ym[1]]}/{ym[0]}",
            key="esp_mes",
        )
    with fp3:
        filtro_situacao = st.selectbox(
            "Situação",
            ["Todos", "Apenas ativos", "Apenas inativos"],
            key="esp_situacao",
        )

    # Mês fechado vai até o último dia; mês corrente vai até hoje.
    dt_inicio = date(_mes_sel[0], _mes_sel[1], 1)
    if (_mes_sel[0], _mes_sel[1]) == (hoje.year, hoje.month):
        dt_fim = hoje
    else:
        _prox = (_mes_sel[0] + 1, 1) if _mes_sel[1] == 12 else (_mes_sel[0], _mes_sel[1] + 1)
        dt_fim = date(_prox[0], _prox[1], 1) - timedelta(days=1)

    _mes_corrente = (_mes_sel[0], _mes_sel[1]) == (hoje.year, hoje.month)
    _mes_label = f"{_MESES_PT[_mes_sel[1]]}/{_mes_sel[0]}"

    # Chave de cache das consultas da tela. Abrir a tela custa ~36 MB de
    # leitura no BigQuery (as pesadas são pagamentos creditados com 11,9 MB e
    # eventos de regularização com 14,6 MB), então vale cachear bem:
    #   mês FECHADO  -> chave fixa + ttl=None: consulta 1x e nunca mais.
    #   mês CORRENTE -> chave do dia operacional (vira 08:30 BRT, depois do
    #                   pipeline e do cron): 1x por dia, sempre com o dado do
    #                   dia. O que muda durante o dia entra pelo overlay da API.
    # Nome sem underscore de propósito: st.cache_data IGNORA argumentos
    # iniciados por '_' no hash, então '_versao' não invalidaria nada.
    _versao_cache = (
        f"dia-{carimbo_dia_cache()}" if _mes_corrente
        else f"mes-{_mes_sel[0]:04d}-{_mes_sel[1]:02d}"
    )

    # Situação vira parâmetro das consultas do BQ (carteira do mês, cobertura,
    # série mensal): elas olham snapshots e tarefas, onde o cliente pode nem
    # estar mais na carteira de hoje, então filtrar pelo store não funciona.
    _sit_bq = {"Apenas ativos": "ativos", "Apenas inativos": "inativos"}.get(
        filtro_situacao, "todos"
    )
    _versao_cache_sit = f"{_versao_cache}|{_sit_bq}"

    # Cobertura vem cedo porque alimenta DOIS lugares: o card de inadimplentes
    # (mês fechado) e a coluna Carteira inad. do ranking. Uma consulta só.
    df_cob = fetch_cobertura_por_especialista(
        dt_inicio.isoformat(), dt_fim.isoformat(), _versao_cache_sit, _sit_bq
    )

    # ── Fonte: BQ JOIN com tarefas — atribui por contato efetivo ──────────
    # painel_tarefas_diarias + liquidações → último atendente que teve
    # contato (msg/lig) antes do pagamento. Credita quem trabalhou o caso,
    # não o grupo atual do cliente.
    with st.spinner("Carregando pagamentos creditados..."):
        df_reg = fetch_pagamentos_creditados(dt_inicio.isoformat(), dt_fim.isoformat(), _versao_cache)

    if df_reg.empty:
        st.info("Sem pagamentos com atraso no período selecionado.")
        return

    df_reg = df_reg.rename(columns={
        "id_sacado_sac": "id",
        "atendente_credito": "atendente",
    })
    df_reg["atendente"] = df_reg["atendente"].astype(str)
    df_reg["valor"] = pd.to_numeric(df_reg["valor"], errors="coerce").fillna(0.0)
    df_reg["data_dt"] = pd.to_datetime(df_reg["dt_pagamento"], errors="coerce")
    df_reg = df_reg.dropna(subset=["data_dt"])

    # ── Overlay real-time: pagamentos via API Superlógica ──────────────────
    # BQ replica 1×/dia (lag), então pagamentos recentes só aparecem amanhã
    # no df_reg. Overlay (store["clientes"] com _regularizado_hoje /
    # _pago_parcial_hoje + _dt_liquidacao_real) preenche essa lacuna.
    # IMPORTANTE: usa a data REAL de liquidação (não hoje). Cliente que pagou
    # 15/06 aparece no dia 15/06 do gráfico, não em hoje — antes inflava a
    # barra de hoje com 19 limbos.
    overlay_rows = _build_overlay_rows(clientes, df_reg, dt_inicio, dt_fim)
    if overlay_rows:
        df_reg = pd.concat(
            [df_reg, pd.DataFrame(overlay_rows)],
            ignore_index=True,
        )

    # Override das flags eh_regularizacao / eh_parcial baseado em EVENTOS
    # historicos (analise direta de liquidacoes). O criterio anterior
    # "cliente NAO esta na carteira hoje" (i.cid IS NULL da SQL) era buggy:
    # reclassificava retroativamente pagamentos passados baseado no estado
    # atual. Exemplos do bug:
    # - Cliente regularizou em maio + reincidiu em julho: aparecia como
    #   PARCIAL em maio (errado — foi reg legitima)
    # - Cliente pagou parcial em maio + completou em julho: aparecia como
    #   REG em maio (errado — foi parcial em maio, reg em julho)
    #
    # Novo criterio per-pagamento: existe outro boleto vencido em aberto
    # apos essa data? Se nao → regularizou. Preserva o contexto temporal.
    #
    # Fallback pra pagamentos dos ultimos 3d (BQ pode ainda nao ter
    # replicado): mantem eh_regularizacao original (que veio do overlay).
    if not df_reg.empty:
        eventos_reg = fetch_eventos_regularizacao()
        from datetime import date as _dc

        def _classifica_evento(row):
            _cid = str(row.get("id") or "")
            _dt = row.get("data_dt")
            if _dt is None or pd.isna(_dt):
                return row.get("eh_regularizacao", False)
            _dstr = _dt.strftime("%d/%m/%Y") if hasattr(_dt, "strftime") else str(_dt)
            if (_cid, _dstr) in eventos_reg:
                return True
            # Fallback: pagamentos recentes (ultimos 10d) — BQ nao replicou,
            # respeita a classificacao vinda do overlay (_regularizado_hoje).
            # 10 dias = mesma janela do overlay (fetch_pagamentos_hoje_api).
            try:
                dt_date = _dt.date() if hasattr(_dt, "date") else _dt
                if (_dc.today() - dt_date).days <= 10:
                    return bool(row.get("eh_regularizacao", False))
            except Exception:
                pass
            return False

        df_reg["eh_regularizacao"] = df_reg.apply(_classifica_evento, axis=1)
        df_reg["eh_parcial"] = ~df_reg["eh_regularizacao"]

    # "Sem especialista" fora da tela inteira (cards, matriz, gráficos,
    # ranking): é o balde de clientes sem grupo, não uma pessoa, e não deve
    # entrar em análise nem métrica.
    df_reg = df_reg[df_reg["atendente"] != "Sem especialista"]
    df_reg = _so_regua(df_reg)
    df_cob = df_cob[df_cob["atendente"] != "Sem especialista"] if not df_cob.empty else df_cob
    if df_reg.empty:
        st.info("Sem pagamentos com atraso no período selecionado.")
        return

    with fp2:
        especialistas_disp = sorted(
            (set(df_reg["atendente"].unique()) | set(_EMAIL_GRUPO.values()))
            - {"Sem especialista"}
        )
        filtro_esp = st.multiselect(
            "Especialista",
            especialistas_disp,
            key="esp_filtro",
            placeholder="Todos",
        )

    # Helpers de filtro pra carteira atual (clientes). Multi-select:
    # lista vazia = todos (sem filtro); com nomes = filtra por esses.
    def _eh_grupo_match(c):
        _g = _norm_atendente_raw(c.get("_grupo"))
        if _g == "Sem especialista":
            return False
        if not filtro_esp:
            return True
        return _g in filtro_esp
    def _eh_situacao_match(c):
        if filtro_situacao == "Todos":
            return True
        if filtro_situacao == "Apenas ativos":
            return not c.get("_inativo")
        return bool(c.get("_inativo"))

    # Set de IDs ativos/inativos — usado pra cruzar com os pagamentos do
    # histórico. Vem da tabela MESTRE, não da carteira de hoje: quem pagou e
    # saiu da carteira não está mais no store, e era descartado do recorte
    # (24/09/2026: a Ana tinha 61 regularizações no total, 24 em "ativos" e 0
    # em "inativos"). "Todos" mantém None e não restringe nada.
    if filtro_situacao == "Todos":
        ids_situacao_ok = None
    else:
        ids_situacao_ok = fetch_cids_por_situacao(_sit_bq, _versao_cache_sit)
        if not ids_situacao_ok:  # consulta falhou: cai pra carteira de hoje
            ids_situacao_ok = {
                str(c.get("id") or "") for c in clientes if _eh_situacao_match(c)
            }

    def _contatados_por_atendente(ini, fim):
        """Clientes distintos com msg/ligação no período, por atendente —
        denominador da Eficácia e da Cobertura.

        Vem da mesma consulta do BQ que monta a Carteira do mês (df_cob), que
        já aplica o filtro de Situação pela tabela mestre. Filtrar pelo store
        perdia quem foi contatado e saiu da carteira: em 24/09/2026, com
        "Apenas ativos", dava 93 contra 123."""
        if not df_cob.empty and "contactados" in df_cob.columns:
            return df_cob.rename(columns={"contactados": "contatados"})[
                ["atendente", "contatados"]
            ]
        # Sem snapshot no período o df_cob vem vazio: cai pro cálculo local.
        _c = fetch_contatos_janela(ini.isoformat(), fim.isoformat())
        if _c.empty:
            return pd.DataFrame(columns=["atendente", "contatados"])
        _c = _c.copy()
        _c["cid"] = _c["cid"].astype(str)
        _d = pd.to_datetime(_c["data_tarefa"]).dt.date
        _c = _c[(_d >= ini) & (_d <= fim)]
        if ids_situacao_ok is not None:
            _c = _c[_c["cid"].isin(ids_situacao_ok)]
        return _c.groupby("atendente")["cid"].nunique().rename("contatados").reset_index()

    # df_per_all: período inteiro (BQ já filtrou por data) — média da equipe.
    # Aplica filtro de Situação cruzando com IDs da carteira atual.
    df_per_all = df_reg
    if ids_situacao_ok is not None:
        df_per_all = df_per_all[df_per_all["id"].astype(str).isin(ids_situacao_ok)]
    # df_per: também filtrado por especialista (cards individuais)
    df_per = df_per_all.copy()
    if filtro_esp:
        df_per = df_per[df_per["atendente"].isin(filtro_esp)]

    # ── Cards agregados ───────────────────────────────────────────────────
    # Resumo da equipe na mesma lógica do ranking: carteira → contatados →
    # regularizações → resultado do contato → valor. Pagamentos e Parciais
    # saíram: parcial é pouco (cliente continua devendo) e "pagamentos"
    # só somava regularizações + parciais.
    # Cliente é classificado UMA vez (REG > PARC): BQ defasado e overlay da
    # API podiam discordar e contar o mesmo cliente nos dois.
    total_valor = float(df_per["valor"].sum()) if not df_per.empty else 0.0
    if not df_per.empty:
        _ids = df_per["id"].astype(str)
        _reg = df_per["eh_regularizacao"].astype(bool)
        total_reg = int(_ids[_reg].nunique())
        total_reg_com = int(_ids[_reg & (df_per["tipo_atribuicao"] == "via_contato")].nunique())
    else:
        total_reg = 0
        total_reg_com = 0
    pct_reg_com = (total_reg_com / total_reg * 100) if total_reg else 0.0

    # Carteira da cobrança no mês (base do ranking) e contatados da equipe
    _cob_card = df_cob
    if filtro_esp and not _cob_card.empty:
        _cob_card = _cob_card[_cob_card["atendente"].isin(filtro_esp)]
    _base_cart = int(_cob_card["inadimplentes_periodo"].sum()) if not _cob_card.empty else 0
    _cont_card = _contatados_por_atendente(dt_inicio, dt_fim)
    if filtro_esp and not _cont_card.empty:
        _cont_card = _cont_card[_cont_card["atendente"].isin(filtro_esp)]
    total_contatados = int(_cont_card["contatados"].sum()) if not _cont_card.empty else 0
    cobertura_equipe = (total_contatados / _base_cart * 100) if _base_cart else 0.0
    resultado_equipe = (total_reg_com / _base_cart * 100) if _base_cart else 0.0

    # Card de inadimplentes: número grande = Carteira do mês (a soma da coluna
    # do ranking: quem chegou à cobrança no mês, mesmo que já tenha pago).
    # Subtítulo = a foto: quem deve hoje (mês corrente) ou no último dia (mês
    # fechado). Chegou a mostrar os distintos com 1+ dia (964 em set/2026),
    # mas eram três "inadimplentes" diferentes na tela; ficaram só dois: no
    # mês e hoje.
    _card_inad_valor = _base_cart
    if _mes_corrente:
        # Foto de hoje sem quem regularizou hoje (API), igual Inadimplência e
        # Lote do Dia. Em dia de pipeline parado o store ainda traz quem já
        # pagou (em 22/09/2026 eram 155) e o número inflava pra 846.
        _ids_hoje = {
            str(c.get("id")) for c in clientes
            if not c.get("_regularizado_hoje")
            and _eh_grupo_match(c)
            and _eh_situacao_match(c)
        }
        _card_inad_sub = f"no mês · {len(_ids_hoje):,} hoje".replace(",", ".")
    else:
        _fim_p = fetch_inadimplentes_fim_periodo(
            dt_inicio.isoformat(), dt_fim.isoformat(), _versao_cache_sit, _sit_bq
        )
        if filtro_esp and not _fim_p.empty:
            _fim_p = _fim_p[_fim_p["atendente"].isin(filtro_esp)]
        _card_inad_sub = (
            f'no mês · {int(_fim_p["clientes"].sum()):,} em '.replace(",", ".")
            + pd.Timestamp(_fim_p["data_snapshot"].iloc[0]).strftime("%d/%m")
            if not _fim_p.empty else "no mês"
        )

    def _pct_br(v):
        return f"{v:.2f}%".replace(".", ",")

    # Tooltips dos cards
    _tt_inad = (
        f"Clientes que entraram na cobrança em algum dia de {_mes_label}, mesmo "
        "que já tenham pago — é a soma da coluna Carteira do mês. Embaixo, quantos "
        + ("devem hoje (igual à tela Inadimplência)." if _mes_corrente
           else "deviam no último dia do mês.")
    )
    _tt_cont = (
        f"Clientes distintos que receberam mensagem ou ligação no mês. Cobertura = "
        f"contatados ÷ carteira do mês ({total_contatados} ÷ {_base_cart})."
    )
    _tt_reg = (
        f"Clientes que pagaram e zeraram tudo que estava vencido, já na fase de "
        f"cobrança: {total_reg_com} com contato e {total_reg - total_reg_com} sem "
        "contato. Não inclui baixas administrativas, parcelamentos ou desativações."
    )
    _tt_res = (
        f"Regularizações com contato ÷ carteira do mês ({total_reg_com} ÷ "
        f"{_base_cart}). É a Cobertura × a Eficácia e o critério do ranking."
    )
    _tt_val = "Soma dos pagamentos em atraso feitos já na fase de cobrança."

    # 5 cards — Valor Recuperado (último) tem coluna mais larga porque
    # "R$ 130.121,84" não cabe na largura das demais sem quebrar linha.
    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1.5])
    _card_fmt = lambda label, valor, sub, cor, tip="": (
        f'<div class="metric-card" '
        f'{"title=" + chr(34) + tip + chr(34) if tip else ""} '
        f'style="cursor:{"help" if tip else "default"};padding:20px 22px">'
        f'<div class="metric-label" style="font-size:15px;letter-spacing:1.3px">{label}</div>'
        f'<div style="font-size:38px;font-weight:800;color:{cor};margin-top:6px;'
        f'line-height:1.05;font-variant-numeric:tabular-nums;'
        f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{valor}</div>'
        # nowrap: em notebook o subtítulo quebrava em duas linhas
        f'<div class="metric-sub" style="font-size:13.5px;margin-top:8px;white-space:nowrap;'
        f'overflow:hidden;text-overflow:ellipsis">{sub}</div>'
        f'</div>'
    )
    with c1:
        st.markdown(
            _card_fmt("Inadimplentes", f"{_card_inad_valor:,}".replace(",", "."),
                      _card_inad_sub, "#ef4444", _tt_inad),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            _card_fmt("Contatados", f"{total_contatados:,}".replace(",", "."),
                      f"cobertura {_pct_br(cobertura_equipe)}", "#e8eaf0", _tt_cont),
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            _card_fmt("Regularizações", f"{total_reg:,}".replace(",", "."),
                      f"{_pct_br(pct_reg_com)} com contato", "#22c55e", _tt_reg),
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            # Título curto: "RESULTADO DO CONTATO" não cabia na largura do
            # card e o CSS corta com reticências. A fórmula fica no tooltip.
            _card_fmt("Resultado", _pct_br(resultado_equipe),
                      "do contato", "#22c55e", _tt_res),
            unsafe_allow_html=True,
        )
    with c5:
        st.markdown(
            _card_fmt("Valor Recuperado", fmt_moeda_plain(total_valor),
                      "no período", "#5fa3ff", _tt_val),
            unsafe_allow_html=True,
        )

    # Divider entre seções — linha hairline + respiro vertical pra separar
    # blocos visualmente (Cards → Matriz → Gráficos → Tabela).
    _DIVIDER = '<div style="margin:36px 0 28px;border-top:1px solid rgba(75,85,99,0.5)"></div>'
    st.markdown(_DIVIDER, unsafe_allow_html=True)

    if df_per.empty:
        st.info("Nenhum pagamento no período selecionado.")
        return

    # ── Tabela ranking detalhado ──────────────────────────────────────────
    st.markdown(
        '<div style="font-size:14px;font-weight:700;color:#8b94a5;'
        'text-transform:uppercase;letter-spacing:1.5px;'
        'margin-bottom:12px">Ranking Detalhado</div>',
        unsafe_allow_html=True,
    )
    # Agregado por especialista — pagamentos, regularizações, parciais, valor,
    # contagem via contato direto vs espontâneo.
    # IMPORTANTE: dedup POR CLIENTE antes de agregar, senão Sara (com 2
    # linhas: BQ + overlay) conta duas vezes em reg/parc — mesma raiz do
    # bug dos cards. Aplica regra de prioridade REG > PARC (estado final).
    # Com/sem contato só compara quem estava 5+ dias atrasado ao pagar. Com
    # até 4 dias é margem de erro (compensação, esquecimento): o lote só pega
    # cliente com 5+ dias, então ninguém poderia ter cobrado. Esses entram só
    # no total de Regularizações. Atraso desconhecido (overlay sem vencimento)
    # conta como 5+, que era o comportamento anterior.
    _atraso = (pd.to_numeric(df_per["atraso_dias"], errors="coerce").fillna(99)
               if "atraso_dias" in df_per.columns else pd.Series(99, index=df_per.index))
    _na_regua = _atraso >= 5
    _eh_reg = df_per["eh_regularizacao"].astype(bool)
    _via = df_per["tipo_atribuicao"] == "via_contato"
    df_per["reg_via_contato"] = _eh_reg & _via & _na_regua
    df_per["reg_sem_contato"] = _eh_reg & ~_via & _na_regua
    # Fora do ranking: "Sem especialista" não é pessoa, é o balde de clientes
    # sem grupo. Ele nunca entra no lote, então aparecia com 0 contatados,
    # 0% de eficácia e 100% espontâneos — linha que só polui a comparação.
    # Mesma exclusão já feita na Matriz de Desempenho e na média da equipe.
    df_rank = df_per[df_per["atendente"] != "Sem especialista"]
    # Passo 1: classifica cada cliente UMA vez (qualquer linha reg → reg;
    # qualquer via_contato → via_contato; valor total)
    per_cli_rank = (
        df_rank.groupby(["id", "atendente"])
        .agg(
            tem_reg=("eh_regularizacao", "any"),
            tem_parc=("eh_parcial", "any"),
            tem_via_contato=("tipo_atribuicao", lambda s: (s == "via_contato").any()),
            tem_reg_via_contato=("reg_via_contato", "any"),
            tem_reg_sem_contato=("reg_sem_contato", "any"),
            valor=("valor", "sum"),
        )
        .reset_index()
    )
    # Cliente que teve as duas coisas no mês conta como COM contato
    per_cli_rank["tem_reg_sem_contato"] = (
        per_cli_rank["tem_reg_sem_contato"] & ~per_cli_rank["tem_reg_via_contato"]
    )
    # Aplica prioridade REG > PARC
    per_cli_rank["eh_reg_final"] = per_cli_rank["tem_reg"]
    per_cli_rank["eh_parc_final"] = per_cli_rank["tem_parc"] & ~per_cli_rank["tem_reg"]
    # Passo 2: agrega por atendente (cada linha já é 1 cliente)
    rank_agg = (
        per_cli_rank.groupby("atendente")
        .agg(
            pagamentos=("id", "size"),
            regularizacoes=("eh_reg_final", "sum"),
            parciais=("eh_parc_final", "sum"),
            via_contato=("tem_via_contato", "sum"),
            reg_via_contato=("tem_reg_via_contato", "sum"),
            reg_sem_contato=("tem_reg_sem_contato", "sum"),
            valor=("valor", "sum"),
        )
        .reset_index()
    )
    # Eficácia = Reg. com contato ÷ Contatados do mês — as duas colunas da
    # própria linha, então a conta se confere na tabela. A regularização
    # conta no mês do PAGAMENTO (uma vez só), igual a Reg. total e % da
    # carteira. Antes contava no mês do contato e nunca batia com a coluna.
    # outer: especialista pode ter contatado e não ter NENHUM pagamento no
    # recorte (com "Apenas inativos" em 24/09/2026 a Ana ficava fora do
    # rank_agg e aparecia com 0 contatados, apesar de 157 no BQ).
    rank_agg = rank_agg.merge(
        _contatados_por_atendente(dt_inicio, dt_fim), on="atendente", how="outer"
    )
    rank_agg["ef_contatados"] = rank_agg["contatados"].fillna(0).astype(int)
    rank_agg["ef_regularizaram"] = rank_agg["reg_via_contato"].fillna(0).astype(int)
    rank_agg["eficacia"] = (
        rank_agg["ef_regularizaram"] / rank_agg["ef_contatados"].replace(0, pd.NA) * 100
    ).fillna(0).astype(float)
    rank_agg = rank_agg.drop(columns=["contatados"])
    # Cobertura = quanto da propria carteira inadimplente o especialista tocou
    # no periodo. Complementa a eficacia: quem tem carteira maior recebe o
    # mesmo lote de 80/dia e por isso cobre uma fatia menor.
    # df_cob já veio lá de cima (uma consulta só pro card e pro ranking).
    if df_cob.empty:
        rank_agg["cobertura"] = 0
        rank_agg["cob_contactados"] = 0
        rank_agg["cob_base"] = 0
    else:
        rank_agg = rank_agg.merge(
            df_cob[["atendente", "cobertura_pct", "contactados", "inadimplentes_periodo"]],
            on="atendente", how="outer",
        )
        rank_agg["cobertura"] = rank_agg["cobertura_pct"].fillna(0).astype(float)
        rank_agg["cob_contactados"] = rank_agg["contactados"].fillna(0).astype(int)
        rank_agg["cob_base"] = rank_agg["inadimplentes_periodo"].fillna(0).astype(int)
        rank_agg = rank_agg.drop(columns=["cobertura_pct", "contactados", "inadimplentes_periodo"])
    # Carteira: quantos clientes ESTIVERAM com 5+ dias de atraso no mês
    # (inclusive o corrente) — mesma base da Cobertura, então a linha fica
    # autoexplicativa:
    # Contatados ÷ Carteira inad. = Cobertura.
    # Fim do mês esconderia quem entrou e saiu no meio: em ago/2026 a Ana
    # terminou com 243, mas passaram 525 pelas mãos dela.
    if df_cob.empty:
        carteira_count = pd.DataFrame(columns=["atendente", "carteira_atual"])
    else:
        carteira_count = (
            df_cob.rename(columns={"inadimplentes_periodo": "carteira_atual"})
            [["atendente", "carteira_atual"]]
        )
    # Sem o filtro aqui, o merge outer traria "Sem especialista" de volta só
    # com a carteira preenchida e o resto zerado.
    if not carteira_count.empty:
        carteira_count = carteira_count[carteira_count["atendente"] != "Sem especialista"]
    ranking = rank_agg.merge(carteira_count, on="atendente", how="outer").fillna(0)
    # Força int em todas as colunas numéricas inteiras — evita exibir '16.0'
    # quando merges com floats convertem o tipo silenciosamente.
    # Eficácia mantém como float (duas casas decimais); demais são int.
    for col in ("pagamentos", "regularizacoes", "parciais", "reg_via_contato",
                "reg_sem_contato", "carteira_atual", "cob_contactados", "cob_base"):
        if col in ranking.columns:
            ranking[col] = ranking[col].astype(int)
    # Eficácia e cobertura ficam float (duas casas) — percentuais pequenos
    # arredondados pra inteiro escondem diferença entre as especialistas.
    for col in ("eficacia", "cobertura"):
        if col in ranking.columns:
            ranking[col] = ranking[col].astype(float)
    # % da carteira regularizada (informativo: inclui quem pagou sozinho).
    ranking["pct_carteira"] = (
        ranking["regularizacoes"] / ranking["carteira_atual"].replace(0, pd.NA) * 100
    ).fillna(0).astype(float)
    # Resultado do contato = Reg. com contato ÷ Carteira inad. = Cobertura ×
    # Eficácia. Ordena o ranking: só conta o que veio do contato e ajusta pelo
    # tamanho da carteira. O % da carteira premiava quem teve mais cliente
    # pagando sozinho.
    ranking["res_contato"] = (
        ranking["reg_via_contato"] / ranking["carteira_atual"].replace(0, pd.NA) * 100
    ).fillna(0).astype(float)
    ranking = ranking.sort_values("res_contato", ascending=False).reset_index(drop=True)
    ranking["rank"] = ranking.index + 1
    ranking["valor_fmt"] = ranking["valor"].apply(fmt_moeda_plain)

    # Headers — 11 colunas, na ordem do funil: o que tem na mão (carteira),
    # o que tocou (contatados), o que voltou (pagamentos e regularizações) e
    # só então os percentuais e o valor. As colunas de pagamento são por
    # CLIENTE — o mesmo cliente pode pagar várias vezes no mês.
    _col_widths = [0.5, 1.5, 0.95, 0.95, 1.0, 1.0, 0.85, 1.05, 0.95, 0.9, 0.95, 1.2]
    _carteira_tip = (
        f"Clientes que entraram na cobrança (já podiam entrar no lote) em algum "
        f"dia de {_mes_label}, mesmo que já tenham pago. Quem paga nos primeiros "
        "dias de atraso, antes do lote, não entra. É a base da Cobertura e do "
        "Resultado do contato."
    )
    hdr_cols = st.columns(_col_widths)
    _hdr_labels = [
        ("Pos.", ""),
        ("Especialista", ""),
        ("Carteira<br>do mês", _carteira_tip),
        ("Contatados", "Clientes distintos que receberam mensagem ou ligação no mês. É a base da Eficácia e da Cobertura."),
        ("Reg. com<br>contato", "Clientes que zeraram o atraso no mês tendo recebido msg ou ligação durante esse atraso (até 30 dias antes do pagamento). Crédito vai pra quem fez o contato mais recente. É o numerador da Eficácia."),
        ("Reg. sem<br>contato", "Clientes que zeraram o atraso sem contato da cobrança durante esse atraso. Pode ter havido régua automática ou chatbot — o painel só registra contato do lote."),
        ("Reg.<br>total", "Reg. com contato + Reg. sem contato."),
        ("Resultado<br>do contato", "Reg. com contato ÷ Carteira do mês — é a Cobertura × a Eficácia. Ordena o ranking: mede só o que veio do contato, ajustado ao tamanho da carteira."),
        ("% da<br>carteira", "Reg. total ÷ Carteira do mês. Inclui quem pagou sem contato."),
        ("Eficácia", "Reg. com contato ÷ Contatados. Cada regularização conta uma vez, no mês do pagamento. Pagamento parcial não conta."),
        ("Cobertura", "Contatados ÷ Carteira do mês: quanto da carteira o especialista alcançou (msg/ligação). Carteira maior com o mesmo lote de 80/dia = cobertura menor."),
        ("Valor<br>recuperado", ""),
    ]
    for col, (h, tip) in zip(hdr_cols, _hdr_labels):
        title_attr = f' title="{tip}"' if tip else ""
        cursor = "help" if tip else "default"
        col.markdown(
            # Quebra só onde tem <br> (entre palavras): white-space:nowrap em
            # cada linha. Antes o navegador partia no meio ("POSI/ÇÃO",
            # "CONTATADO/S", "REGULARIZAÇÕ/ES") em monitores menores.
            f'<div{title_attr} style="cursor:{cursor};padding:8px 0;font-size:10.5px;'
            f'text-transform:uppercase;letter-spacing:0.6px;color:#8b94a5;font-weight:700;'
            f'white-space:nowrap;line-height:1.3">{h}</div>',
            unsafe_allow_html=True,
        )

    for _, row in ranking.iterrows():
        rcols = st.columns(_col_widths)
        # Posição numérica (1, 2, 3...) em vez das medalhas de emoji.
        rcols[0].markdown(
            f'<div style="padding:10px 0;font-size:16px;color:#e8eaf0;font-weight:700">{row["rank"]}</div>',
            unsafe_allow_html=True,
        )
        rcols[1].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#e8eaf0;font-weight:600">{row["atendente"]}</div>',
            unsafe_allow_html=True,
        )
        # Carteira inadimplente de hoje — contexto pra ler o resto da linha.
        rcols[2].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#9ca3af">{row["carteira_atual"]}</div>',
            unsafe_allow_html=True,
        )
        # Contatados — base dos dois percentuais mais à direita.
        _contatados = int(row.get("ef_contatados", 0) or 0) or int(row.get("cob_contactados", 0) or 0)
        rcols[3].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#e8eaf0;font-weight:600">{_contatados}</div>',
            unsafe_allow_html=True,
        )
        # Regularizações separadas por origem. As colunas de pagamento
        # (clientes com pag., pag. via contato, pag. espontâneos) saíram: ~97%
        # de quem paga regulariza, então repetiam estas duas.
        rcols[4].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#22c55e;font-weight:600">'
            f'{int(row.get("reg_via_contato", 0) or 0)}</div>',
            unsafe_allow_html=True,
        )
        rcols[5].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#9ca3af;font-weight:600">'
            f'{int(row.get("reg_sem_contato", 0) or 0)}</div>',
            unsafe_allow_html=True,
        )
        rcols[6].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#22c55e;font-weight:600">{row["regularizacoes"]}</div>',
            unsafe_allow_html=True,
        )
        # Resultado do contato — critério de ordenação do ranking.
        _res = float(row.get("res_contato", 0) or 0)
        _res_tip = (
            f'{int(row.get("reg_via_contato", 0) or 0)} regularizações com contato ÷ '
            f'{int(row["carteira_atual"])} da carteira'
        )
        rcols[7].markdown(
            f'<div title="{_res_tip}" style="cursor:help;padding:10px 0;font-size:14px;'
            f'color:#22c55e;font-weight:700">{_res:.2f}%</div>',
            unsafe_allow_html=True,
        )
        # % da carteira regularizada — informativo (inclui quem pagou sozinho).
        _pct_cart = float(row.get("pct_carteira", 0) or 0)
        _pct_cart_tip = (
            f'{int(row["regularizacoes"])} de {int(row["carteira_atual"])} '
            f'da carteira'
        )
        rcols[8].markdown(
            f'<div title="{_pct_cart_tip}" style="cursor:help;padding:10px 0;font-size:14px;'
            f'color:#9ca3af;font-weight:600">{_pct_cart:.2f}%</div>',
            unsafe_allow_html=True,
        )
        # Eficácia REAL — faixas ajustadas (cobrança é trabalho difícil,
        # taxa típica de conversão é 10-20% em operação saudável).
        # Tooltip mostra a fração explícita pra transparência: X de Y
        # contatados regularizaram. Antes só dava pra ver o percentual.
        _ef = row["eficacia"]
        _ef_cor = "#22c55e" if _ef >= 30 else ("#f59e0b" if _ef >= 15 else "#ef4444")
        _ef_reg = int(row.get("ef_regularizaram", 0) or 0)
        _ef_cont = int(row.get("ef_contatados", 0) or 0)
        _ef_tip = f"{_ef_reg} regularizações com contato ÷ {_ef_cont} contatados no mês"
        rcols[9].markdown(
            f'<div title="{_ef_tip}" style="cursor:help;padding:10px 0;font-size:14px;'
            f'color:{_ef_cor};font-weight:700">{_ef:.2f}%</div>',
            unsafe_allow_html=True,
        )
        # Cobertura — sem faixa de cor "boa/ruim": depende do tamanho da
        # carteira, entao e' contexto pra ler a eficacia, nao nota.
        _cob = float(row.get("cobertura", 0) or 0)
        _cob_cont = int(row.get("cob_contactados", 0) or 0)
        _cob_base = int(row.get("cob_base", 0) or 0)
        _cob_txt = f"{_cob:.2f}%" if _cob_base else "—"
        _cob_tip = (
            f"{_cob_cont} de {_cob_base} inadimplentes do período foram contactados"
            if _cob_base else "Sem snapshot diário no período"
        )
        rcols[10].markdown(
            f'<div title="{_cob_tip}" style="cursor:help;padding:10px 0;font-size:14px;'
            f'color:#9ca3af;font-weight:600">{_cob_txt}</div>',
            unsafe_allow_html=True,
        )
        rcols[11].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#5fa3ff;font-weight:600">{row["valor_fmt"]}</div>',
            unsafe_allow_html=True,
        )

    st.markdown(_DIVIDER, unsafe_allow_html=True)


    # ── Agregado por especialista — Volume + Eficácia (base pra matriz) ───
    # Exclui "Sem especialista" da comparação: não é uma pessoa pra comparar
    # performance, é o bucket de clientes não atribuídos. Incluir distorce
    # a média da equipe e faz Ana/Priscila parecerem acima do que são.
    df_per_matriz = df_per[df_per["atendente"] != "Sem especialista"]
    agg_esp = (
        df_per_matriz.groupby("atendente")
        .agg(pagamentos=("id", "nunique"), valor=("valor", "sum"))
        .reset_index()
    )
    # Volume da Matriz = Reg. com contato (mesma regra da coluna da tabela:
    # regularizou, 5+ dias de atraso, contato durante o atraso). Antes era
    # "todos os pagamentos", que creditava parcial e quem pagou em até 4
    # dias — sobe no gráfico sem trabalho de cobrança por trás.
    _m = df_per_matriz.copy()
    _atr_m = (pd.to_numeric(_m["atraso_dias"], errors="coerce").fillna(99)
              if "atraso_dias" in _m.columns else pd.Series(99, index=_m.index))
    _m["_reg_com"] = (
        _m["eh_regularizacao"].astype(bool)
        & (_m["tipo_atribuicao"] == "via_contato")
        & (_atr_m >= 5)
    )
    _reg_com_esp = (
        _m[_m["_reg_com"]].groupby("atendente")["id"].nunique()
        .rename("reg_com_contato").reset_index()
    )
    agg_esp = agg_esp.merge(_reg_com_esp, on="atendente", how="left")
    agg_esp["reg_com_contato"] = agg_esp["reg_com_contato"].fillna(0).astype(int)
    # Eficácia = Reg. com contato ÷ Contatados, mesma conta da tabela
    agg_esp = agg_esp.merge(
        _contatados_por_atendente(dt_inicio, dt_fim)
        .rename(columns={"contatados": "clientes_contactados"}),
        on="atendente", how="left",
    )
    agg_esp["clientes_contactados"] = agg_esp["clientes_contactados"].fillna(0).astype(int)
    agg_esp["regularizaram"] = agg_esp["reg_com_contato"]
    agg_esp["eficacia_real"] = (
        agg_esp["reg_com_contato"] / agg_esp["clientes_contactados"].replace(0, pd.NA) * 100
    ).fillna(0).astype(float)

    # ── Matriz de Desempenho (scatter Volume × Eficácia) ──────────────────
    # Cada atendente vira um ponto. Quadrante superior direito = star
    # (alto volume + alta eficácia). Inferior esquerdo = precisa apoio.
    st.markdown(
        '<div style="font-size:14px;font-weight:700;color:#8b94a5;'
        'text-transform:uppercase;letter-spacing:1.5px;'
        'margin-top:8px;margin-bottom:4px">Matriz de Desempenho</div>'
        '<div style="font-size:11px;color:#8b94a5;margin-bottom:12px">'
        'Regularizações com contato × Eficácia por especialista.'
        '</div>',
        unsafe_allow_html=True,
    )

    # Cap dos eixos: deixa margem visual nos extremos pra texto não sair
    _max_pag = max(agg_esp["reg_com_contato"].max() if not agg_esp.empty else 1, 1)
    _max_ef = max(agg_esp["eficacia_real"].max() if not agg_esp.empty else 1, 30)

    base_scatter = alt.Chart(agg_esp).encode(
        x=alt.X(
            "eficacia_real:Q",
            title="EFICÁCIA REAL (%)",
            scale=alt.Scale(domain=[0, max(_max_ef * 1.2, 100)]),
        ),
        y=alt.Y(
            "reg_com_contato:Q",
            title="REGULARIZAÇÕES COM CONTATO",
            scale=alt.Scale(domain=[0, _max_pag * 1.25]),
        ),
    )
    pontos = base_scatter.mark_circle(size=400, opacity=0.85).encode(
        color=alt.Color(
            "atendente:N",
            scale=alt.Scale(range=_CHART_PALETTE),
            legend=None,
        ),
        tooltip=[
            alt.Tooltip("atendente:N", title="Especialista"),
            alt.Tooltip("reg_com_contato:Q", title="Reg. com contato"),
            alt.Tooltip("eficacia_real:Q", title="Eficácia (%)", format=".2f"),
            alt.Tooltip("clientes_contactados:Q", title="Contatados"),
            alt.Tooltip("valor:Q", title="Valor recuperado", format=",.2f"),
        ],
    )
    labels = base_scatter.mark_text(
        align="left", baseline="middle", dx=14, dy=-2,
        fontSize=12, fontWeight="bold", color="#e8eaf0",
    ).encode(text="atendente:N")

    # Linhas de quadrantes — médias da equipe (vertical = eficácia, horizontal
    # = volume). Atendente acima da linha horizontal = volume acima da média;
    # à direita da vertical = eficácia acima da média.
    _avg_ef = float(agg_esp["eficacia_real"].mean()) if not agg_esp.empty else 0
    _avg_vol = float(agg_esp["reg_com_contato"].mean()) if not agg_esp.empty else 0
    vline = alt.Chart(pd.DataFrame({"x": [_avg_ef]})).mark_rule(
        color="#cbd5e1", strokeDash=[6, 4], opacity=0.45, strokeWidth=1.5,
    ).encode(x="x:Q")
    hline = alt.Chart(pd.DataFrame({"y": [_avg_vol]})).mark_rule(
        color="#cbd5e1", strokeDash=[6, 4], opacity=0.45, strokeWidth=1.5,
    ).encode(y="y:Q")

    chart_matriz = (vline + hline + pontos + labels).properties(height=320)
    st.altair_chart(chart_matriz, use_container_width=True)
    st.markdown(
        f'<div style="font-size:11px;color:#6b7280;margin-top:-8px">'
        f'Linhas pontilhadas = média da equipe (eficácia {_avg_ef:.2f}%, '
        f'regularizações com contato {_avg_vol:.0f}).'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown(_DIVIDER, unsafe_allow_html=True)

    # ── Layout 2 colunas: Regularizações por Dia | Distribuição da Carteira ──
    g_esq, g_dir = st.columns(2)

    # ── Regularizações por Dia ────────────────────────────────────────────
    # Mesmo formato do "Regularizações por Mês": com x sem contato durante o
    # atraso (df_per já só tem 5+ dias). Antes eram "Pagamentos por Dia" por
    # atendente, contando tudo — o pico depois dos vencimentos em massa
    # (dias 15/17) parecia resultado, mas era margem de erro.
    with g_esq:
        _tem_hoje_no_df = any(d == hoje for d in df_per["data_dt"].dt.date.unique())
        _sub_dia = (
            'Clientes que regularizaram o atraso no dia, com ou sem contato durante o atraso.'
        )
        st.markdown(
            '<div style="font-size:14px;font-weight:700;color:#8b94a5;'
            'text-transform:uppercase;letter-spacing:1.5px;'
            'margin-top:24px;margin-bottom:4px">Regularizações por Dia</div>'
            f'<div style="font-size:11px;color:#8b94a5;margin-bottom:8px">{_sub_dia}</div>'
            + _legenda_html([("Com contato", "#22c55e", "barra"),
                             ("Sem contato", "#9ca3af", "barra"),
                             ("Total do dia", "#e8eaf0", "linha")]),
            unsafe_allow_html=True,
        )
        _dd = df_per.copy()
        _dd["id"] = _dd["id"].astype(str)
        _dd["data"] = _dd["data_dt"].dt.date
        _atr_d = (pd.to_numeric(_dd["atraso_dias"], errors="coerce").fillna(99)
                  if "atraso_dias" in _dd.columns else pd.Series(99, index=_dd.index))
        _dd["reg"] = _dd["eh_regularizacao"].astype(bool)
        _dd["r_via"] = _dd["reg"] & (_dd["tipo_atribuicao"] == "via_contato") & (_atr_d >= 5)
        _dd["r_esp"] = _dd["reg"] & (_dd["tipo_atribuicao"] != "via_contato") & (_atr_d >= 5)
        _cli_dia = (
            _dd.groupby(["data", "id"])
            .agg(reg=("reg", "any"), r_via=("r_via", "any"), r_esp=("r_esp", "any"))
            .reset_index()
        )
        _cli_dia["r_esp"] = _cli_dia["r_esp"] & ~_cli_dia["r_via"]
        _por_dia = (
            _cli_dia.groupby("data")
            .agg(com=("r_via", "sum"), sem=("r_esp", "sum"), total=("reg", "sum"))
            .reset_index()
        )
        _por_dia["total"] = _por_dia["com"] + _por_dia["sem"]
        _por_dia = _por_dia[_por_dia["total"] > 0]
        if _por_dia.empty:
            st.info("Sem regularizações no período.")
        else:
            _por_dia["data_str"] = _por_dia["data"].apply(lambda d: d.strftime("%d/%m"))
            _por_dia["eh_hoje"] = _por_dia["data"].apply(lambda d: d == hoje)
            _datas_ordem = _por_dia.sort_values("data")["data_str"].tolist()
            _barras = pd.concat([
                _por_dia.assign(serie="Com contato", clientes=_por_dia["com"]),
                _por_dia.assign(serie="Sem contato", clientes=_por_dia["sem"]),
            ])[["data_str", "eh_hoje", "serie", "clientes"]]
            _x_dia = alt.X("data_str:O", title="DIA", sort=_datas_ordem, axis=alt.Axis(labelAngle=0))
            _bar_dia = alt.Chart(_barras).mark_bar(cornerRadiusEnd=2).encode(
                x=_x_dia,
                y=alt.Y("clientes:Q", title="CLIENTES"),
                color=alt.Color(
                    "serie:N", title=None,
                    scale=alt.Scale(domain=["Com contato", "Sem contato", "Total do dia"],
                                    range=["#22c55e", "#9ca3af", "#e8eaf0"]),
                    legend=None,
                ),
                opacity=alt.condition(alt.datum.eh_hoje, alt.value(0.45), alt.value(1.0)),
                tooltip=[
                    alt.Tooltip("data_str:O", title="Dia"),
                    alt.Tooltip("serie:N", title="Origem"),
                    alt.Tooltip("clientes:Q", title="Clientes"),
                ],
            )
            # Linha pontilhada = total do dia (com + sem contato), em valor
            # absoluto — mesma escala de cor, então entra na legenda.
            _base_tot_dia = alt.Chart(_por_dia.assign(serie="Total do dia")).encode(
                x=_x_dia,
                y=alt.Y("total:Q"),
                color=alt.Color("serie:N", legend=None),
                tooltip=[
                    alt.Tooltip("data_str:O", title="Dia"),
                    alt.Tooltip("total:Q", title="Total de regularizações"),
                    alt.Tooltip("com:Q", title="Com contato"),
                    alt.Tooltip("sem:Q", title="Sem contato"),
                ],
            )
            chart_dia = (
                _bar_dia
                + _base_tot_dia.mark_line(strokeDash=[4, 3], strokeWidth=1.5)
                + _base_tot_dia.mark_circle(size=35)
                + _base_tot_dia.mark_text(dy=-10, fontSize=10, fontWeight=700)
                .encode(text=alt.Text("total:Q"))
            ).properties(height=320)
            st.altair_chart(chart_dia, use_container_width=True)

    # ── Distribuição da Carteira (Donut) ──────────────────────────────────
    with g_dir:
        st.markdown(
            '<div style="font-size:14px;font-weight:700;color:#8b94a5;'
            'text-transform:uppercase;letter-spacing:1.5px;'
            'margin-top:24px;margin-bottom:12px">Distribuição da Carteira</div>',
            unsafe_allow_html=True,
        )
        # Mesma carteira do card Inadimplentes: total atual das duas
        # especialistas, sem quem regularizou hoje (filtros de Especialista e
        # Situação aplicados).
        carteira = pd.DataFrame([
            {"atendente": _norm_atendente_raw(c.get("_grupo")), "valor": float(c.get("valor") or 0)}
            for c in clientes
            if not c.get("_regularizado_hoje")
            and _eh_grupo_match(c)
            and _eh_situacao_match(c)
        ])
        if not carteira.empty:
            carteira_agg = (
                carteira.groupby("atendente")
                .agg(clientes=("valor", "count"), valor=("valor", "sum"))
                .reset_index()
            )
            _tot_cart = int(carteira_agg["clientes"].sum())
            carteira_agg["pct"] = carteira_agg["clientes"] / _tot_cart * 100
            # Quantidade dentro da fatia, % da carteira das duas do lado de fora
            carteira_agg["qtd_lbl"] = carteira_agg["clientes"].map(lambda n: f"{n:,}".replace(",", "."))
            carteira_agg["pct_lbl"] = carteira_agg["pct"].map(lambda v: f"{v:.2f}%".replace(".", ","))
            # Cor do número interno por fatia: escuro na fatia verde clara,
            # branco na verde escura (mesma ordem que a escala das fatias usa).
            _dom_cart = sorted(carteira_agg["atendente"].unique())
            _cor_interna = ["#0f1117" if c in ("#7cc243", "#a3d672") else "#ffffff"
                            for c in _CHART_PALETTE[:len(_dom_cart)]]
            _base_donut = alt.Chart(carteira_agg).encode(
                theta=alt.Theta("clientes:Q", title="Clientes", stack=True),
                color=alt.Color(
                    "atendente:N",
                    scale=alt.Scale(range=_CHART_PALETTE),
                    title="Especialista",
                ),
                tooltip=[
                    alt.Tooltip("atendente:N", title="Especialista"),
                    alt.Tooltip("clientes:Q", title="Clientes"),
                    alt.Tooltip("pct:Q", title="% da carteira", format=".2f"),
                    alt.Tooltip("valor:Q", title="R$ em aberto", format=",.2f"),
                ],
            )
            _centro = alt.Chart(pd.DataFrame({"t": [f"{_tot_cart:,}".replace(",", ".")]})).mark_text(
                fontSize=34, fontWeight=800, color="#e8eaf0", dy=-8,
            ).encode(text="t:N")
            _centro_sub = alt.Chart(pd.DataFrame({"t": ["CLIENTES"]})).mark_text(
                fontSize=14, fontWeight=700, color="#8b94a5", dy=18,
            ).encode(text="t:N")
            chart_donut = (
                _base_donut.mark_arc(innerRadius=62, outerRadius=122,
                                     stroke="#0f1117", strokeWidth=3)
                # Quantidade no meio da fatia
                + _base_donut.mark_text(radius=92, fontSize=20, fontWeight=800)
                .encode(
                    text="qtd_lbl:N",
                    color=alt.Color("atendente:N", legend=None,
                                    scale=alt.Scale(domain=_dom_cart, range=_cor_interna)),
                )
                # Percentual do lado de fora
                + _base_donut.mark_text(radius=152, fontSize=15, fontWeight=700)
                .encode(text="pct_lbl:N", color=alt.value("#cbd5e1"))
                + _centro + _centro_sub
            ).resolve_scale(color="independent").properties(height=320)
            st.altair_chart(chart_donut, use_container_width=True)
        else:
            st.info("Sem carteira atual pra mostrar distribuição.")

    st.markdown(_DIVIDER, unsafe_allow_html=True)

    # ── Base mensal de pagamentos (desde jun/26) ──────────────────────────
    # Alimenta o "Regularizações por Mês" e as Taxas Mensais. O gráfico
    # "Evolução Mensal de Pagamentos" que usava esta base foi removido:
    # contava todo pagamento (parcial, até 4 dias, sem contato) e repetia
    # o "Regularizações por Mês" (~97% de quem paga regulariza).
    # Começa em jun/2026 e cresce um ponto por mês. Antes eram 6 meses fixos,
    # que traziam abril (nenhum contato registrado: todo pagamento creditado
    # pelo grupo atual — trabalho que não aconteceu). Maio também fica fora:
    # o lote começou em 05/05 (19 dias) e os snapshots diários só em 20/05
    # (5 dias), então o mês não é comparável com os seguintes.
    _hoje_trend = date.fromisoformat(hoje_brt())
    _trend_inicio = date(2026, 6, 1)
    # Trend sempre inclui o mês corrente, então usa o carimbo do dia.
    df_trend = fetch_pagamentos_creditados(
        _trend_inicio.isoformat(), _hoje_trend.isoformat(), f"dia-{carimbo_dia_cache()}"
    )
    if not df_trend.empty:
        df_trend = df_trend.rename(columns={
            "id_sacado_sac": "id",
            "atendente_credito": "atendente",
        })
        df_trend["data_dt"] = pd.to_datetime(df_trend["dt_pagamento"], errors="coerce")
        df_trend = df_trend.dropna(subset=["data_dt"])
        # Adiciona linhas do overlay (mesmos critérios do df_reg principal)
        # pra que o mês atual reflita pagamentos detectados em real-time.
        # Sem isso, mês corrente subestima (faltam os pagamentos do dia).
        _trend_overlay = _build_overlay_rows(clientes, df_trend, _trend_inicio, _hoje_trend)
        if _trend_overlay:
            df_trend = pd.concat(
                [df_trend, pd.DataFrame(_trend_overlay)],
                ignore_index=True,
            )
        # Aplica filtro de Situação no trend também (consistência com o resto)
        if ids_situacao_ok is not None:
            df_trend = df_trend[df_trend["id"].astype(str).isin(ids_situacao_ok)]
        # Fora do gráfico: "Sem especialista" não é pessoa, é o balde de
        # clientes sem grupo — a linha dele no trend não representa trabalho de
        # ninguém. Filtra DEPOIS do overlay porque as linhas do overlay também
        # podem vir com esse rótulo. Mesma exclusão do ranking e da matriz.
        df_trend = df_trend[df_trend["atendente"] != "Sem especialista"]
        df_trend = _so_regua(df_trend)

    # ── Recuperação mensal: volume (barras) + taxas (linhas) ──────────────
    # Antes eram 5 linhas de volume no mesmo eixo: inadimplentes e contatados
    # ficavam lá em cima e as 3 de regularização coladas embaixo, e quando a
    # carteira caía tudo caía junto. Volume vira barra empilhada; o que
    # compara mês a mês são as taxas, que não dependem do tamanho da carteira.
    _serie_mes = {}
    df_serie = fetch_serie_carteira_mensal(
        _trend_inicio.isoformat(), _hoje_trend.isoformat(),
        f"dia-{carimbo_dia_cache()}|{_sit_bq}", _sit_bq
    )
    if not df_serie.empty:
        _serie = df_serie
        if filtro_esp:
            _serie = _serie[_serie["atendente"].isin(filtro_esp)]
        for _, r in _serie.groupby("mes").agg(
            inad=("inadimplentes", "sum"), cont=("contatados", "sum"),
            cont_base=("contatados_na_base", "sum"),
        ).reset_index().iterrows():
            _serie_mes[r["mes"]] = {"inad": int(r["inad"]), "cont": int(r["cont"]),
                                    "cont_base": int(r["cont_base"]),
                                    "reg_via": 0, "reg_esp": 0, "reg_total": 0}

    if not df_trend.empty:
        _pag = df_trend.copy()
        if filtro_esp:
            _pag = _pag[_pag["atendente"].isin(filtro_esp)]
        if not _pag.empty:
            _ev = fetch_eventos_regularizacao()
            _pag["id"] = _pag["id"].astype(str)
            _pag["mes"] = _pag["data_dt"].dt.strftime("%Y-%m")
            _pag["eh_reg_ev"] = _pag.apply(
                lambda r: (r["id"], r["data_dt"].strftime("%d/%m/%Y")) in _ev, axis=1
            )
            _pag["via"] = _pag["tipo_atribuicao"] == "via_contato"
            _pag["regua"] = (
                pd.to_numeric(_pag["atraso_dias"], errors="coerce").fillna(99)
                if "atraso_dias" in _pag.columns else pd.Series(99, index=_pag.index)
            ) >= 5
            _pag["r_via"] = _pag["eh_reg_ev"] & _pag["via"] & _pag["regua"]
            _pag["r_esp"] = _pag["eh_reg_ev"] & ~_pag["via"] & _pag["regua"]
            _cli_mes = (
                _pag.groupby(["mes", "id"])
                .agg(reg=("eh_reg_ev", "any"), r_via=("r_via", "any"), r_esp=("r_esp", "any"))
                .reset_index()
            )
            # Com contato x sem contato, igual às colunas da tabela.
            _cli_mes["reg_via"] = _cli_mes["r_via"]
            _cli_mes["reg_esp"] = _cli_mes["r_esp"] & ~_cli_mes["r_via"]
            for _, r in _cli_mes.groupby("mes").agg(
                reg_via=("reg_via", "sum"), reg_esp=("reg_esp", "sum"),
                reg_total=("reg", "sum"),
            ).reset_index().iterrows():
                _d = _serie_mes.setdefault(
                    r["mes"], {"inad": 0, "cont": 0, "cont_base": 0,
                               "reg_via": 0, "reg_esp": 0, "reg_total": 0}
                )
                _d["reg_via"] = int(r["reg_via"])
                _d["reg_esp"] = int(r["reg_esp"])
                _d["reg_total"] = int(r["reg_total"])

    def _mes_label_pt(ym):
        _a, _m = ym.split("-")
        return f"{_MESES_PT[int(_m)]}/{_a[2:]}"

    _meses_funil = sorted(_serie_mes)
    _ordem_lbl = [_mes_label_pt(m) for m in _meses_funil]

    if _meses_funil:
        _vol, _taxas, _topo = [], [], []
        for _m_key in _meses_funil:
            d = _serie_mes[_m_key]
            lbl = _mes_label_pt(_m_key)
            _vol.append({"mes": lbl, "serie": "Com contato", "clientes": d["reg_via"]})
            _vol.append({"mes": lbl, "serie": "Sem contato", "clientes": d["reg_esp"]})
            # Rótulo em cima da barra: total e % da carteira (mesma conta da
            # coluna "% da carteira": Reg. total ÷ inadimplentes 5+ do mês).
            _tot_m = d["reg_via"] + d["reg_esp"]
            _pct_m = (_tot_m / d["inad"] * 100) if d["inad"] else None
            _topo.append({
                "mes": lbl, "total": _tot_m, "inad": d["inad"],
                "pct": _pct_m if _pct_m is not None else 0.0,
                "rotulo": (f"{_tot_m} · {_pct_m:.2f}%".replace(".", ",")
                           if _pct_m is not None else str(_tot_m)),
            })
            # Taxas na mesma base da tabela: inadimplentes com 5+ dias.
            # Sem contato = base que NÃO foi contatada no mês.
            _sem_contato = max(d["inad"] - d.get("cont_base", 0), 0)
            if d["inad"]:
                _taxas.append({"mes": lbl, "serie": "Cobertura (%)",
                               "pct": d["cont"] / d["inad"] * 100})
            # Conversão com contato = EFICÁCIA do mês (mesma conta da tabela:
            # dos contatados no mês, % que regularizaram com contato durante o
            # atraso). A linha "sem contato" saiu: o lote prioriza os piores
            # casos, então comparar com quem não foi contatado induzia a
            # concluir que o contato não adianta.
            # Eficácia do mês = Reg. com contato ÷ contatados (mesma conta da
            # tabela), com as regularizações no mês do pagamento.
            _ef_mes = (d["reg_via"] / d["cont"] * 100) if d["cont"] else None
            if _ef_mes is not None:
                _taxas.append({"mes": lbl, "serie": "Eficácia do contato (%)",
                               "pct": _ef_mes})

        g_vol, g_tx = st.columns(2)
        with g_vol:
            st.markdown(
                '<div style="font-size:14px;font-weight:700;color:#8b94a5;'
                'text-transform:uppercase;letter-spacing:1.5px;'
                'margin-bottom:4px">Regularizações por Mês</div>'
                '<div style="font-size:11px;color:#8b94a5;margin-bottom:8px">'
                'Clientes que regularizaram o atraso no mês, com ou sem contato durante o atraso.'
                '</div>'
                + _legenda_html([("Com contato", "#22c55e", "barra"),
                                 ("Sem contato", "#9ca3af", "barra"),
                                 ("% da carteira", "#e8eaf0", "linha")]),
                unsafe_allow_html=True,
            )
            _df_vol = pd.DataFrame(_vol)
            _base_vol = alt.Chart(_df_vol).encode(
                    x=alt.X("mes:O", title="MÊS", sort=_ordem_lbl, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("clientes:Q", title="CLIENTES"),
                    color=alt.Color(
                        "serie:N", title=None,
                        scale=alt.Scale(domain=["Com contato", "Sem contato", "% da carteira"],
                                        range=["#22c55e", "#9ca3af", "#e8eaf0"]),
                        legend=None,
                    ),
                    tooltip=[
                        alt.Tooltip("mes:N", title="Mês"),
                        alt.Tooltip("serie:N", title="Origem"),
                        alt.Tooltip("clientes:Q", title="Clientes"),
                    ],
            )
            _rot_vol = _base_vol.mark_text(dy=12, fontSize=11, fontWeight=700).encode(
                text=alt.Text("clientes:Q"), color=alt.value("#0f1117")
            )
            # Linha pontilhada = % da carteira do mês (Reg. total ÷
            # inadimplentes com 5+ dias no mês), no eixo da direita.
            _df_topo = pd.DataFrame(_topo)
            _df_topo = _df_topo[_df_topo["inad"] > 0].copy()
            _df_topo["serie"] = "% da carteira"
            _df_topo["pct_lbl"] = _df_topo["pct"].map(lambda v: f"{v:.2f}%".replace(".", ","))
            _base_pct = alt.Chart(_df_topo).encode(
                x=alt.X("mes:O", sort=_ordem_lbl),
                y=alt.Y("pct:Q", title="% DA CARTEIRA",
                        scale=alt.Scale(domainMin=0, nice=True),
                        axis=alt.Axis(orient="right", grid=False)),
                color=alt.Color("serie:N", legend=None),
                tooltip=[
                    alt.Tooltip("mes:N", title="Mês"),
                    alt.Tooltip("total:Q", title="Regularizações"),
                    alt.Tooltip("inad:Q", title="Carteira do mês"),
                    alt.Tooltip("pct:Q", title="% da carteira", format=".2f"),
                ],
            )
            _linha_pct = (
                _base_pct.mark_line(strokeDash=[4, 3], strokeWidth=1.5)
                + _base_pct.mark_circle(size=45)
                + _base_pct.mark_text(dy=-12, fontSize=11, fontWeight=700)
                .encode(text=alt.Text("pct_lbl:N"))
            )
            chart_vol = (
                alt.layer(_base_vol.mark_bar(cornerRadiusEnd=2) + _rot_vol, _linha_pct)
                .resolve_scale(y="independent")
                .properties(height=320)
            )
            st.altair_chart(chart_vol, use_container_width=True)

        with g_tx:
            st.markdown(
                '<div style="font-size:14px;font-weight:700;color:#8b94a5;'
                'text-transform:uppercase;letter-spacing:1.5px;'
                'margin-bottom:4px">Taxas Mensais</div>'
                '<div style="font-size:11px;color:#8b94a5;margin-bottom:12px">'
                'Cobertura = contatados ÷ carteira do mês.<br>'
                'Eficácia = regularizações com contato ÷ contatados no mês.'
                '</div>'
                + _legenda_html([("Cobertura", "#9ca3af", "linha_cheia"),
                                 ("Eficácia do contato", "#22c55e", "linha_cheia")]),
                unsafe_allow_html=True,
            )
            _ordem_tx = ["Cobertura (%)", "Eficácia do contato (%)"]
            _df_tx = pd.DataFrame(_taxas)
            # Percentual sempre com 2 casas (padrão da tela), vírgula decimal
            _df_tx["pct_lbl"] = _df_tx["pct"].map(lambda v: f"{v:.2f}%".replace(".", ","))
            _cor_tx = alt.Color(
                "serie:N", title=None, sort=_ordem_tx,
                scale=alt.Scale(domain=_ordem_tx, range=["#9ca3af", "#22c55e"]),
                legend=None,
            )
            base_tx = alt.Chart(_df_tx).encode(
                x=alt.X("mes:O", title="MÊS", sort=_ordem_lbl,
                        axis=alt.Axis(labelAngle=0),
                        scale=alt.Scale(padding=0.22)),
                y=alt.Y("pct:Q", title="% DOS CLIENTES",
                        scale=alt.Scale(domainMin=0, nice=True)),
                color=_cor_tx,
                tooltip=[
                    alt.Tooltip("mes:N", title="Mês"),
                    alt.Tooltip("serie:N", title="Taxa"),
                    alt.Tooltip("pct:Q", title="%", format=".2f"),
                ],
            )
            _valores_tx = base_tx.mark_text(dy=-14, fontSize=11, fontWeight=600).encode(
                text=alt.Text("pct_lbl:N")
            )
            chart_tx = (
                base_tx.mark_line(strokeWidth=2.5, interpolate="monotone")
                + base_tx.mark_circle(size=80, stroke="#0f1117", strokeWidth=2)
                + _valores_tx
            ).properties(height=320)
            st.altair_chart(chart_tx, use_container_width=True)
    else:
        st.info("Sem dados mensais de recuperação.")
