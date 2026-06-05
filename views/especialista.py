from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from auth import current_role
from data import _EMAIL_GRUPO, fetch_pagamentos_creditados, fetch_eficacia_por_especialista
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

    # ── Gráfico 2: Eficácia REAL do contato por especialista ──────────────
    # Denominador correto: clientes únicos contactados no período (não só os
    # que viraram pagamento). Reflete o trabalho real — maioria dos contatos
    # não converte imediatamente.
    st.markdown(
        '<div style="font-size:18px;font-weight:700;color:#e8eaf0;'
        'margin-top:24px;margin-bottom:4px">Eficácia do contato por especialista</div>'
        '<div style="font-size:11px;color:#8b94a5;margin-bottom:12px">'
        'Dos clientes contactados no período, % que estão regularizados hoje.'
        '</div>',
        unsafe_allow_html=True,
    )
    df_ef = fetch_eficacia_por_especialista(dt_inicio.isoformat(), dt_fim.isoformat())
    if filtro_esp != "Todos" and not df_ef.empty:
        df_ef = df_ef[df_ef["atendente"] == filtro_esp]

    if df_ef.empty:
        st.info("Sem dados de contato no período pra calcular eficácia.")
    else:
        # Faixas de cor por valor (reais agora — bem mais baixos que parecia)
        chart_ef = (
            alt.Chart(df_ef.sort_values("eficacia_real", ascending=False))
            .mark_bar(cornerRadiusEnd=4)
            .encode(
                x=alt.X("eficacia_real:Q", title="Eficácia REAL (%)", scale=alt.Scale(domain=[0, 100])),
                y=alt.Y("atendente:N", title=None, sort="-x"),
                color=alt.Color(
                    "eficacia_real:Q",
                    scale=alt.Scale(
                        domain=[0, 15, 30, 100],
                        range=["#ef4444", "#f59e0b", "#22c55e", "#22c55e"],
                    ),
                    legend=None,
                ),
                tooltip=[
                    alt.Tooltip("atendente:N", title="Especialista"),
                    alt.Tooltip("eficacia_real:Q", title="Eficácia", format=".0f"),
                    alt.Tooltip("clientes_contactados:Q", title="Clientes contactados"),
                    alt.Tooltip("regularizaram:Q", title="Regularizaram"),
                    alt.Tooltip("ainda_inadimplentes:Q", title="Ainda inadimplentes"),
                ],
            )
            .properties(height=max(150, 40 * len(df_ef)))
        )
        st.altair_chart(chart_ef, use_container_width=True)

    # ── Gráfico 3: Total de pagamentos por dia (barras empilhadas) ───────
    # Barras empilhadas: altura = total diário, segmentos = atendentes.
    # Hoje aparece com opacidade reduzida + anotação ("em andamento") pra
    # não distorcer comparação com dias completos.
    st.markdown(
        '<div style="font-size:18px;font-weight:700;color:#e8eaf0;'
        'margin-top:24px;margin-bottom:4px">Pagamentos por dia</div>'
        '<div style="font-size:11px;color:#8b94a5;margin-bottom:12px">'
        'Hoje aparece com opacidade reduzida — dia ainda em andamento, não comparável aos completos.'
        '</div>',
        unsafe_allow_html=True,
    )
    df_diario = (
        df_per.groupby([df_per["data_dt"].dt.date, "atendente"])
        .size()
        .reset_index(name="pagamentos")
        .rename(columns={"data_dt": "data"})
    )
    df_diario["eh_hoje"] = df_diario["data"].apply(lambda d: d == hoje)
    # Converte pra string DD/MM pra exibir só dia/mês — sem horário.
    # Tipo ordinal (não temporal) preserva ordem mas elimina a quantização
    # de tempo do Altair (que tentava inferir 00:00, intervalos etc).
    df_diario["data_str"] = df_diario["data"].apply(lambda d: d.strftime("%d/%m"))
    # Lista ordenada pra Altair respeitar ordem cronológica no eixo X
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
            x=alt.X("data_str:O", title="Data", sort=_datas_ordem, axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("pagamentos:Q", title="Pagamentos (total empilhado)"),
            color=alt.Color(
                "atendente:N",
                scale=alt.Scale(range=_CHART_PALETTE),
                title="Especialista",
            ),
            opacity=alt.condition(
                alt.datum.eh_hoje,
                alt.value(0.45),  # hoje: esmaecido
                alt.value(1.0),   # outros dias: cheio
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
        rank_agg["eficacia"] = rank_agg["eficacia_real"].fillna(0).astype(int)
        rank_agg = rank_agg.drop(columns=["eficacia_real"])
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

    # Headers — 9 colunas (Eficácia adicionada)
    _col_widths = [0.35, 2.0, 0.8, 1.2, 1.1, 0.8, 0.9, 1.3, 1.0]
    hdr_cols = st.columns(_col_widths)
    _hdr_labels = [
        ("#", ""),
        ("Especialista", ""),
        ("Pag.", "Pagamentos totais (clientes únicos)"),
        ("Contato ●", "Pagamentos com contato registrado antes (msg ou ligação)"),
        ("Espontâneo ○", "Pagamentos sem contato — atribuído por grupo"),
        ("Reg.", "Clientes que NÃO estão mais inadimplentes hoje"),
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
            f'<div style="padding:10px 0;font-size:14px;color:{_ef_cor};font-weight:700">{_ef}%</div>',
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
