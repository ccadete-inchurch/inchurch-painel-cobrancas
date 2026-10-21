import streamlit as st

from data import processar_dados_bigquery
from views.header import render_header


def tela_importar():
    """Tela de estado vazio: o app cai aqui quando o BigQuery nao devolveu
    cliente nenhum. Oferece recarregar na mao em vez de deixar o painel em
    branco sem explicacao.

    Nao ha mais botao "Voltar": ele existia guardado por
    `if store["clientes"] and ...`, e so se chega nesta tela quando a lista
    esta VAZIA — a condicao nunca podia ser verdadeira.
    """
    render_header()

    _, col_b, _ = st.columns([1, 1, 6])
    with col_b:
        if st.button("Sair"):
            for k in ["user_uid", "user_nome", "user_role", "tela"]:
                st.session_state.pop(k, None)
            # st.logout() invalida o cookie do OAuth (st.user) — sem isso
            # o usuario continua autenticado no Google e volta a logar no
            # proximo rerun.
            st.logout()

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
