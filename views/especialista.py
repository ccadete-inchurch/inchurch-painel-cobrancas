from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from auth import current_role
from data import _EMAIL_GRUPO, fetch_pagamentos_creditados, fetch_eficacia_por_especialista
from helpers import fmt_moeda_plain


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
    if role != "admin":
        st.error("Acesso restrito — apenas Admin.")
        return

    # ── Header ────────────────────────────────────────────────────────────
    st.markdown(
        '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:36px;'
        'font-weight:800;color:#e8eaf0;margin-top:24px;margin-bottom:24px;letter-spacing:-1px;line-height:1.1">'
        'Especialista</div>',
        unsafe_allow_html=True,
    )

    # ── Filtros: Período, Especialista, Situação ─────────────────────────
    fp1, fp2, fp3, _ = st.columns([2, 2, 2, 2])
    with fp1:
        periodo = st.selectbox(
            "Período",
            ["Este mês", "Últimos 30 dias", "Últimos 90 dias", "Mês anterior", "Últimos 12 meses"],
            key="esp_periodo",
        )
    with fp3:
        filtro_situacao = st.selectbox(
            "Situação",
            ["Todos", "Apenas ativos", "Apenas inativos"],
            key="esp_situacao",
        )

    hoje = date.today()
    if periodo == "Este mês":
        dt_inicio = hoje.replace(day=1)
        dt_fim = hoje
    elif periodo == "Últimos 30 dias":
        dt_inicio = hoje - timedelta(days=30)
        dt_fim = hoje
    elif periodo == "Últimos 90 dias":
        dt_inicio = hoje - timedelta(days=90)
        dt_fim = hoje
    elif periodo == "Mês anterior":
        primeiro_dia_atual = hoje.replace(day=1)
        dt_fim = primeiro_dia_atual - timedelta(days=1)
        dt_inicio = dt_fim.replace(day=1)
    else:  # Últimos 12 meses
        dt_inicio = hoje - timedelta(days=365)
        dt_fim = hoje

    # ── Fonte: BQ JOIN com tarefas — atribui por contato efetivo ──────────
    # painel_tarefas_diarias + liquidações → último atendente que teve
    # contato (msg/lig) antes do pagamento. Credita quem trabalhou o caso,
    # não o grupo atual do cliente.
    with st.spinner("Carregando pagamentos creditados..."):
        df_reg = fetch_pagamentos_creditados(dt_inicio.isoformat(), dt_fim.isoformat())

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

    # ── Overlay real-time: pagamentos via API Superlógica HOJE ─────────────
    # BQ replica 1×/dia (lag), então pagamentos de hoje só aparecem amanhã
    # no df_reg. O overlay (store["clientes"] com _regularizado_hoje /
    # _pago_parcial_hoje) preenche essa lacuna. Mesma lógica da tela
    # Pagamentos — Especialista também fica real-time.
    if hoje >= dt_inicio and hoje <= dt_fim:
        hoje_dt = pd.to_datetime(hoje.isoformat())
        # Evita duplicata: ids que já estão em df_reg pra HOJE (caso BQ tenha
        # replicado mais cedo do que esperado)
        ids_hoje_bq = set()
        if not df_reg.empty:
            _mask = df_reg["data_dt"].dt.date == hoje
            ids_hoje_bq = set(df_reg.loc[_mask, "id"].astype(str))

        overlay_rows = []
        for c in clientes:
            eh_reg = bool(c.get("_regularizado_hoje"))
            eh_parc = bool(c.get("_pago_parcial_hoje"))
            if not (eh_reg or eh_parc):
                continue
            cid = str(c.get("id") or "")
            if cid in ids_hoje_bq:
                continue
            valor_hoje = float(c.get("_valor_pago_hoje") or 0)
            if valor_hoje <= 0:
                continue
            atendente = _norm_atendente_raw(c.get("_grupo"))
            overlay_rows.append({
                "id": cid,
                "atendente": atendente,
                "valor": valor_hoje,
                "dt_pagamento": hoje.isoformat(),
                "data_dt": hoje_dt,
                "eh_regularizacao": eh_reg,
                "eh_parcial": eh_parc,
                # Sem distinção de via_contato pra overlay (não temos rastro
                # do contato em real-time). Default conservador: via_contato.
                "tipo_atribuicao": "via_contato",
            })
        if overlay_rows:
            df_reg = pd.concat(
                [df_reg, pd.DataFrame(overlay_rows)],
                ignore_index=True,
            )

    with fp2:
        especialistas_disp = sorted(
            set(df_reg["atendente"].unique())
            | set(_EMAIL_GRUPO.values())
        )
        filtro_esp = st.selectbox(
            "Especialista",
            ["Todos"] + especialistas_disp,
            key="esp_filtro",
        )

    # Helpers de filtro pra carteira atual (clientes)
    def _eh_grupo_match(c):
        if filtro_esp == "Todos":
            return True
        return _norm_atendente_raw(c.get("_grupo")) == filtro_esp
    def _eh_situacao_match(c):
        if filtro_situacao == "Todos":
            return True
        if filtro_situacao == "Apenas ativos":
            return not c.get("_inativo")
        return bool(c.get("_inativo"))

    # Set de IDs ativos/inativos baseado no filtro de situação — usado pra
    # cruzar com df_per (pagamentos histórico). Quando filtro é "Todos",
    # mantém None e não aplica restrição. Senão, restringe aos IDs que
    # batem com a situação atual.
    if filtro_situacao == "Todos":
        ids_situacao_ok = None
    else:
        ids_situacao_ok = {
            str(c.get("id") or "") for c in clientes if _eh_situacao_match(c)
        }

    # df_per_all: período inteiro (BQ já filtrou por data) — média da equipe.
    # Aplica filtro de Situação cruzando com IDs da carteira atual.
    df_per_all = df_reg
    if ids_situacao_ok is not None:
        df_per_all = df_per_all[df_per_all["id"].astype(str).isin(ids_situacao_ok)]
    # df_per: também filtrado por especialista (cards individuais)
    df_per = df_per_all.copy()
    if filtro_esp != "Todos":
        df_per = df_per[df_per["atendente"] == filtro_esp]

    # ── Cards agregados ───────────────────────────────────────────────────
    total_pgto = int(df_per["id"].astype(str).nunique()) if not df_per.empty else 0
    total_valor = float(df_per["valor"].sum()) if not df_per.empty else 0.0
    total_reg = int(df_per[df_per["eh_regularizacao"]]["id"].astype(str).nunique()) if not df_per.empty else 0
    total_parc = int(df_per[df_per["eh_parcial"]]["id"].astype(str).nunique()) if not df_per.empty else 0
    inadimplentes_atual = sum(
        1 for c in clientes
        if not c.get("_regularizado_hoje")
        and _eh_grupo_match(c)
        and _eh_situacao_match(c)
    )
    taxa_reg = (total_reg / total_pgto * 100) if total_pgto else 0

    # Sub-texto contextual no 'Pagamentos' — se filtrando por 1 especialista,
    # mostra comparativo com a média da equipe.
    team_especialistas = int(df_per_all["atendente"].nunique()) if not df_per_all.empty else 0
    team_total_pgto = int(df_per_all["id"].astype(str).nunique()) if not df_per_all.empty else 0
    media_por_esp = (team_total_pgto / team_especialistas) if team_especialistas else 0
    if filtro_esp != "Todos" and team_especialistas:
        diff_pct = ((total_pgto - media_por_esp) / media_por_esp * 100) if media_por_esp else 0
        sinal = "+" if diff_pct >= 0 else ""
        cor_diff = "#22c55e" if diff_pct >= 0 else "#ef4444"
        sub_pag = (
            f'<span style="color:{cor_diff};font-weight:600">{sinal}{diff_pct:.0f}%</span> '
            f'<span style="color:#8b94a5">vs média</span>'
        )
    else:
        sub_pag = "no período"

    # Tooltips dos cards
    _tt_inad = (
        "Total de clientes inadimplentes na carteira HOJE (snapshot atual). "
        "Equivale ao 'Total Clientes' da tela Inadimplência."
    )
    _tt_pag = (
        "Clientes únicos que fizeram pagamento de cobrança ATRASADA no período "
        "(dt_liquidacao > dt_vencimento). Não inclui pagamentos em dia."
    )
    _tt_reg = (
        "Clientes que pagaram cobrança atrasada E não estão mais inadimplentes hoje. "
        "Conta SÓ pagamentos efetivos — não inclui baixas administrativas, "
        "parcelamentos ou desativações. Pra ver toda saída da carteira "
        "(incluindo esses motivos), ver 'Regularizados' da tela Inadimplência."
    )
    _tt_parc = (
        "Pagou cobrança atrasada mas ainda está inadimplente hoje "
        "(pagou só parte ou voltou a ter cobrança vencida)."
    )
    _tt_val = "Soma dos pagamentos de cobranças atrasadas no período."

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
        f'<div class="metric-sub" style="font-size:15px;margin-top:8px">{sub}</div>'
        f'</div>'
    )
    with c1:
        st.markdown(
            _card_fmt("Inadimplentes Atual", f"{inadimplentes_atual:,}",
                      "carteira hoje", "#ef4444", _tt_inad),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            _card_fmt("Pagamentos", f"{total_pgto:,}", sub_pag, "#e8eaf0", _tt_pag),
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            _card_fmt("Regularizações", f"{total_reg:,}",
                      f"{taxa_reg:.0f}% dos pagamentos", "#22c55e", _tt_reg),
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            _card_fmt("Parciais", f"{total_parc:,}",
                      "ainda devem algo", "#f59e0b", _tt_parc),
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
    df_ef = fetch_eficacia_por_especialista(dt_inicio.isoformat(), dt_fim.isoformat())
    if filtro_esp != "Todos" and not df_ef.empty:
        df_ef = df_ef[df_ef["atendente"] == filtro_esp]
    if not df_ef.empty:
        agg_esp = agg_esp.merge(
            df_ef[["atendente", "eficacia_real", "clientes_contactados"]],
            on="atendente", how="left",
        ).fillna({"eficacia_real": 0, "clientes_contactados": 0})
    else:
        agg_esp["eficacia_real"] = 0
        agg_esp["clientes_contactados"] = 0

    # ── Matriz de Desempenho (scatter Volume × Eficácia) ──────────────────
    # Cada atendente vira um ponto. Quadrante superior direito = star
    # (alto volume + alta eficácia). Inferior esquerdo = precisa apoio.
    st.markdown(
        '<div style="font-size:14px;font-weight:700;color:#8b94a5;'
        'text-transform:uppercase;letter-spacing:1.5px;'
        'margin-top:8px;margin-bottom:4px">Matriz de Desempenho</div>'
        '<div style="font-size:11px;color:#8b94a5;margin-bottom:12px">'
        'Volume × Eficácia por especialista. Quadrante superior direito = melhor performance (muitos pagamentos + alta conversão).'
        '</div>',
        unsafe_allow_html=True,
    )

    # Cap dos eixos: deixa margem visual nos extremos pra texto não sair
    _max_pag = max(agg_esp["pagamentos"].max() if not agg_esp.empty else 1, 1)
    _max_ef = max(agg_esp["eficacia_real"].max() if not agg_esp.empty else 1, 30)

    base_scatter = alt.Chart(agg_esp).encode(
        x=alt.X(
            "eficacia_real:Q",
            title="EFICÁCIA REAL (%)",
            scale=alt.Scale(domain=[0, max(_max_ef * 1.2, 100)]),
        ),
        y=alt.Y(
            "pagamentos:Q",
            title="VOLUME DE PAGAMENTOS",
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
            alt.Tooltip("pagamentos:Q", title="Pagamentos"),
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
    _avg_vol = float(agg_esp["pagamentos"].mean()) if not agg_esp.empty else 0
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
        f'volume {_avg_vol:.0f}). Superior direito = melhor desempenho.'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown(_DIVIDER, unsafe_allow_html=True)

    # ── Layout 2 colunas: Pagamentos por Dia | Distribuição da Carteira ──
    # Time series (esquerda, sem legenda) + Donut (direita, com legenda
    # única que serve de referência pros dois gráficos via cor compartilhada).
    g_esq, g_dir = st.columns(2)

    # ── Pagamentos por Dia ────────────────────────────────────────────────
    with g_esq:
        _tem_hoje_no_df = any(d == hoje for d in df_per["data_dt"].dt.date.unique())
        _sub_hoje = (
            '<div style="font-size:11px;color:#8b94a5;margin-bottom:12px">'
            'Hoje aparece com a opacidade reduzida — dia em andamento.'
            '</div>' if _tem_hoje_no_df else '<div style="height:12px"></div>'
        )
        st.markdown(
            '<div style="font-size:14px;font-weight:700;color:#8b94a5;'
            'text-transform:uppercase;letter-spacing:1.5px;'
            'margin-top:24px;margin-bottom:4px">Pagamentos por Dia</div>'
            f'{_sub_hoje}',
            unsafe_allow_html=True,
        )
        df_diario = (
            df_per.groupby([df_per["data_dt"].dt.date, "atendente"])
            .size()
            .reset_index(name="pagamentos")
            .rename(columns={"data_dt": "data"})
        )
        df_diario["eh_hoje"] = df_diario["data"].apply(lambda d: d == hoje)
        df_diario["data_str"] = df_diario["data"].apply(lambda d: d.strftime("%d/%m"))
        _datas_ordem = (
            df_diario[["data", "data_str"]]
            .drop_duplicates()
            .sort_values("data")["data_str"]
            .tolist()
        )
        chart_dia = (
            alt.Chart(df_diario)
            .mark_bar(cornerRadiusEnd=2)
            .encode(
                x=alt.X("data_str:O", title="DATA", sort=_datas_ordem, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("pagamentos:Q", title="PAGAMENTOS"),
                # Sem legenda — o donut à direita serve de referência única
                # pra cor → atendente em toda a tela.
                color=alt.Color(
                    "atendente:N",
                    scale=alt.Scale(range=_CHART_PALETTE),
                    legend=None,
                ),
                opacity=alt.condition(
                    alt.datum.eh_hoje,
                    alt.value(0.45),
                    alt.value(1.0),
                ),
                tooltip=[
                    alt.Tooltip("data_str:O", title="Dia"),
                    alt.Tooltip("atendente:N", title="Especialista"),
                    alt.Tooltip("pagamentos:Q", title="Pagamentos"),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(chart_dia, use_container_width=True)

    # ── Distribuição da Carteira (Donut) ──────────────────────────────────
    with g_dir:
        st.markdown(
            '<div style="font-size:14px;font-weight:700;color:#8b94a5;'
            'text-transform:uppercase;letter-spacing:1.5px;'
            'margin-top:24px;margin-bottom:12px">Distribuição da Carteira</div>',
            unsafe_allow_html=True,
        )
        # Filtra: exclui regularizados de hoje (real-time) + aplica filtros
        # de Especialista e Situação.
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
            chart_donut = (
                alt.Chart(carteira_agg)
                .mark_arc(innerRadius=60, outerRadius=110)
                .encode(
                    theta=alt.Theta("clientes:Q", title="Clientes"),
                    color=alt.Color(
                        "atendente:N",
                        scale=alt.Scale(range=_CHART_PALETTE),
                        title="Especialista",
                    ),
                    tooltip=[
                        alt.Tooltip("atendente:N", title="Especialista"),
                        alt.Tooltip("clientes:Q", title="Clientes"),
                        alt.Tooltip("valor:Q", title="R$ em aberto", format=",.2f"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(chart_donut, use_container_width=True)
        else:
            st.info("Sem carteira atual pra mostrar distribuição.")

    st.markdown(_DIVIDER, unsafe_allow_html=True)

    # ── Evolução Mensal de Pagamentos (últimos 6 meses) ───────────────────
    # Trend histórico — independente do filtro de período (sempre 6 meses).
    # Mostra se o time tá melhorando ou piorando ao longo do tempo.
    st.markdown(
        '<div style="font-size:14px;font-weight:700;color:#8b94a5;'
        'text-transform:uppercase;letter-spacing:1.5px;'
        'margin-bottom:4px">Evolução Mensal de Pagamentos</div>'
        '<div style="font-size:11px;color:#8b94a5;margin-bottom:12px">'
        'Últimos 6 meses — independente do filtro de período. Mostra '
        'tendência do time ao longo do tempo.'
        '</div>',
        unsafe_allow_html=True,
    )
    # Calcula primeiro dia há 6 meses (1º dia do mês há 5 meses pra trás)
    _hoje_trend = date.today()
    _ano = _hoje_trend.year
    _mes = _hoje_trend.month - 5
    while _mes <= 0:
        _mes += 12
        _ano -= 1
    _trend_inicio = date(_ano, _mes, 1)
    df_trend = fetch_pagamentos_creditados(_trend_inicio.isoformat(), _hoje_trend.isoformat())
    if not df_trend.empty:
        df_trend = df_trend.rename(columns={
            "id_sacado_sac": "id",
            "atendente_credito": "atendente",
        })
        df_trend["data_dt"] = pd.to_datetime(df_trend["dt_pagamento"], errors="coerce")
        df_trend = df_trend.dropna(subset=["data_dt"])
        # Aplica filtro de Situação no trend também (consistência com o resto)
        if ids_situacao_ok is not None:
            df_trend = df_trend[df_trend["id"].astype(str).isin(ids_situacao_ok)]
        df_trend["mes_dt"] = df_trend["data_dt"].dt.to_period("M").dt.to_timestamp()
        df_trend["mes_label"] = df_trend["mes_dt"].dt.strftime("%b/%y").str.capitalize()
        df_mensal = (
            df_trend.groupby(["mes_dt", "mes_label", "atendente"])
            .agg(pagamentos=("id", "nunique"))
            .reset_index()
        )
        # Filtra por especialista se selecionado (só na visualização — base
        # da média da equipe permanece todos os atendentes)
        df_mensal_show = df_mensal.copy()
        if filtro_esp != "Todos":
            df_mensal_show = df_mensal_show[df_mensal_show["atendente"] == filtro_esp]

        if not df_mensal_show.empty:
            _meses_ordem = (
                df_mensal[["mes_dt", "mes_label"]]
                .drop_duplicates()
                .sort_values("mes_dt")["mes_label"]
                .tolist()
            )
            base_trend = alt.Chart(df_mensal_show).encode(
                x=alt.X("mes_label:O", title="MÊS", sort=_meses_ordem, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("pagamentos:Q", title="PAGAMENTOS"),
                # Sem legenda — o donut "Distribuição da Carteira" acima é a
                # referência única pra mapeamento cor→especialista.
                color=alt.Color(
                    "atendente:N",
                    scale=alt.Scale(range=_CHART_PALETTE),
                    legend=None,
                ),
                tooltip=[
                    alt.Tooltip("mes_label:N", title="Mês"),
                    alt.Tooltip("atendente:N", title="Especialista"),
                    alt.Tooltip("pagamentos:Q", title="Pagamentos"),
                ],
            )
            linha_trend = base_trend.mark_line(strokeWidth=2.5, interpolate="monotone")
            pontos_trend = base_trend.mark_circle(size=90, stroke="#0f1117", strokeWidth=2)

            chart_trend = (linha_trend + pontos_trend).properties(height=280)
            st.altair_chart(chart_trend, use_container_width=True)
        else:
            st.info("Sem pagamentos do especialista selecionado nos últimos 6 meses.")
    else:
        st.info("Sem dados históricos de pagamentos.")

    st.markdown(_DIVIDER, unsafe_allow_html=True)

    # ── Tabela ranking detalhado ──────────────────────────────────────────
    st.markdown(
        '<div style="font-size:14px;font-weight:700;color:#8b94a5;'
        'text-transform:uppercase;letter-spacing:1.5px;'
        'margin-bottom:12px">Ranking Detalhado</div>',
        unsafe_allow_html=True,
    )
    # Agregado por especialista — pagamentos, regularizações, parciais, valor,
    # contagem via contato direto vs espontâneo, e eficácia do contato.
    df_per["reg_via_contato"] = (
        df_per["eh_regularizacao"].astype(bool)
        & (df_per["tipo_atribuicao"] == "via_contato")
    )
    rank_agg = (
        df_per.groupby("atendente")
        .agg(
            pagamentos=("id", "nunique"),
            regularizacoes=("eh_regularizacao", lambda s: int(s.sum())),
            parciais=("eh_parcial", lambda s: int(s.sum())),
            via_contato=("tipo_atribuicao", lambda s: int((s == "via_contato").sum())),
            reg_via_contato=("reg_via_contato", lambda s: int(s.sum())),
            valor=("valor", "sum"),
        )
        .reset_index()
    )
    rank_agg["espontaneos"] = rank_agg["pagamentos"] - rank_agg["via_contato"]
    rank_agg["pct_contato"] = (rank_agg["via_contato"] / rank_agg["pagamentos"] * 100).round(0).astype(int)
    # Eficácia REAL = dos clientes contactados no período, % regularizados hoje.
    # Usa fetch_eficacia_por_especialista (denominador correto, não só pagamentos).
    df_ef_real = fetch_eficacia_por_especialista(dt_inicio.isoformat(), dt_fim.isoformat())
    if df_ef_real.empty:
        rank_agg["eficacia"] = 0
    else:
        rank_agg = rank_agg.merge(
            df_ef_real[["atendente", "eficacia_real"]],
            on="atendente", how="left",
        )
        rank_agg["eficacia"] = rank_agg["eficacia_real"].fillna(0).astype(float)
        rank_agg = rank_agg.drop(columns=["eficacia_real"])
    # Junta com carteira atual
    carteira_count = (
        pd.DataFrame([{"atendente": _norm_atendente_raw(c.get("_grupo"))} for c in clientes])
        .groupby("atendente").size().reset_index(name="carteira_atual")
        if clientes else pd.DataFrame(columns=["atendente", "carteira_atual"])
    )
    ranking = rank_agg.merge(carteira_count, on="atendente", how="outer").fillna(0)
    # Força int em todas as colunas numéricas inteiras — evita exibir '16.0'
    # quando merges com floats convertem o tipo silenciosamente.
    # Eficácia mantém como float (duas casas decimais); demais são int.
    for col in ("pagamentos", "regularizacoes", "parciais", "via_contato",
                "espontaneos", "carteira_atual"):
        if col in ranking.columns:
            ranking[col] = ranking[col].astype(int)
    if "eficacia" in ranking.columns:
        ranking["eficacia"] = ranking["eficacia"].astype(float)
    ranking = ranking.sort_values("regularizacoes", ascending=False).reset_index(drop=True)
    ranking["rank"] = ranking.index + 1
    ranking["valor_fmt"] = ranking["valor"].apply(fmt_moeda_plain)

    # Headers — 9 colunas (Eficácia adicionada)
    # 9 colunas: Posição (mais larga pra header completo), Especialista (nome),
    # Pagamentos, Via Contato, Espontâneos, Regularizações, Eficácia, Valor
    # Recuperado, Carteira.
    _col_widths = [0.7, 2.0, 1.0, 1.0, 1.1, 1.2, 0.9, 1.4, 0.9]
    hdr_cols = st.columns(_col_widths)
    _hdr_labels = [
        ("Posição", ""),
        ("Especialista", ""),
        ("Pagamentos", "Pagamentos totais (clientes únicos)"),
        ("Via Contato", "Pagamentos com contato registrado antes (msg ou ligação)"),
        ("Espontâneos", "Pagamentos sem contato — atribuído por grupo"),
        ("Regularizações", "Clientes que NÃO estão mais inadimplentes hoje"),
        ("Eficácia", "Dos clientes contactados no período (msg/ligação), % que estão regularizados hoje. Reflete trabalho real — cobrança tem conversão típica de 10-20%."),
        ("Valor Recuperado", ""),
        ("Carteira", "Clientes inadimplentes hoje sob esse especialista"),
    ]
    for col, (h, tip) in zip(hdr_cols, _hdr_labels):
        title_attr = f' title="{tip}"' if tip else ""
        cursor = "help" if tip else "default"
        col.markdown(
            f'<div{title_attr} style="cursor:{cursor};padding:8px 0;font-size:11px;'
            f'text-transform:uppercase;letter-spacing:1px;color:#8b94a5;font-weight:700">{h}</div>',
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
        rcols[2].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#e8eaf0;font-weight:600">{row["pagamentos"]}</div>',
            unsafe_allow_html=True,
        )
        rcols[3].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#7cc243;font-weight:600">{row["via_contato"]}</div>',
            unsafe_allow_html=True,
        )
        rcols[4].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#9ca3af">{row["espontaneos"]}</div>',
            unsafe_allow_html=True,
        )
        rcols[5].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#22c55e;font-weight:600">{row["regularizacoes"]}</div>',
            unsafe_allow_html=True,
        )
        # Eficácia REAL — faixas ajustadas (cobrança é trabalho difícil,
        # taxa típica de conversão é 10-20% em operação saudável).
        _ef = row["eficacia"]
        _ef_cor = "#22c55e" if _ef >= 30 else ("#f59e0b" if _ef >= 15 else "#ef4444")
        rcols[6].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:{_ef_cor};font-weight:700">{_ef:.2f}%</div>',
            unsafe_allow_html=True,
        )
        rcols[7].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#5fa3ff;font-weight:600">{row["valor_fmt"]}</div>',
            unsafe_allow_html=True,
        )
        rcols[8].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#9ca3af">{row["carteira_atual"]}</div>',
            unsafe_allow_html=True,
        )
