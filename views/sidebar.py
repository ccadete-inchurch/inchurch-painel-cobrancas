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

    st.sidebar.markdown(f"""
    <div style="padding:24px 20px 18px;border-bottom:1px solid #1e2333;margin-bottom:8px">
        {logo_sb}
        <div style="font-size:10px;color:#4b5563;margin-top:6px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600">Painel de Cobrança</div>
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

    nav_item("Inadimplência",      "dashboard")
    nav_item("Próximas Cobranças", "proximas")
    nav_item("Regularizados",      "historico")
    nav_item("Cliente",            "cliente")

    st.sidebar.markdown(f"""
    <div style="position:fixed;bottom:0;width:248px;padding:16px 20px;border-top:1px solid #1e2333;background:#13161f">
        <div style="font-size:12px;color:#e8eaf0;font-weight:600">{current_nome()}</div>
        <div style="font-size:10px;color:#4b5563;margin-top:2px;text-transform:uppercase;letter-spacing:.8px">{current_role()}</div>
    </div>
    """, unsafe_allow_html=True)
    st.sidebar.markdown('<div style="height:80px"></div>', unsafe_allow_html=True)

    if st.sidebar.button("Sair da conta", width="stretch"):
        for k in ["user_uid", "user_nome", "user_role", "tela", "page"]:
            st.session_state.pop(k, None)
        st.rerun()
