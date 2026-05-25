import streamlit as st

from auth import current_nome, current_role
from data import get_store


def render_header():
    store    = get_store()
    upd      = store.get("ultima_atualizacao") or "—"
    is_admin = current_role() in ("admin", "gestor")
    role_tag  = '<span style="background:rgba(124,194,67,.2);color:#7cc243;font-size:11px;padding:3px 10px;border-radius:12px;font-weight:700;margin-left:8px">ADMIN</span>' if current_role() == "admin" else ""

    # CSS pro botão de refresh ficar discreto e parecido com o pill ao lado.
    # Aplicado via wrapper key='hdr-refresh-mini' (data-testid em Streamlit).
    st.markdown("""
    <style>
    div[data-testid="column"]:has(> div > div > div > button[kind="secondary"]#hdr-refresh-btn-anchor) button {
        background: #1e2333 !important;
        border: 1px solid #2a2f42 !important;
        color: #8b94a5 !important;
        border-radius: 50% !important;
        padding: 0 !important;
        width: 32px !important;
        height: 32px !important;
        min-height: 32px !important;
        font-size: 14px !important;
        line-height: 1 !important;
        margin: 0 !important;
    }
    div[data-testid="column"]:has(button[kind="secondary"]) button[key="hdr_refresh"]:hover {
        color: #e8eaf0 !important;
        background: #2a2f42 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Layout em colunas: spacer | atualizado pill + botão refresh | user pill
    sp, c_status, c_user = st.columns([6, 2.5, 1.8], vertical_alignment="center")

    with c_status:
        # Sub-colunas pra encaixar pill + botão de refresh juntos
        if is_admin:
            cs1, cs2 = st.columns([4, 1], vertical_alignment="center")
            with cs1:
                st.markdown(
                    f'<div style="text-align:right">'
                    f'<span style="font-size:13px;color:#8b94a5;background:#1e2333;padding:6px 14px;border-radius:20px;border:1px solid #2a2f42">Atualizado: {upd}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with cs2:
                if st.button("↻", key="hdr_refresh", help="Atualizar dados do BigQuery"):
                    # 1. Limpa gates de carga
                    for k in list(st.session_state.keys()):
                        if k.startswith(("_bq_loaded_", "_historico_loaded", "_mensagens_loaded",
                                         "_grupo_atendente", "_painel_", "_msg_", "_snapshot_")):
                            st.session_state.pop(k, None)
                    # 2. Limpa cache do overlay API
                    try:
                        from data import fetch_pagamentos_hoje_api
                        fetch_pagamentos_hoje_api.clear()
                    except Exception:
                        pass
                    # 3. Força processar (atualiza ultima_atualizacao)
                    try:
                        from data import processar_dados_bigquery
                        with st.spinner("Atualizando..."):
                            processar_dados_bigquery()
                        st.toast("Dados atualizados", icon="✅")
                    except Exception as e:
                        st.error(f"Erro: {e}")
                    st.rerun()
        else:
            st.markdown(
                f'<div style="text-align:right">'
                f'<span style="font-size:13px;color:#8b94a5;background:#1e2333;padding:6px 14px;border-radius:20px;border:1px solid #2a2f42">Atualizado: {upd}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    with c_user:
        st.markdown(
            f'<div style="text-align:right">'
            f'<span style="font-size:13px;background:#1e2333;border:1px solid #2a2f42;border-radius:20px;padding:6px 14px;display:inline-flex;align-items:center;gap:8px;font-weight:500">'
            f'<span style="width:8px;height:8px;background:#7cc243;border-radius:50%;display:inline-block"></span>{current_nome()}{role_tag}'
            f'</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Divisor inferior pra manter a sensação de barra do header
    st.markdown(
        '<div style="border-bottom:1px solid #2a2f42;margin:8px 0 24px"></div>',
        unsafe_allow_html=True,
    )
