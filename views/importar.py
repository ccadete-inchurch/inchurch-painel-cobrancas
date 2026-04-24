import streamlit as st

from auth import get_store
from data import processar_dados_bigquery
from views.header import render_header


def tela_importar():
    store = get_store()
    render_header()

    col_a, col_b, _ = st.columns([1, 1, 6])
    with col_a:
        if store["clientes"] and st.button("← Voltar"):
            st.session_state["tela"] = "principal"
            st.rerun()
    with col_b:
        if st.button("Sair"):
            for k in ["user_uid", "user_nome", "user_role", "tela"]:
                st.session_state.pop(k, None)
            st.rerun()

    st.markdown("### 📥 Importar Dados")
    st.markdown("#### 🔄 Carregar do BigQuery")
    st.markdown("*Os dados são atualizados diariamente pelos pipelines*")

    if st.button("📊 Carregar Dados do BigQuery", width="stretch", type="primary"):
        with st.spinner("Conectando ao BigQuery e carregando dados..."):
            clientes, n_reg = processar_dados_bigquery()
        if clientes:
            st.toast(f"✅ {len(clientes)} clientes carregados do BigQuery", icon="✅")
            if n_reg:
                st.toast(f"✅ {n_reg} clientes regularizados", icon="✅")
            st.session_state["tela"] = "principal"
            st.rerun()
        else:
            st.error("Erro ao carregar dados do BigQuery")
