import pandas as pd
import streamlit as st

from helpers import fmt_moeda_plain, fmt_moeda


def _render_historico(store):
    st.markdown(
        '<div style="font-family:Syne,sans-serif;font-size:20px;font-weight:700;margin-bottom:20px">Regularizados</div>',
        unsafe_allow_html=True,
    )

    reg = store["regularizados"]
    if not reg:
        st.info("Nenhum cliente regularizado ainda.")
        return

    df = pd.DataFrame(reg)

    # ── Filtros ───────────────────────────────────────────────────────────────
    fb, fs, _ = st.columns([3, 2, 3])
    with fb:
        busca = st.text_input("Buscar", placeholder="Nome ou CNPJ...", key="reg_busca")
    with fs:
        filtro_sit = st.selectbox("Situação", ["Todos", "Apenas ativos", "Apenas inativos"], key="reg_sit")

    if busca:
        b = busca.lower()
        df = df[df.apply(lambda r: b in str(r.get("nome","")).lower() or b in str(r.get("cnpj","")).lower(), axis=1)]
    if filtro_sit == "Apenas ativos" and "inativo" in df.columns:
        df = df[~df["inativo"].fillna(False).astype(bool)]
    elif filtro_sit == "Apenas inativos" and "inativo" in df.columns:
        df = df[df["inativo"].fillna(False).astype(bool)]

    # ── Métricas ──────────────────────────────────────────────────────────────
    total_valor = df["valor"].sum() if not df.empty else 0
    m1, m2, _ , _ = st.columns(4)
    for col, label, val, sub in [
        (m1, "Total Regularizado", fmt_moeda_plain(total_valor), "soma dos pagamentos"),
        (m2, "Pagamentos",         str(len(df)),                 "faturas liquidadas"),
    ]:
        with col:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="metric-label">{label}</div>'
                f'<div style="font-size:15px;font-weight:600;color:#2dd36f;margin-top:4px">{val}</div>'
                f'<div class="metric-sub">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ── Tabela ────────────────────────────────────────────────────────────────
    col_w = [1.2, 3, 1.8, 1.5]
    hdrs  = ["Data", "Cliente", "CNPJ", "Valor"]

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
    for i, row in enumerate(rows):
        inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:4px">INATIVO</span>' if row.get("inativo") else ""
        rcols = st.columns(col_w)
        with rcols[0]:
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;color:#8b94a5">{row.get("data","—")}</div>', unsafe_allow_html=True)
        with rcols[1]:
            st.markdown(
                f'<div style="padding:12px 14px">'
                f'<div style="margin-bottom:2px">{inativo_badge}</div>'
                f'<div style="font-size:14px;font-weight:600;color:#e8eaf0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{row.get("nome","—")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with rcols[2]:
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;color:#8b94a5">{row.get("cnpj","—")}</div>', unsafe_allow_html=True)
        with rcols[3]:
            st.markdown(f'<div style="padding:12px 14px;font-size:14px;font-weight:600;color:#2dd36f">{fmt_moeda(row.get("valor",0))}</div>', unsafe_allow_html=True)

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
