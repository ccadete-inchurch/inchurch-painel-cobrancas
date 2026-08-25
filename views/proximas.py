from datetime import date, timedelta

import pandas as pd
import streamlit as st

from data import fetch_proximas_cobracas
from helpers import carimbo_dia_cache
from helpers import fmt_moeda, fmt_moeda_plain


# Janela maxima de fetch — cobre range default (hoje → hoje+30d) com folga.
# Se user escolher range maior via date picker, refetcha com days ajustado.
_FETCH_DAYS_DEFAULT = 60


def _render_proximas(_store, _clientes):
    st.markdown(
        '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:36px;'
        'font-weight:800;color:#e8eaf0;margin-top:24px;margin-bottom:24px;letter-spacing:-1px;line-height:1.1">'
        'Próximas Cobranças</div>',
        unsafe_allow_html=True,
    )

    hoje = date.today()
    _ini_default = hoje
    _fim_default = hoje + timedelta(days=30)

    # Filtros no mesmo padrao da tela Pagamentos: busca + date range + situacao + grupo.
    # Grupo e' populado apos o fetch (precisa saber quais grupos existem nos dados).
    fb, fp, fs, fa = st.columns([2.4, 2.2, 1.3, 1.5])
    with fb:
        busca = st.text_input("Buscar", placeholder="Nome, CNPJ ou ID sacado...", key="proximas_busca")
    with fp:
        intervalo_selecionado = st.date_input(
            "Período (de → até)",
            value=(_ini_default, _fim_default),
            key="proximas_periodo_range",
            format="DD/MM/YYYY",
        )
    with fs:
        filtro_situacao = st.selectbox(
            "Situação",
            ["Todos", "Apenas ativos", "Apenas inativos"],
            key="proximas_situacao",
        )

    # Parse do date range picker — retorna tupla quando ambas escolhidas,
    # ou tupla de 1 item durante a selecao. Fallback seguro pro default.
    dt_ini, dt_fim = _ini_default, _fim_default
    if isinstance(intervalo_selecionado, tuple):
        if len(intervalo_selecionado) == 2:
            dt_ini, dt_fim = intervalo_selecionado
        elif len(intervalo_selecionado) == 1:
            dt_ini = dt_fim = intervalo_selecionado[0]
    elif intervalo_selecionado:
        dt_ini = dt_fim = intervalo_selecionado

    # Ajusta days do fetch pra cobrir o range escolhido (com margem).
    # fetch_proximas_cobracas puxa cobrancas com vencimento em [hoje, hoje+days].
    # Se user escolheu dt_fim mais longe, precisa aumentar days.
    days = max(_FETCH_DAYS_DEFAULT, (dt_fim - hoje).days + 5)

    with st.spinner("Carregando cobranças futuras..."):
        df_raw = fetch_proximas_cobracas(days, _dia=carimbo_dia_cache())

    if df_raw.empty:
        st.info(f"Nenhuma cobrança no período selecionado.")
        return

    rows = []
    for _, row in df_raw.iterrows():
        try:
            venc      = pd.to_datetime(row["vencimento"])
            venc_date = venc.date()
            venc_str  = venc.strftime("%d/%m/%Y")
            dias_rest = (venc_date - hoje).days
        except Exception:
            venc_date = None
            venc_str  = str(row.get("vencimento", ""))
            dias_rest = 0

        rows.append({
            "id":             str(row.get("codigo",    "") or ""),  # id_sacado_sac
            "nome":           str(row.get("nome",      "") or ""),
            "cnpj":           str(row.get("cnpj",      "") or ""),
            "telefone":       str(row.get("telefone",  "") or "—"),
            "valor":          float(row.get("valor", 0) or 0),
            "vencimento":     venc_str,
            "_venc_date":     venc_date,
            "dias_restantes": dias_rest,
            "grupo":          str(row.get("grupo",     "") or "—"),
            "inativo":        bool(row.get("inativo",  False)),
        })

    # Filtro de grupo — opções vêm dos dados carregados.
    # 'Sem especialista' = grupo vazio/'—' (mesmo padrão das outras telas).
    grupos_disp = sorted({
        r["grupo"] for r in rows
        if r["grupo"] and r["grupo"] not in ("—", "", "nan", "NaN")
    })
    _tem_sem_grupo = any(
        not r["grupo"] or r["grupo"] in ("—", "", "nan", "NaN")
        for r in rows
    )
    with fa:
        filtro_grupo = st.selectbox(
            "Grupo",
            ["Todos"] + grupos_disp + (["Sem especialista"] if _tem_sem_grupo else []),
            key="proximas_grupo",
        )

    # Aplica filtros
    if busca:
        b = busca.lower()
        rows = [
            r for r in rows
            if b in str(r.get("nome", "")).lower()
            or b in str(r.get("cnpj", "")).lower()
            or b in str(r.get("id", "")).lower()
        ]
    if filtro_situacao == "Apenas ativos":
        rows = [r for r in rows if not r.get("inativo")]
    elif filtro_situacao == "Apenas inativos":
        rows = [r for r in rows if r.get("inativo")]
    if filtro_grupo == "Sem especialista":
        rows = [r for r in rows if not r["grupo"] or r["grupo"] in ("—", "", "nan", "NaN")]
    elif filtro_grupo != "Todos":
        rows = [r for r in rows if r["grupo"] == filtro_grupo]

    # Filtro temporal via date range picker — orquestra cards + tabela.
    if dt_ini and dt_fim:
        rows = [
            r for r in rows
            if r.get("_venc_date") is not None
            and dt_ini <= r["_venc_date"] <= dt_fim
        ]

    # Label do período pra exibir nos cards (subtitulo)
    if dt_ini and dt_fim:
        if dt_ini == dt_fim:
            periodo_lbl = dt_ini.strftime("%d/%m/%Y")
        else:
            periodo_lbl = f"{dt_ini.strftime('%d/%m/%Y')} → {dt_fim.strftime('%d/%m/%Y')}"
    else:
        periodo_lbl = "período"

    # ── Métricas ──────────────────────────────────────────────────────────────
    total_valor = sum(r["valor"] for r in rows)
    n_clientes  = len({r["cnpj"] for r in rows})
    # Ticket médio: valor por cobrança. Indica se o pipeline é de cobranças
    # pequenas (volume) ou grandes (concentração).
    ticket_medio = (total_valor / len(rows)) if rows else 0.0

    m1, m2, m3, m4 = st.columns(4)
    # Mesmo padrão visual da tela Pagamentos: padding, font-sizes, peso.
    for col, label, val, sub, cor in [
        (m1, "Total a Receber", fmt_moeda_plain(total_valor), periodo_lbl, "#2dd36f"),
        (m2, "Cobranças",       str(len(rows)),               "faturas futuras",       "#e8eaf0"),
        (m3, "Clientes",        str(n_clientes),              "com vencimentos",       "#e8eaf0"),
        (m4, "Ticket Médio",    fmt_moeda_plain(ticket_medio),"valor por cobrança",    "#5fa3ff"),
    ]:
        with col:
            st.markdown(
                f'<div class="metric-card" style="padding:18px 20px">'
                f'<div class="metric-label" style="font-size:14px;letter-spacing:1.3px">{label}</div>'
                f'<div style="font-size:30px;font-weight:800;color:{cor};margin-top:6px;'
                f'line-height:1.1;font-variant-numeric:tabular-nums">{val}</div>'
                f'<div class="metric-sub" style="font-size:14px;margin-top:8px">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ── Paginação ─────────────────────────────────────────────────────────────
    PAGE_SIZE  = 100
    total_f    = len(rows)
    total_pg   = max(1, -(-total_f // PAGE_SIZE))
    page       = max(1, min(st.session_state.get("proximas_page", 1), total_pg))
    rows_page  = rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    # ── Tabela ────────────────────────────────────────────────────────────────
    col_w = [3, 1.5, 1.5, 1.2, 1.5]
    hdrs  = ["Cliente", "Valor", "Vencimento", "Dias p/ vencer", "Grupo"]

    hdr_cells = "".join(
        f'<div style="flex:{w};padding:14px 14px;font-size:12px;text-transform:uppercase;'
        f'letter-spacing:1.2px;color:#8b94a5;font-weight:700;white-space:nowrap;min-width:0">{h}</div>'
        for w, h in zip(col_w, hdrs)
    )
    st.markdown(
        f'<div style="display:flex;gap:1rem;background:#1e2333;border:1px solid #2a2f42;'
        f'border-radius:12px 12px 0 0;overflow:hidden">{hdr_cells}</div>',
        unsafe_allow_html=True,
    )

    if not rows:
        st.markdown(
            '<div style="background:#181c26;border:1px solid #2a2f42;border-top:none;'
            'border-radius:0 0 12px 12px;padding:60px;text-align:center;color:#6b7280;font-size:14px">'
            'Nenhum resultado — ajuste os filtros</div>',
            unsafe_allow_html=True,
        )
        return

    n = len(rows_page)
    for i, row in enumerate(rows_page):
        d = row["dias_restantes"]
        cor_d = "#ef4444" if d <= 7 else ("#f59e0b" if d <= 15 else "#2dd36f")

        rcols = st.columns(col_w)
        with rcols[0]:
            inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:4px">INATIVO</span>' if row.get("inativo") else ""
            st.markdown(
                f'<div style="padding:12px 14px">'
                f'<div style="margin-bottom:2px">{inativo_badge}</div>'
                f'<div style="font-weight:600;font-size:16px;color:#e8eaf0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{row["nome"]}</div>'
                f'<div style="font-size:13px;color:#6b7280;margin-top:2px">{row["cnpj"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with rcols[1]:
            st.markdown(f'<div style="padding:12px 14px;font-size:15px;font-weight:600">{fmt_moeda(row["valor"])}</div>', unsafe_allow_html=True)
        with rcols[2]:
            st.markdown(f'<div style="padding:12px 14px;font-size:15px;color:#8b94a5">{row["vencimento"]}</div>', unsafe_allow_html=True)
        with rcols[3]:
            st.markdown(
                f'<div style="padding:12px 14px">'
                f'<span style="border:1px solid {cor_d};color:{cor_d};'
                f'padding:3px 9px;border-radius:6px;font-size:12px;font-weight:700">{d}d</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with rcols[4]:
            st.markdown(f'<div style="padding:12px 14px;font-size:14px;color:#8b94a5">{row["grupo"]}</div>', unsafe_allow_html=True)

        if i < n - 1:
            st.markdown('<div style="height:0.5px;background:#2a2f42;margin:0"></div>', unsafe_allow_html=True)

    st.markdown(
        f'<div style="background:#1e2333;border:1px solid #2a2f42;border-top:none;'
        f'border-radius:0 0 12px 12px;padding:10px 16px;display:flex;justify-content:space-between;font-size:12px;color:#6b7280">'
        f'<span>Mostrando {(page-1)*PAGE_SIZE+1}–{min(page*PAGE_SIZE, total_f)} de {total_f} cobranças</span>'
        f'<span>Página {page} de {total_pg}</span></div>',
        unsafe_allow_html=True,
    )

    if total_pg > 1:
        st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)
        pc1, pc2, pc3 = st.columns([1, 2, 1])
        with pc1:
            if st.button("← Anterior", key="prox_prev", disabled=(page <= 1), width="stretch"):
                st.session_state["proximas_page"] = page - 1
                st.rerun()
        with pc2:
            st.markdown(f'<div style="text-align:center;color:#6b7280;font-size:12px;padding-top:6px">Página {page} de {total_pg}</div>', unsafe_allow_html=True)
        with pc3:
            if st.button("Próxima →", key="prox_next", disabled=(page >= total_pg), width="stretch"):
                st.session_state["proximas_page"] = page + 1
                st.rerun()
