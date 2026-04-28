import base64
import json

import streamlit as st
from streamlit_oauth import OAuth2Component

from config import LOGO_SRC
from auth import login, login_google

_AUTHORIZE_URL    = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URL        = "https://oauth2.googleapis.com/token"
_REVOKE_TOKEN_URL = "https://oauth2.googleapis.com/revoke"


def _google_oauth_component():
    try:
        g = st.secrets["google"]
        return OAuth2Component(
            g["client_id"], g["client_secret"],
            _AUTHORIZE_URL, _TOKEN_URL, _TOKEN_URL, _REVOKE_TOKEN_URL,
        ), g["redirect_uri"]
    except Exception:
        return None, None


def _decode_id_token(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


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

        # ── Google OAuth ──────────────────────────────────────────────────────
        oauth2, redirect_uri = _google_oauth_component()
        if oauth2:
            result = oauth2.authorize_button(
                name="Continuar com Google",
                icon="https://www.google.com/favicon.ico",
                redirect_uri=redirect_uri,
                scope="openid email profile",
                key="google_oauth",
                extras_params={"prompt": "select_account"},
                use_container_width=True,
            )
            if result and "token" in result:
                try:
                    info  = _decode_id_token(result["token"]["id_token"])
                    email = info.get("email", "")
                    nome  = info.get("name", email)
                    if login_google(email, nome):
                        st.rerun()
                    else:
                        st.error(f"Acesso não autorizado para {email}.")
                except Exception as e:
                    st.error(f"Erro ao processar login Google: {e}")

            st.markdown('<div style="display:flex;align-items:center;gap:12px;margin:16px 0"><div style="flex:1;height:1px;background:#2a2f42"></div><span style="color:#4b5563;font-size:12px">ou</span><div style="flex:1;height:1px;background:#2a2f42"></div></div>', unsafe_allow_html=True)

        # ── E-mail / senha ────────────────────────────────────────────────────
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
