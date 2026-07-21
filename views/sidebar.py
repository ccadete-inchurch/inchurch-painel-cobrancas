import streamlit as st

from config import LOGO_SRC
from auth import is_logged, current_role


def render_sidebar():
    if not is_logged():
        st.markdown("""
        <style>
        section[data-testid="stSidebar"]{display:none!important}
        </style>
        """, unsafe_allow_html=True)
        return

    page    = st.session_state.get("page", "atividades")
    logo_sb = f'<img src="{LOGO_SRC}" style="height:30px;object-fit:contain">' if LOGO_SRC else '<span style="font-family:Syne,sans-serif;font-weight:800;font-size:18px;color:#7cc243">InChurch</span>'

    # CSS: 'Sair' fixed no fundo da sidebar (sem footer de nome/role pra
    # competir — já aparecem no header top-right).
    st.sidebar.markdown("""
    <style>
    section[data-testid="stSidebar"],
    section[data-testid="stSidebar"] > div,
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
        overflow: hidden !important;
        overscroll-behavior: contain !important;
    }
    section[data-testid="stSidebar"] [data-testid="stElementContainer"]:last-of-type {
        position: fixed !important;
        bottom: 16px !important;
        left: 0 !important;
        width: 250px !important;
        padding: 0 16px !important;
        z-index: 50 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.sidebar.markdown(f"""
    <div style="padding:24px 20px 18px;border-bottom:1px solid #1e2333;margin-bottom:8px">
        <div style="font-size:10px;color:#6b7280;font-weight:500;letter-spacing:0.5px;margin-bottom:4px">v2.0</div>
        {logo_sb}
        <div style="font-size:12px;color:#8b94a5;margin-top:6px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600">Painel de Cobrança</div>
    </div>
    <div style="padding:6px 20px 8px">
        <div style="font-size:10px;color:#374151;text-transform:uppercase;letter-spacing:1.5px;font-weight:700">Navegação</div>
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

    nav_item("Atividades",          "atividades")
    nav_item("Inadimplência",      "dashboard")
    nav_item("Pagamentos",         "historico")
    nav_item("Próximas Cobranças", "proximas")
    nav_item("Cliente",            "cliente")
    # Especialista: análise por atendente (gráficos) — admin only
    if current_role() == "admin":
        nav_item("Especialista",   "especialista")

    # Spacer pra não esconder último nav atrás do botão Sair (fixed bottom)
    st.sidebar.markdown('<div style="height:70px"></div>', unsafe_allow_html=True)

    if st.sidebar.button("Sair da conta", width="stretch"):
        # Limpa TODAS as chaves do session_state — garante que o login
        # subsequente faça fresh load do BQ + cache, sem heranças.
        for k in list(st.session_state.keys()):
            st.session_state.pop(k, None)
        # st.logout() invalida o cookie do OAuth (st.user) e redireciona
        # pra /. Sem isso, so limpar session_state mantinha o user
        # autenticado pelo Google (cookie ativo) e o painel logava de novo.
        st.logout()
