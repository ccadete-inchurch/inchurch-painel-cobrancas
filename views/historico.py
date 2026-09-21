from datetime import date, datetime

import pandas as pd
import streamlit as st

from helpers import fmt_moeda_plain, get_effective_atendente, hoje_lote, carimbo_dia_cache
from data import (
    fetch_ids_em_qualquer_lote_hoje,
    fetch_cobrancas_liquidacao,
    fetch_eventos_regularizacao,
)


def _build_regularizados_fresh(store) -> list:
    """Rebuilda a lista de pagamentos do zero a cada render — BQ + overlay 3d.

    Por que: store['regularizados'] acumulava entries entre sessões via cache
    file (cache_dados.json). Cliente Sara que pagou 15/06 era adicionada via
    overlay; quando o BQ replicava no dia seguinte, BQ + overlay coexistiam
    com dedup imperfeito por (id, data). Resultado: a Pagamentos mostrava
    339 quando o BQ + overlay real era ~199.

    Aqui fazemos fresh: BQ tem nome/cnpj/inativo, overlay adiciona limbos
    (liquidados últimos 3d, crédito vindo). Sem persistência → sem acúmulo.
    """
    df_liq = fetch_cobrancas_liquidacao(dia=carimbo_dia_cache())
    regs = []
    if not df_liq.empty:
        for _, row in df_liq.iterrows():
            liq_raw = row.get("data_liquidacao")
            try:
                data_liq = (
                    datetime.strptime(str(liq_raw)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
                    if pd.notna(liq_raw) and liq_raw
                    else date.today().strftime("%d/%m/%Y")
                )
            except Exception:
                data_liq = date.today().strftime("%d/%m/%Y")
            regs.append({
                "id":        str(row["codigo"]),
                "nome":      str(row.get("nome") or ""),
                "cnpj":      str(row.get("cnpj") or ""),
                "valor":     float(row["valor"]) if pd.notna(row.get("valor")) else 0.0,
                "atendente": "Sistema (BigQuery)",
                "data":      data_liq,
                "tipo":      "auto",
                "inativo":   bool(row.get("inativo", False)),
            })

    # Adiciona overlay — MESMA lógica da tela Especialista pra uniformizar.
    # Itera store["clientes"] (atuais) e usa flags _regularizado_hoje/
    # _pago_parcial_hoje setadas pelo overlay (aplicar_pagamentos_hoje_no_store).
    # Cliente em-dia NÃO está em store["clientes"] → não entra. Cliente
    # limbo (pagou 15/06, crédito vindo) está com a flag setada → entra
    # com a data real do pagamento (_dt_liquidacao_real).
    existing = {(r["id"], r["data"]) for r in regs}
    for c in store.get("clientes", []):
        eh_reg = bool(c.get("_regularizado_hoje"))
        eh_parc = bool(c.get("_pago_parcial_hoje"))
        if not (eh_reg or eh_parc):
            continue
        # Só a parte ATRASADA — esta tela lista pagamentos de cobrança
        # atrasada (a consulta do BQ filtra dt_liquidacao > dt_vencimento).
        # O overlay somava tudo, inclusive quem pagou em dia ou adiantado.
        dt_real = c.get("_dt_liquidacao_atraso")
        if dt_real is None:
            continue
        valor = float(c.get("_valor_pago_atraso") or 0)
        if valor <= 0:
            continue
        cid = str(c.get("id") or "")
        data_liq_br = dt_real.strftime("%d/%m/%Y")
        if (cid, data_liq_br) in existing:
            continue
        regs.append({
            "id":        cid,
            "nome":      str(c.get("nome") or ""),
            "cnpj":      str(c.get("cnpj") or ""),
            "valor":     valor,
            "atendente": "",  # resolvido via get_effective_atendente
            "data":      data_liq_br,
            "tipo":      "overlay",
            "inativo":   bool(c.get("_inativo", False)),
        })
    return regs


def _render_historico(store):
    st.markdown(
        '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:36px;'
        'font-weight:800;color:#e8eaf0;margin-top:24px;margin-bottom:24px;letter-spacing:-1px;line-height:1.1">'
        'Pagamentos em Atraso</div>',
        unsafe_allow_html=True,
    )

    # Alerta se credenciais Superlogica ausentes: sem elas, a API SL nao e'
    # consultada e pagamentos so aparecem quando o BQ replica (1-2d depois).
    # Ja perdemos 3 clientes regularizados hoje por causa disso (ago/2026).
    if "superlogica" not in st.secrets:
        st.error(
            "❌ **Overlay de pagamentos DESATIVADO** — credenciais do Superlógica não configuradas. "
            "Pagamentos de hoje não aparecerão aqui, nem badges de regularização/parcial "
            "nas telas Atividades e Inadimplência. O painel só verá o pagamento quando "
            "o BQ replicar (1-2 dias depois).\n\n"
            "**Como consertar:** Streamlit Cloud → Settings → Secrets, adicionar:\n"
            "```toml\n[superlogica]\napp_token    = \"...\"\naccess_token = \"...\"\n```"
        )

    # Rebuilda fresh do BQ + overlay a cada render — não usa mais
    # store["regularizados"] (que acumulava via cache file).
    with st.spinner("Carregando pagamentos..."):
        reg = _build_regularizados_fresh(store)
    if not reg:
        st.info("Nenhum cliente regularizado ainda.")
        return

    df = pd.DataFrame(reg)
    # Uma linha por cliente e dia: a consulta vem por BOLETO, então quem
    # pagou dois boletos no mesmo dia aparecia duas vezes (Mevam Almada em
    # 04/09/2026: R$ 1.029,90 + R$ 394,97). O overlay só entra quando o
    # (cliente, dia) ainda não veio do BQ, então não mistura as duas fontes.
    if not df.empty:
        df = df.groupby(["id", "data"], as_index=False, sort=False).agg(
            nome=("nome", "first"),
            cnpj=("cnpj", "first"),
            valor=("valor", "sum"),
            atendente=("atendente", "first"),
            tipo=("tipo", "first"),
            inativo=("inativo", "max"),
            n_boletos=("valor", "size"),
        )

    # Resolve atendente: grupo (splgc-grupo) primeiro, painel_tarefas_diarias
    # como fallback. get_effective_atendente já encapsula essa lógica.
    def _resolve_atendente(row):
        at = str(row.get("atendente") or "").strip()
        if at and "BigQuery" not in at:
            return at
        return get_effective_atendente(str(row.get("id") or "")) or "—"

    if not df.empty:
        df["atendente"] = df.apply(_resolve_atendente, axis=1)

    # Ordena por data desc (mais recentes primeiro). Pagamentos via overlay
    # da API entram com data de hoje — sem sort ficariam escondidos no fim
    # da lista, depois dos registros históricos do BQ.
    if not df.empty and "data" in df.columns:
        df["_data_dt"] = pd.to_datetime(df["data"], format="%d/%m/%Y", errors="coerce")
        df = df.sort_values("_data_dt", ascending=False, na_position="last").drop(columns=["_data_dt"])

    # ── Filtros ───────────────────────────────────────────────────────────────
    atendentes_disp = sorted({a for a in df["atendente"].unique() if a and a != "—"}) if not df.empty else []

    hoje_br_pre = date.fromisoformat(hoje_lote())
    # Default: mês corrente (1º dia → hoje)
    _ini_default = hoje_br_pre.replace(day=1)

    fb, fp, fs, fa, fl = st.columns([2.2, 2.0, 1.3, 1.4, 1.3])
    with fb:
        busca = st.text_input("Buscar", placeholder="Nome, CNPJ ou ID sacado...", key="reg_busca")
    with fp:
        # Date range picker — qualquer intervalo de datas
        intervalo_selecionado = st.date_input(
            "Período (de → até)",
            value=(_ini_default, hoje_br_pre),
            key="reg_periodo_range",
            format="DD/MM/YYYY",
        )
    with fs:
        filtro_sit = st.selectbox("Situação", ["Todos", "Apenas ativos", "Apenas inativos"], key="reg_sit")
    with fa:
        filtro_atd = st.multiselect(
            "Grupo",
            atendentes_disp + (["Sem especialista"] if (not df.empty and (df["atendente"] == "—").any()) else []),
            key="reg_atd",
            placeholder="Todos",
        )
    with fl:
        # Só quem está no lote de hoje (qualquer atendente). Filtro em vez de
        # selo: pagamento antigo de quem voltou ao lote não ganha marca na
        # linha (parecia conversão do dia), mas dá pra achar esses clientes.
        # Selectbox (igual a Situação): o segmented_control quebrava em duas
        # linhas no notebook.
        _lote_sel = st.selectbox("Lote", ["Todos", "No lote hoje"], key="reg_lote")
    filtro_lote = _lote_sel == "No lote hoje"

    if busca:
        b = busca.lower()
        df = df[df.apply(lambda r: b in str(r.get("nome","")).lower() or b in str(r.get("cnpj","")).lower(), axis=1)]
    if filtro_sit == "Apenas ativos" and "inativo" in df.columns:
        df = df[~df["inativo"].fillna(False).astype(bool)]
    elif filtro_sit == "Apenas inativos" and "inativo" in df.columns:
        df = df[df["inativo"].fillna(False).astype(bool)]
    # Multi-select: lista de grupos selecionados. Vazio = todos (sem filtro).
    if filtro_atd:
        _sem_esp_sel = "Sem especialista" in filtro_atd
        _grupos_sel = [g for g in filtro_atd if g != "Sem especialista"]
        _mask_sem = (df["atendente"] == "—") if _sem_esp_sel else pd.Series(False, index=df.index)
        _mask_grp = df["atendente"].isin(_grupos_sel) if _grupos_sel else pd.Series(False, index=df.index)
        df = df[_mask_sem | _mask_grp]

    # IDs do lote de hoje: usados no checkbox e no destaque verde da tabela
    ids_lote_hoje = fetch_ids_em_qualquer_lote_hoje()
    if filtro_lote and not df.empty:
        df = df[df["id"].astype(str).isin(ids_lote_hoje)]

    # Filtro temporal via date range picker — orquestra cards + tabela.
    # st.date_input com value tupla retorna tupla (dt_ini, dt_fim) quando
    # ambas datas escolhidas; tupla com 1 item enquanto user escolhe a 2ª.
    dt_ini, dt_fim = None, None
    if isinstance(intervalo_selecionado, tuple):
        if len(intervalo_selecionado) == 2:
            dt_ini, dt_fim = intervalo_selecionado
        elif len(intervalo_selecionado) == 1:
            dt_ini = dt_fim = intervalo_selecionado[0]
    elif intervalo_selecionado:  # date single
        dt_ini = dt_fim = intervalo_selecionado

    if dt_ini and dt_fim and not df.empty:
        df = df.copy()
        df["_dt_temp"] = pd.to_datetime(df["data"], format="%d/%m/%Y", errors="coerce")
        df = df[(df["_dt_temp"].dt.date >= dt_ini) & (df["_dt_temp"].dt.date <= dt_fim)]
        df = df.drop(columns=["_dt_temp"])

    # Label do período pra usar nos cards (texto curto). Ambas as datas
    # mostram o ano completo pra evitar ambiguidade entre anos diferentes.
    if dt_ini and dt_fim:
        if dt_ini == dt_fim:
            periodo = dt_ini.strftime("%d/%m/%Y")
        else:
            periodo = f"{dt_ini.strftime('%d/%m/%Y')} → {dt_fim.strftime('%d/%m/%Y')}"
    else:
        periodo = "Período"

    # ── Métricas ──────────────────────────────────────────────────────────────
    # Cards driven pelo período selecionado — df já está filtrado por período.
    hoje_br = date.fromisoformat(hoje_lote())
    hoje_str = hoje_br.strftime("%d/%m/%Y")

    # Pagamentos no Período = todos os pagamentos do df filtrado
    if not df.empty:
        n_periodo = int(df["id"].astype(str).nunique())
        v_periodo = float(df["valor"].sum())
    else:
        n_periodo = 0
        v_periodo = 0.0

    # Regularizações no Período = subset que efetivamente regularizou
    # Combina 2 fontes: overlay HOJE (real-time) + histórico (BQ cross-check)
    ids_reg_hoje_all = {
        str(c.get("id") or "") for c in store.get("clientes", [])
        if c.get("_regularizado_hoje")
    }
    # Lookup do cliente atual em store["clientes"] pra puxar saldo/acordo
    # e pra check de regularização operacional (sem saldo = regularizou).
    _clientes_lookup = {
        str(c.get("id") or ""): c for c in store.get("clientes", []) or []
    }

    if not df.empty:
        # Eventos historicos de regularizacao via analise direta de liquidacoes.
        # Pra cada pagamento (cid, data_pag), verifica se apos esse pagamento
        # sobrou algum boleto vencido em aberto. Sem sobra = regularizacao.
        #
        # Preserva o evento no seu contexto temporal: cliente que regularizou
        # em maio + reincidiu em julho conta como REG em maio (nao vira parcial
        # retroativamente). Cliente que pagou parcial em maio + completou em
        # julho conta como PARCIAL em maio + REG em julho (nao ambos como REG).
        #
        # Fallback pra pagamentos dos ultimos 3 dias: BQ pode nao ter replicado
        # ainda, entao usa overlay (ids_reg_hoje_all) como source of truth.
        eventos_reg = fetch_eventos_regularizacao()
        from datetime import datetime as _dt_c, date as _dc

        def _eh_reg(r):
            _rid = str(r.get("id") or "")
            _data_pag = str(r.get("data") or "")
            if (_rid, _data_pag) in eventos_reg:
                return True
            # Fallback pra pagamentos recentes (ultimos 10d) — BQ ainda pode
            # nao ter replicado, overlay via API SL preenche a lacuna. 10 dias
            # = mesma janela do overlay (fetch_pagamentos_hoje_api). Com 3, um
            # pagamento de 4-10 dias atras que o BQ ainda nao tivesse caia como
            # "nao regularizou" e o cliente aparecia como parcial.
            try:
                d_pag = _dt_c.strptime(_data_pag, "%d/%m/%Y").date()
                if (_dc.today() - d_pag).days <= 10:
                    return _rid in ids_reg_hoje_all
            except Exception:
                pass
            return False

        df_reg_periodo = df[df.apply(_eh_reg, axis=1)]
        n_reg = int(df_reg_periodo["id"].astype(str).nunique()) if not df_reg_periodo.empty else 0
        v_reg = float(df_reg_periodo["valor"].sum()) if not df_reg_periodo.empty else 0.0
    else:
        n_reg = 0
        v_reg = 0.0

    # Taxa de regularização (% pagantes que zeraram tudo)
    taxa_reg = (n_reg / n_periodo * 100) if n_periodo > 0 else 0.0

    m1, m2, m3 = st.columns(3)
    _tooltip_pag = (
        f"Pagamentos de cobranças em atraso feitos por clientes inadimplentes "
        f"no período ({periodo}). Inclui quem pagou parte e quem quitou tudo."
    )
    _tooltip_reg = (
        f"Clientes que quitaram todo o atraso no período ({periodo}) e "
        f"deixaram de ser inadimplentes. Parte dos Pagamentos em Atraso."
    )
    _tooltip_taxa = (
        "Dos clientes inadimplentes que pagaram no período, quantos % "
        "quitaram todo o atraso."
    )
    # Cards adaptam label ao período. Tipo "moeda" formata R$, "pct" formata %.
    # Taxa de Regularização tem sub-texto diferente (X de Y, não 'X regularizaram').
    _sub_taxa = (
        f'{n_reg} de {n_periodo} '
        f'{"inadimplente quitou" if n_periodo == 1 else "inadimplentes quitaram"} tudo'
    ) if n_periodo > 0 else "sem pagamentos no período"
    _sub_pag = (
        f'{n_periodo} {"cliente inadimplente pagou" if n_periodo == 1 else "clientes inadimplentes pagaram"}'
    )
    _sub_reg = (
        f'{n_reg} {"cliente quitou" if n_reg == 1 else "clientes quitaram"} todo o atraso'
    )
    cards = [
        (m1, f"Pagamentos em Atraso · {periodo}", fmt_moeda_plain(v_periodo), _sub_pag,  _tooltip_pag,  "#2dd36f"),
        (m2, f"Regularizações · {periodo}", fmt_moeda_plain(v_reg),     _sub_reg,  _tooltip_reg,  "#2dd36f"),
        (m3, "Taxa de Regularização",       f"{taxa_reg:.2f}%",         _sub_taxa, _tooltip_taxa, "#5fa3ff"),
    ]
    for col, label, valor_str, sub, tooltip, cor_valor in cards:
        with col:
            title_attr = f' title="{tooltip}"' if tooltip else ""
            cursor = "help" if tooltip else "default"
            st.markdown(
                f'<div class="metric-card" style="cursor:{cursor};padding:18px 20px"{title_attr}>'
                f'<div class="metric-label" style="font-size:14px;letter-spacing:1.3px">{label}</div>'
                f'<div style="font-size:30px;font-weight:800;color:{cor_valor};margin-top:6px;'
                f'line-height:1.1;font-variant-numeric:tabular-nums">{valor_str}</div>'
                f'<div class="metric-sub" style="font-size:14px;margin-top:8px">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ── Tabela ────────────────────────────────────────────────────────────────
    # Cliente primeiro pra receber o destaque visual do LOTE (faixa lateral)
    # de forma natural na lateral esquerda da tabela.
    col_w = [3, 1.2, 1.8, 1.5, 1.5]
    hdrs  = ["Cliente", "Data de Pag.", "CNPJ", "Valor", "Especialista"]

    hdr_cells = "".join(
        f'<div style="flex:{w};padding:14px 14px;font-size:12px;text-transform:uppercase;'
        f'letter-spacing:1.2px;color:#8b94a5;font-weight:700;white-space:nowrap">{h}</div>'
        for w, h in zip(col_w, hdrs)
    )
    st.markdown(
        f'<div style="display:flex;gap:1rem;background:#1e2333;border:1px solid #2a2f42;'
        f'border-radius:12px 12px 0 0;overflow:hidden">{hdr_cells}</div>',
        unsafe_allow_html=True,
    )

    if df.empty:
        st.markdown(
            '<div style="background:#181c26;border:1px solid #2a2f42;border-top:none;'
            'border-radius:0 0 12px 12px;padding:60px;text-align:center;color:#6b7280;font-size:14px">'
            'Nenhum resultado.</div>',
            unsafe_allow_html=True,
        )
        return

    PAGE_SIZE = 100
    total_f   = len(df)
    total_pg  = max(1, -(-total_f // PAGE_SIZE))
    page      = max(1, min(st.session_state.get("reg_page", 1), total_pg))
    rows      = df.iloc[(page - 1) * PAGE_SIZE : page * PAGE_SIZE].to_dict("records")
    n = len(rows)

    # ids_lote_hoje (lá em cima): marca verde a conversão do dia — cliente
    # trabalhado no lote E pagou hoje.

    for i, row in enumerate(rows):
        inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:4px">INATIVO</span>' if row.get("inativo") else ""
        # Badge "REGULARIZADO" — mesma regra dos cards (_eh_reg): o pagamento
        # zerou tudo que estava vencido NAQUELE dia (evento), com o overlay da
        # API pros últimos 10 dias. Antes olhava se o cliente estava na
        # carteira HOJE: quem regularizou e voltou a atrasar via o pagamento
        # antigo virar "PAGAMENTO PARCIAL".
        _rid = str(row.get("id") or "")
        _rdt = str(row.get("data") or "")
        _cli_atual = _clientes_lookup.get(_rid)
        eh_regularizado = _eh_reg(row)
        # Regularizou naquela data, mas hoje deve de novo (boleto novo
        # venceu depois). Sem o aviso, "REGULARIZADO" + "no lote hoje"
        # parecia contradição.
        voltou_atrasar = bool(
            eh_regularizado and _cli_atual
            and not _cli_atual.get("_regularizado_hoje")
            and (_cli_atual.get("dias_atraso") or 0) > 0
        )
        # Voltou a atrasar: selo em cinza (o verde passava "resolvido", mas
        # o cliente deve de novo). O fato da data continua registrado.
        _reg_cor = ("background:rgba(156,163,175,.18);color:#9ca3af;" if voltou_atrasar
                    else "background:rgba(45,211,111,.18);color:#2dd36f;")
        reg_badge = (
            f'<span style="{_reg_cor}'
            'font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;'
            'margin-right:4px">✓ REGULARIZADO</span>' if eh_regularizado else ""
        )
        if voltou_atrasar:
            reg_badge += (
                '<span style="color:#f59e0b;font-size:11px;font-style:italic;'
                'margin-right:6px">· voltou a atrasar</span>'
            )
        # Badge PAGAMENTO PARCIAL (azul) — pagou algo mas não zerou a dívida.
        # Mutuamente exclusivo com REGULARIZADO.
        parcial_badge = (
            '<span style="background:rgba(95,163,255,.18);color:#5fa3ff;'
            'font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;'
            'margin-right:4px">PAGAMENTO PARCIAL</span>' if not eh_regularizado else ""
        )
        # Badge ACORDO (amarelo) — só pra clientes AINDA na carteira.
        acordo_badge = ""
        if _cli_atual and not eh_regularizado:
            if _cli_atual.get("_tem_acordo"):
                acordo_badge = (
                    '<span style="background:rgba(245,158,11,.2);color:#f59e0b;'
                    'font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;'
                    'margin-right:4px">ACORDO</span>'
                )
        # Marca conversão: cliente do lote de hoje que pagou (parcial OU
        # regularização). Faixa verde lateral + tint sutil na célula
        # Cliente — espelha o TOP em Inadimplentes (.04 bg, .6 border).
        # Sem badge LOTE: tint verde já comunica "veio do lote", e badge
        # competia com REGULARIZADO/PARCIAL ali do lado.
        # Só a linha do pagamento de HOJE: antes pintava qualquer pagamento
        # antigo de quem voltou ao lote, e o verde parecia conversão do dia.
        # Pagamento com data de ontem que só chegou hoje pela API foi ANTES
        # do lote de hoje, então também não conta.
        em_lote_hoje = _rid in ids_lote_hoje and _rdt == hoje_str
        cli_bg = "background:rgba(45,211,111,.04);" if em_lote_hoje else ""
        cli_bl = "border-left:4px solid rgba(45,211,111,.6);" if em_lote_hoje else ""
        rcols = st.columns(col_w)
        with rcols[0]:
            badges_html = f'{reg_badge}{parcial_badge}{acordo_badge}{inativo_badge}'
            badges_line = f'<div style="margin-bottom:2px">{badges_html}</div>' if badges_html else ''
            st.markdown(
                f'<div style="padding:12px 14px;{cli_bg}{cli_bl}">'
                f'{badges_line}'
                f'<div style="font-size:14px;font-weight:600;color:#e8eaf0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{row.get("nome","—")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with rcols[1]:
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;color:#8b94a5">{row.get("data","—")}</div>', unsafe_allow_html=True)
        with rcols[2]:
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;color:#8b94a5">{row.get("cnpj","—")}</div>', unsafe_allow_html=True)
        with rcols[3]:
            # fmt_moeda_plain (não fmt_moeda) — fmt_moeda colore valores altos
            # em vermelho/âmbar como ALERTA (desenhado pra dívidas em
            # Inadimplência). Aqui é PAGAMENTO recebido → tudo verde.
            # "· N boletos" só quando o cliente pagou mais de um no mesmo dia
            _nb = int(row.get("n_boletos") or 1)
            _nb_html = (f'<div style="font-size:11px;color:#8b94a5;font-weight:500;margin-top:2px">'
                        f'{_nb} boletos</div>') if _nb > 1 else ""
            st.markdown(f'<div style="padding:12px 14px;font-size:14px;font-weight:600;color:#2dd36f">{fmt_moeda_plain(row.get("valor",0))}{_nb_html}</div>', unsafe_allow_html=True)
        with rcols[4]:
            _at_txt = str(row.get("atendente") or "—")
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;color:#8b94a5">{_at_txt}</div>', unsafe_allow_html=True)

        if i < n - 1:
            st.markdown('<div style="height:0.5px;background:#2a2f42;margin:0"></div>', unsafe_allow_html=True)

    st.markdown(
        f'<div style="background:#1e2333;border:1px solid #2a2f42;border-top:none;'
        f'border-radius:0 0 12px 12px;padding:10px 16px;display:flex;justify-content:space-between;font-size:12px;color:#6b7280">'
        f'<span>Mostrando {(page-1)*PAGE_SIZE+1}–{min(page*PAGE_SIZE, total_f)} de {total_f} pagamentos</span>'
        f'<span>Página {page} de {total_pg}</span></div>',
        unsafe_allow_html=True,
    )

    if total_pg > 1:
        st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)
        pc1, pc2, pc3 = st.columns([1, 2, 1])
        with pc1:
            if st.button("← Anterior", key="reg_prev", disabled=(page <= 1), width="stretch"):
                st.session_state["reg_page"] = page - 1
                st.rerun()
        with pc2:
            st.markdown(f'<div style="text-align:center;color:#6b7280;font-size:12px;padding-top:6px">Página {page} de {total_pg}</div>', unsafe_allow_html=True)
        with pc3:
            if st.button("Próxima →", key="reg_next", disabled=(page >= total_pg), width="stretch"):
                st.session_state["reg_page"] = page + 1
                st.rerun()
