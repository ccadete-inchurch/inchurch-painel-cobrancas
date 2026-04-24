import streamlit as st

from config import LOGO_SRC
from auth import login


def tela_login():
    st.markdown("""
    <style>
    html,body,[class*="css"]{background:#181c26!important}
    div[data-testid="stForm"] .stFormSubmitButton button{background:#7cc243!important;color:#0f1117!important;font-weight:600!important;border:none!important;font-size:14px!important;letter-spacing:0.2px!important}
    div[data-testid="stForm"] .stFormSubmitButton button:hover{background:#8fd44e!important}
    </style>
    """, unsafe_allow_html=True)

    _, col, _ = st.columns([1, 1.1, 1])
    with col:
        logo_html = f'<img src="{LOGO_SRC}" style="height:48px;object-fit:contain">' if LOGO_SRC else '<span style="font-family:Syne,sans-serif;font-weight:800;font-size:24px;color:#7cc243">InChurch</span>'
        st.markdown(f"""
        <div style="margin-top:80px;margin-bottom:36px;text-align:center">
            {logo_html}
            <div style="margin-top:24px;display:flex;align-items:center;gap:12px;justify-content:center">
                <div style="flex:1;height:1px;background:linear-gradient(90deg,transparent,#2a2f42)"></div>
                <div style="font-size:13px;color:#4b5563;text-transform:uppercase;letter-spacing:3px;white-space:nowrap;font-weight:500">Painel de Cobrança</div>
                <div style="flex:1;height:1px;background:linear-gradient(90deg,#2a2f42,transparent)"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            st.markdown("""
            <style>
            div[data-testid="stForm"]{background:transparent!important;border:none!important;padding:0!important}
            </style>
            """, unsafe_allow_html=True)
            email = st.text_input("E-mail", placeholder="seu@inchurch.com.br")
            senha = st.text_input("Senha", type="password", placeholder="••••••••")
            st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
            if st.form_submit_button("Entrar", width="stretch"):
                if login(email, senha):
                    st.rerun()
                else:
                    st.error("E-mail ou senha incorretos.")
