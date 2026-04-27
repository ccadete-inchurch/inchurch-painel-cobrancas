from datetime import date

import pandas as pd
import streamlit as st

from data import fetch_proximas_cobracas
from helpers import fmt_moeda, fmt_moeda_plain


_PERIODO_DAYS = {
    "Próximos 7 dias":  7,
    "Próximos 15 dias": 15,
    "Próximos 30 dias": 30,
    "Próximos 60 dias": 60,
}


def _render_proximas(_store, _clientes):
    st.markdown(
        '<div style="font-family:Syne,sans-serif;font-size:20px;font-weight:700;margin-bottom:20px">Próximas Cobranças</div>',
        unsafe_allow_html=True,
    )

    fp1, fp2, fp3, _ = st.columns([2, 2, 2, 2])
    with fp1:
        periodo = st.selectbox(
            "Período",
            list(_PERIODO_DAYS.keys()),
            index=2,
            label_visibility="collapsed",
            key="proximas_periodo",
        )
    with fp2:
        busca = st.text_input(
            "Buscar",
            placeholder="Nome ou CNPJ...",
            label_visibility="collapsed",
            key="proximas_busca",
        )
    with fp3:
        filtro_situacao = st.selectbox(
            "Situação",
            ["Todos", "Apenas ativos", "Apenas inativos"],
            label_visibility="collapsed",
            key="proximas_situacao",
        )

    days = _PERIODO_DAYS[periodo]

    with st.spinner("Carregando cobranças futuras..."):
        df_raw = fetch_proximas_cobracas(days)

    if df_raw.empty:
        st.info(f"Nenhuma cobrança nos próximos {days} dias.")
        return

    hoje = date.today()
    rows = []
    for _, row in df_raw.iterrows():
        try:
            venc      = pd.to_datetime(row["vencimento"])
            venc_str  = venc.strftime("%d/%m/%Y")
            dias_rest = (venc.date() - hoje).days
        except Exception:
            venc_str  = str(row.get("vencimento", ""))
            dias_rest = 0

        rows.append({
            "nome":           str(row.get("nome",      "") or ""),
            "cnpj":           str(row.get("cnpj",      "") or ""),
            "telefone":       str(row.get("telefone",  "") or "—"),
            "valor":          float(row.get("valor", 0) or 0),
            "vencimento":     venc_str,
            "dias_restantes": dias_rest,
            "grupo":          str(row.get("grupo",     "") or "—"),
            "inativo":        bool(row.get("inativo",  False)),
        })

    if busca:
        b = busca.lower()
        rows = [r for r in rows if b in r["nome"].lower() or b in r["cnpj"].lower()]
    if filtro_situacao == "Apenas ativos":
        rows = [r for r in rows if not r.get("inativo")]
    elif filtro_situacao == "Apenas inativos":
        rows = [r for r in rows if r.get("inativo")]

    # ── Métricas ──────────────────────────────────────────────────────────────
    total_valor = sum(r["valor"] for r in rows)
    n_clientes  = len({r["cnpj"] for r in rows})

    m1, m2, m3, _ = st.columns(4)
    for col, label, val, sub in [
        (m1, "Total a Receber", fmt_moeda_plain(total_valor), f"próximos {days} dias"),
        (m2, "Cobranças",       str(len(rows)),               "faturas futuras"),
        (m3, "Clientes",        str(n_clientes),              "com vencimentos"),
    ]:
        with col:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="metric-label">{label}</div>'
                f'<div style="font-size:15px;font-weight:600;color:#e8eaf0;margin-top:4px">{val}</div>'
                f'<div class="metric-sub">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ── Tabela ────────────────────────────────────────────────────────────────
    col_w = [3, 1.5, 1.5, 1.2, 1.5]
    hdrs  = ["Cliente", "Valor", "Vencimento", "Dias p/ vencer", "Grupo"]

    hdr_cells = "".join(
        f'<div style="flex:{w};padding:14px 14px;font-size:11px;text-transform:uppercase;'
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

    n = len(rows)
    for i, row in enumerate(rows):
        d = row["dias_restantes"]
        cor_d = "#ef4444" if d <= 7 else ("#f59e0b" if d <= 15 else "#2dd36f")

        rcols = st.columns(col_w)
        with rcols[0]:
            inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:4px">INATIVO</span>' if row.get("inativo") else ""
            st.markdown(
                f'<div style="padding:12px 14px">'
                f'<div style="margin-bottom:2px">{inativo_badge}</div>'
                f'<div style="font-weight:600;font-size:13px;color:#e8eaf0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{row["nome"]}</div>'
                f'<div style="font-size:11px;color:#6b7280;margin-top:2px">{row["cnpj"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with rcols[1]:
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;font-weight:600">{fmt_moeda(row["valor"])}</div>', unsafe_allow_html=True)
        with rcols[2]:
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;color:#8b94a5">{row["vencimento"]}</div>', unsafe_allow_html=True)
        with rcols[3]:
            st.markdown(
                f'<div style="padding:12px 14px">'
                f'<span style="border:1px solid {cor_d};color:{cor_d};'
                f'padding:3px 9px;border-radius:6px;font-size:12px;font-weight:700">{d}d</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with rcols[4]:
            st.markdown(f'<div style="padding:12px 14px;font-size:12px;color:#8b94a5">{row["grupo"]}</div>', unsafe_allow_html=True)

        if i < n - 1:
            st.markdown('<div style="height:0.5px;background:#2a2f42;margin:0"></div>', unsafe_allow_html=True)

    st.markdown(
        f'<div style="background:#1e2333;border:1px solid #2a2f42;border-top:none;'
        f'border-radius:0 0 12px 12px;padding:10px 16px;font-size:12px;color:#6b7280">'
        f'{n} cobranças</div>',
        unsafe_allow_html=True,
    )
