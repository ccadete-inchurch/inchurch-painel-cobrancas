from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from auth import current_role
from data import _EMAIL_GRUPO, fetch_pagamentos_creditados
from helpers import fmt_moeda_plain


# Paleta inChurch (verde + complementares acessíveis em fundo escuro)
_CHART_PALETTE = [
    "#7cc243",  # inChurch verde
    "#5fa3ff",  # azul
    "#f59e0b",  # âmbar
    "#a78bfa",  # roxo
    "#ef4444",  # vermelho
    "#22c55e",  # verde claro
    "#f97316",  # laranja
    "#ec4899",  # rosa
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
    if role not in ("admin", "gestor"):
        st.error("Acesso restrito — apenas Admin e Gestor.")
        return

    # ── Header ────────────────────────────────────────────────────────────
    st.markdown(
        '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:36px;'
        'font-weight:800;color:#e8eaf0;margin-top:24px;margin-bottom:24px;letter-spacing:-1px;line-height:1.1">'
        'Especialista</div>',
        unsafe_allow_html=True,
    )

    # ── Filtro de período (PRIMEIRO — define o range pro BQ) ──────────────
    fp1, fp2, _ = st.columns([2, 2, 4])
    with fp1:
        periodo = st.selectbox(
            "Período",
            ["Este mês", "Últimos 30 dias", "Últimos 90 dias", "Mês anterior", "Últimos 12 meses"],
            key="esp_periodo",
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

    with fp2:
        especialistas_disp = sorted(
            set(df_reg["atendente"].unique())
            | set(_EMAIL_GRUPO.values())
            | {"Sem contato registrado"}
        )
        filtro_esp = st.selectbox(
            "Especialista",
            ["Todos"] + especialistas_disp,
            key="esp_filtro",
        )

    # df_per_all: período inteiro (BQ já filtrou por data). Usado pra média
    # da equipe — não muda com filtro de especialista.
    df_per_all = df_reg
    # df_per: também filtrado por especialista (cards individuais)
    df_per = df_per_all.copy()
    if filtro_esp != "Todos":
        df_per = df_per[df_per["atendente"] == filtro_esp]

    # ── Cards agregados ───────────────────────────────────────────────────
    total_pgto = int(df_per["id"].astype(str).nunique()) if not df_per.empty else 0
    total_valor = float(df_per["valor"].sum()) if not df_per.empty else 0.0
    total_reg = int(df_per[df_per["eh_regularizacao"]]["id"].astype(str).nunique()) if not df_per.empty else 0
    total_parc = int(df_per[df_per["eh_parcial"]]["id"].astype(str).nunique()) if not df_per.empty else 0
    inadimplentes_atual = len(clientes)
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

    # 5 cards em uma linha
    c1, c2, c3, c4, c5 = st.columns(5)
    _card_fmt = lambda label, valor, sub, cor: (
        f'<div class="metric-card" style="min-height:140px;padding:18px 16px">'
        f'<div class="metric-label" style="font-size:11px">{label}</div>'
        f'<div class="metric-value" style="color:{cor};font-size:30px;margin-top:4px">{valor}</div>'
        f'<div class="metric-sub" style="font-size:12px;margin-top:6px">{sub}</div>'
        f'</div>'
    )
    with c1:
        st.markdown(
            _card_fmt("Inadimplentes Atual", f"{inadimplentes_atual:,}", "carteira hoje", "#ef4444"),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            _card_fmt("Pagamentos", f"{total_pgto:,}", sub_pag, "#e8eaf0"),
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            _card_fmt("Regularizações", f"{total_reg:,}",
                      f"{taxa_reg:.0f}% dos pagamentos", "#22c55e"),
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            _card_fmt("Parciais", f"{total_parc:,}",
                      "ainda devem algo", "#f59e0b"),
            unsafe_allow_html=True,
        )
    with c5:
        st.markdown(
            _card_fmt("Valor Recuperado", fmt_moeda_plain(total_valor), "no período", "#5fa3ff"),
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)

    if df_per.empty:
        st.info("Nenhum pagamento no período selecionado.")
        return

    # ── Agregado por especialista (base pros gráficos) ────────────────────
    agg_esp = (
        df_per.groupby("atendente")
        .agg(pagamentos=("id", "nunique"), valor=("valor", "sum"))
        .reset_index()
        .sort_values("pagamentos", ascending=False)
    )

    # ── Gráfico 1: Pagamentos por especialista (bar horizontal) ───────────
    st.markdown(
        '<div style="font-size:18px;font-weight:700;color:#e8eaf0;'
        'margin-top:8px;margin-bottom:12px">Pagamentos por especialista</div>',
        unsafe_allow_html=True,
    )
    chart_qtd = (
        alt.Chart(agg_esp)
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            x=alt.X("pagamentos:Q", title="Pagamentos (clientes únicos)"),
            y=alt.Y("atendente:N", title=None, sort="-x"),
            color=alt.Color(
                "atendente:N",
                scale=alt.Scale(range=_CHART_PALETTE),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("atendente:N", title="Especialista"),
                alt.Tooltip("pagamentos:Q", title="Pagamentos"),
                alt.Tooltip("valor:Q", title="Valor", format=",.2f"),
            ],
        )
        .properties(height=max(150, 40 * len(agg_esp)))
    )
    st.altair_chart(chart_qtd, use_container_width=True)

    # ── Gráfico 2: Valor recuperado por especialista ──────────────────────
    st.markdown(
        '<div style="font-size:18px;font-weight:700;color:#e8eaf0;'
        'margin-top:24px;margin-bottom:12px">Valor recuperado por especialista</div>',
        unsafe_allow_html=True,
    )
    chart_val = (
        alt.Chart(agg_esp.sort_values("valor", ascending=False))
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            x=alt.X("valor:Q", title="R$ recuperado"),
            y=alt.Y("atendente:N", title=None, sort="-x"),
            color=alt.Color(
                "atendente:N",
                scale=alt.Scale(range=_CHART_PALETTE),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("atendente:N", title="Especialista"),
                alt.Tooltip("valor:Q", title="Valor", format=",.2f"),
                alt.Tooltip("pagamentos:Q", title="Pagamentos"),
            ],
        )
        .properties(height=max(150, 40 * len(agg_esp)))
    )
    st.altair_chart(chart_val, use_container_width=True)

    # ── Gráfico 3: Total de pagamentos por dia (barras empilhadas) ───────
    # Barras empilhadas: altura = total diário, segmentos = atendentes.
    # Dá leitura dupla: volume diário + breakdown.
    st.markdown(
        '<div style="font-size:18px;font-weight:700;color:#e8eaf0;'
        'margin-top:24px;margin-bottom:12px">Pagamentos por dia</div>',
        unsafe_allow_html=True,
    )
    df_diario = (
        df_per.groupby([df_per["data_dt"].dt.date, "atendente"])
        .size()
        .reset_index(name="pagamentos")
        .rename(columns={"data_dt": "data"})
    )
    chart_dia = (
        alt.Chart(df_diario)
        .mark_bar(cornerRadiusEnd=2)
        .encode(
            x=alt.X("data:T", title="Data"),
            y=alt.Y("pagamentos:Q", title="Pagamentos (total empilhado)"),
            color=alt.Color(
                "atendente:N",
                scale=alt.Scale(range=_CHART_PALETTE),
                title="Especialista",
            ),
            tooltip=[
                alt.Tooltip("data:T", title="Dia"),
                alt.Tooltip("atendente:N", title="Especialista"),
                alt.Tooltip("pagamentos:Q", title="Pagamentos"),
            ],
        )
        .properties(height=320)
    )
    st.altair_chart(chart_dia, use_container_width=True)

    # ── Gráfico 4: Distribuição da carteira atual (donut) ─────────────────
    st.markdown(
        '<div style="font-size:18px;font-weight:700;color:#e8eaf0;'
        'margin-top:24px;margin-bottom:12px">Distribuição da carteira inadimplente (hoje)</div>',
        unsafe_allow_html=True,
    )
    carteira = pd.DataFrame([
        {"atendente": _norm_atendente_raw(c.get("_grupo")), "valor": float(c.get("valor") or 0)}
        for c in clientes
    ])
    if not carteira.empty:
        carteira_agg = (
            carteira.groupby("atendente")
            .agg(clientes=("valor", "count"), valor=("valor", "sum"))
            .reset_index()
        )
        chart_donut = (
            alt.Chart(carteira_agg)
            .mark_arc(innerRadius=70, outerRadius=130)
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

    # ── Tabela ranking detalhado ──────────────────────────────────────────
    st.markdown(
        '<div style="font-size:18px;font-weight:700;color:#e8eaf0;'
        'margin-top:32px;margin-bottom:12px">Ranking detalhado</div>',
        unsafe_allow_html=True,
    )
    # Agregado por especialista — pagamentos, regularizações, parciais, valor
    rank_agg = (
        df_per.groupby("atendente")
        .agg(
            pagamentos=("id", "nunique"),
            regularizacoes=("eh_regularizacao", lambda s: int(s.sum())),
            parciais=("eh_parcial", lambda s: int(s.sum())),
            valor=("valor", "sum"),
        )
        .reset_index()
    )
    # Junta com carteira atual
    carteira_count = (
        pd.DataFrame([{"atendente": _norm_atendente_raw(c.get("_grupo"))} for c in clientes])
        .groupby("atendente").size().reset_index(name="carteira_atual")
        if clientes else pd.DataFrame(columns=["atendente", "carteira_atual"])
    )
    ranking = rank_agg.merge(carteira_count, on="atendente", how="outer").fillna(0)
    for col in ("pagamentos", "regularizacoes", "parciais", "carteira_atual"):
        ranking[col] = ranking[col].astype(int)
    ranking = ranking.sort_values("regularizacoes", ascending=False).reset_index(drop=True)
    ranking["rank"] = ranking.index + 1
    ranking["valor_fmt"] = ranking["valor"].apply(fmt_moeda_plain)

    # Headers — 7 colunas
    _col_widths = [0.4, 2.5, 1.1, 1.3, 1.0, 1.6, 1.2]
    hdr_cols = st.columns(_col_widths)
    for col, h in zip(hdr_cols, ["#", "Especialista", "Pag.", "Reg.", "Parc.", "Valor Recuperado", "Carteira"]):
        col.markdown(
            f'<div style="padding:8px 0;font-size:11px;text-transform:uppercase;'
            f'letter-spacing:1px;color:#8b94a5;font-weight:700">{h}</div>',
            unsafe_allow_html=True,
        )

    for _, row in ranking.iterrows():
        rcols = st.columns(_col_widths)
        medalha = {1: "🥇", 2: "🥈", 3: "🥉"}.get(row["rank"], f"{row['rank']}")
        rcols[0].markdown(
            f'<div style="padding:10px 0;font-size:18px">{medalha}</div>',
            unsafe_allow_html=True,
        )
        rcols[1].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#e8eaf0;font-weight:600">{row["atendente"]}</div>',
            unsafe_allow_html=True,
        )
        rcols[2].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#e8eaf0">{row["pagamentos"]}</div>',
            unsafe_allow_html=True,
        )
        rcols[3].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#22c55e;font-weight:600">{row["regularizacoes"]}</div>',
            unsafe_allow_html=True,
        )
        rcols[4].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#f59e0b">{row["parciais"]}</div>',
            unsafe_allow_html=True,
        )
        rcols[5].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#5fa3ff;font-weight:600">{row["valor_fmt"]}</div>',
            unsafe_allow_html=True,
        )
        rcols[6].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#9ca3af">{row["carteira_atual"]}</div>',
            unsafe_allow_html=True,
        )
