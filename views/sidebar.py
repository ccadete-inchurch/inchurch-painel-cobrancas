import streamlit as st

from config import LOGO_SRC
from auth import is_logged, current_nome, current_role


def render_sidebar():
    if not is_logged():
        st.markdown("""
        <style>
        section[data-testid="stSidebar"]{display:none!important}
        </style>
        """, unsafe_allow_html=True)
        return

    page    = st.session_state.get("page", "dashboard")
    logo_sb = f'<img src="{LOGO_SRC}" style="height:30px;object-fit:contain">' if LOGO_SRC else '<span style="font-family:Syne,sans-serif;font-weight:800;font-size:18px;color:#7cc243">InChurch</span>'

    # CSS: fonte Syne + footer (nome/cargo + Sair) pinned no fim da sidebar
    # via position:fixed. Última .stButton da sidebar = Sair.
    st.sidebar.markdown("""
    <style>
    section[data-testid="stSidebar"] .stButton > button {
        font-family: 'Syne', sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: 1.2px !important;
        font-size: 12px !important;
    }
    /* Último botão da sidebar (= 'Sair da conta') fixo no fundo */
    section[data-testid="stSidebar"] [data-testid="stElementContainer"]:last-of-type {
        position: fixed !important;
        bottom: 12px !important;
        left: 0 !important;
        width: 250px !important;
        padding: 0 16px !important;
        z-index: 50 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.sidebar.markdown(f"""
    <div style="padding:24px 20px 18px;border-bottom:1px solid #1e2333;margin-bottom:8px">
        {logo_sb}
        <div style="font-size:13px;color:#8b94a5;margin-top:6px;text-transform:uppercase;letter-spacing:1.5px;font-weight:800">Painel de Cobrança</div>
    </div>
    <div style="padding:6px 20px 8px">
        <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:1.5px;font-weight:800">Navegação</div>
    </div>
    """, unsafe_allow_html=True)

    def nav_item(label, key_page):
        if page == key_page:
            st.sidebar.markdown(
                '<div style="height:1px;background:linear-gradient(90deg,#7cc243 60%,transparent);margin:4px 14px 0"></div>',
                unsafe_allow_html=True,
            )
        if st.sidebar.button(label, key=f"nav_{key_page}", width="stretch"):
            st.session_state["page"] = key_page
            st.rerun()

    nav_item("ATIVIDADES",          "atividades")
    nav_item("INADIMPLÊNCIA",      "dashboard")
    nav_item("PAGAMENTOS",         "historico")
    nav_item("PRÓXIMAS COBRANÇAS", "proximas")
    nav_item("CLIENTE",            "cliente")

    # Footer (nome + cargo) — position:fixed logo acima do botão Sair (que
    # também fica fixed por CSS no topo do arquivo). bottom:60px = altura do
    # botão Sair (~46px) + margem (~14px).
    st.sidebar.markdown(f"""
    <div style="position:fixed;bottom:60px;left:0;width:250px;padding:12px 20px 10px;
                border-top:1px solid #1e2333;background:#13161f;z-index:49">
        <div style="font-size:13px;color:#e8eaf0;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{current_nome()}</div>
        <div style="font-size:10px;color:#6b7280;margin-top:3px;text-transform:uppercase;letter-spacing:.8px;font-weight:600">{current_role()}</div>
    </div>
    """, unsafe_allow_html=True)

    # Padding bottom no conteúdo da sidebar pra não esconder último item de nav
    # atrás do footer fixed.
    st.sidebar.markdown('<div style="height:120px"></div>', unsafe_allow_html=True)

    if st.sidebar.button("Sair da conta", width="stretch"):
        # Limpa TODAS as chaves do session_state — garante que o login
        # subsequente faça fresh load do BQ + cache, sem heranças.
        for k in list(st.session_state.keys()):
            st.session_state.pop(k, None)
        st.rerun()
