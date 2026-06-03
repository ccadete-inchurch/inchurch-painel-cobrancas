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

    # CSS: fonte Syne nos botões de nav + spacer flex pra empurrar
    # footer (nome/cargo/sair) pro fundo da sidebar.
    st.sidebar.markdown("""
    <style>
    section[data-testid="stSidebar"] .stButton > button {
        font-family: 'Syne', sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: 1.2px !important;
        font-size: 12px !important;
    }
    /* Sidebar flex column pra empurrar 'Sair' lá pro fundo */
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
        display: flex !important;
        flex-direction: column !important;
        min-height: calc(100vh - 60px) !important;
    }
    /* Spacer que cresce pra empurrar o footer */
    section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(#sb-spacer) {
        flex: 1 1 auto !important;
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

    # Spacer flex-grow que empurra footer pro fim da sidebar
    st.sidebar.markdown('<div id="sb-spacer"></div>', unsafe_allow_html=True)

    # Footer com nome + cargo (alinhado com padding da sidebar, sem position:fixed)
    st.sidebar.markdown(f"""
    <div style="padding:14px 20px 10px;border-top:1px solid #1e2333;margin-top:8px">
        <div style="font-size:13px;color:#e8eaf0;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{current_nome()}</div>
        <div style="font-size:10px;color:#6b7280;margin-top:3px;text-transform:uppercase;letter-spacing:.8px;font-weight:600">{current_role()}</div>
    </div>
    """, unsafe_allow_html=True)

    if st.sidebar.button("Sair da conta", width="stretch"):
        # Limpa TODAS as chaves do session_state — garante que o login
        # subsequente faça fresh load do BQ + cache, sem heranças.
        for k in list(st.session_state.keys()):
            st.session_state.pop(k, None)
        st.rerun()
