from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from auth import current_role
from data import _EMAIL_GRUPO
from helpers import fmt_moeda_plain, get_effective_atendente


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


def _resolve_atendente(row) -> str:
    """Resolve o especialista efetivo de um pagamento.

    Pagamentos do BQ histórico vêm marcados 'Sistema (BigQuery)' — não
    rastreamos qual atendente causou aquela regularização específica.
    Pra dar atribuição útil, busca o especialista atual do cliente via
    get_effective_atendente (que usa splgc-grupo ou painel_tarefas).

    Trade-off: se cliente trocou de especialista entre o pagamento e
    agora (raro), atribuição reflete o atual, não o histórico.
    """
    at = str(row.get("atendente") or "").strip()
    if at and "BigQuery" not in at and at not in ("—", "nan", "NaN"):
        return at
    effective = get_effective_atendente(str(row.get("id") or "")) or ""
    return _norm_atendente_raw(effective)


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

    # ── Prepara dados ─────────────────────────────────────────────────────
    reg_list = store.get("regularizados") or []
    df_reg = pd.DataFrame(reg_list)
    if df_reg.empty:
        st.info("Sem dados de pagamentos pra analisar.")
        return

    # Resolve atendente efetivo — pagamentos do BQ histórico não têm o nome
    # do especialista; busca via get_effective_atendente (grupo splgc atual).
    df_reg["atendente"] = df_reg.apply(_resolve_atendente, axis=1)
    df_reg["valor"] = pd.to_numeric(df_reg["valor"], errors="coerce").fillna(0.0)
    df_reg["data_dt"] = pd.to_datetime(df_reg["data"], format="%d/%m/%Y", errors="coerce")
    df_reg = df_reg.dropna(subset=["data_dt"])

    # ── Filtro de período ─────────────────────────────────────────────────
    fp1, fp2, _ = st.columns([2, 2, 4])
    with fp1:
        periodo = st.selectbox(
            "Período",
            ["Este mês", "Últimos 30 dias", "Últimos 90 dias", "Mês anterior", "Todo o histórico"],
            key="esp_periodo",
        )
    with fp2:
        # Lista todos especialistas + os do _EMAIL_GRUPO mesmo sem pagamento ainda
        especialistas_disp = sorted(set(df_reg["atendente"].unique()) | set(_EMAIL_GRUPO.values()))
        filtro_esp = st.selectbox(
            "Especialista",
            ["Todos"] + especialistas_disp,
            key="esp_filtro",
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
    else:  # Todo o histórico
        dt_inicio = df_reg["data_dt"].min().date()
        dt_fim = hoje

    # df_per_all: filtrado SÓ por período (usado pra média da equipe — não
    # muda quando user filtra por especialista específico)
    df_per_all = df_reg[
        (df_reg["data_dt"].dt.date >= dt_inicio)
        & (df_reg["data_dt"].dt.date <= dt_fim)
    ]
    # df_per: filtrado também por especialista (usado nos cards de total)
    df_per = df_per_all.copy()
    if filtro_esp != "Todos":
        df_per = df_per[df_per["atendente"] == filtro_esp]

    # ── Cards agregados ───────────────────────────────────────────────────
    total_reg = int(df_per["id"].astype(str).nunique()) if not df_per.empty else 0
    total_valor = float(df_per["valor"].sum()) if not df_per.empty else 0.0

    # Média da EQUIPE (sempre baseada em df_per_all — independente do filtro
    # de especialista). Quando user filtra por 1 atendente, pode comparar o
    # total dele com a média da equipe.
    team_especialistas = int(df_per_all["atendente"].nunique()) if not df_per_all.empty else 0
    team_total_reg = int(df_per_all["id"].astype(str).nunique()) if not df_per_all.empty else 0
    team_total_valor = float(df_per_all["valor"].sum()) if not df_per_all.empty else 0.0
    media_por_esp = (team_total_reg / team_especialistas) if team_especialistas else 0
    media_valor = (team_total_valor / team_especialistas) if team_especialistas else 0

    # Sub-texto contextual no 'Pagamentos' — se filtrando por 1 especialista,
    # mostra comparativo com a média da equipe.
    if filtro_esp != "Todos" and team_especialistas:
        diff_pct = ((total_reg - media_por_esp) / media_por_esp * 100) if media_por_esp else 0
        sinal = "+" if diff_pct >= 0 else ""
        cor_diff = "#22c55e" if diff_pct >= 0 else "#ef4444"
        sub_pag = (
            f'<span style="color:{cor_diff};font-weight:600">{sinal}{diff_pct:.0f}%</span> '
            f'<span style="color:#8b94a5">vs média</span>'
        )
    else:
        sub_pag = "no período"

    c1, c2, c3, c4 = st.columns(4)
    _card_fmt = lambda label, valor, sub, cor: (
        f'<div class="metric-card" style="min-height:140px;padding:18px 16px">'
        f'<div class="metric-label" style="font-size:11px">{label}</div>'
        f'<div class="metric-value" style="color:{cor};font-size:34px;margin-top:4px">{valor}</div>'
        f'<div class="metric-sub" style="font-size:12px;margin-top:6px">{sub}</div>'
        f'</div>'
    )
    with c1:
        st.markdown(
            _card_fmt("Pagamentos", f"{total_reg:,}", sub_pag, "#e8eaf0"),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            _card_fmt("Valor Recuperado", fmt_moeda_plain(total_valor), "no período", "#22c55e"),
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            _card_fmt("Especialistas Ativos", str(team_especialistas),
                      f"de {len(_EMAIL_GRUPO)} no time", "#5fa3ff"),
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            _card_fmt("Média da Equipe", f"{media_por_esp:.1f}",
                      f"≈ {fmt_moeda_plain(media_valor)} por especialista", "#a78bfa"),
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

    # ── Gráfico 3: Evolução diária (linha) ────────────────────────────────
    st.markdown(
        '<div style="font-size:18px;font-weight:700;color:#e8eaf0;'
        'margin-top:24px;margin-bottom:12px">Evolução diária — pagamentos</div>',
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
        .mark_line(point=True, strokeWidth=2.5)
        .encode(
            x=alt.X("data:T", title="Data"),
            y=alt.Y("pagamentos:Q", title="Pagamentos"),
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
    # Junta pagamentos do período com carteira atual
    carteira_count = (
        pd.DataFrame([{"atendente": _norm_atendente_raw(c.get("_grupo"))} for c in clientes])
        .groupby("atendente").size().reset_index(name="carteira_atual")
        if clientes else pd.DataFrame(columns=["atendente", "carteira_atual"])
    )
    ranking = agg_esp.merge(carteira_count, on="atendente", how="outer").fillna(0)
    ranking["pagamentos"] = ranking["pagamentos"].astype(int)
    ranking["carteira_atual"] = ranking["carteira_atual"].astype(int)
    ranking = ranking.sort_values("pagamentos", ascending=False).reset_index(drop=True)
    ranking["rank"] = ranking.index + 1
    ranking["valor_fmt"] = ranking["valor"].apply(fmt_moeda_plain)

    # Headers
    hdr_cols = st.columns([0.5, 3, 1.5, 2, 1.5])
    for col, h in zip(hdr_cols, ["#", "Especialista", "Pagamentos", "Valor Recuperado", "Carteira Atual"]):
        col.markdown(
            f'<div style="padding:8px 0;font-size:11px;text-transform:uppercase;'
            f'letter-spacing:1px;color:#8b94a5;font-weight:700">{h}</div>',
            unsafe_allow_html=True,
        )

    for _, row in ranking.iterrows():
        rcols = st.columns([0.5, 3, 1.5, 2, 1.5])
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
            f'<div style="padding:10px 0;font-size:14px;color:#22c55e;font-weight:600">{row["valor_fmt"]}</div>',
            unsafe_allow_html=True,
        )
        rcols[4].markdown(
            f'<div style="padding:10px 0;font-size:14px;color:#9ca3af">{row["carteira_atual"]}</div>',
            unsafe_allow_html=True,
        )
