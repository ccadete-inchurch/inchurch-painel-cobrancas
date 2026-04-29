import base64
import json
import secrets as _secrets
import urllib.parse

import requests
import streamlit as st
import streamlit.components.v1 as components

from config import LOGO_SRC
from auth import login, login_google

_AUTH_URL  = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"

_GOOGLE_ICON = (
    '<svg width="18" height="18" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0">'
    '<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>'
    '<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>'
    '<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>'
    '<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>'
    '</svg>'
)


def _build_auth_url(client_id: str, redirect_uri: str, state: str = "normal") -> str:
    return _AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         "openid email profile",
        "prompt":        "select_account",
        "state":         state,
    })


def _exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    return requests.post(_TOKEN_URL, data={
        "code":          code,
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  redirect_uri,
        "grant_type":    "authorization_code",
    }, timeout=10).json()


def _decode_id_token(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def _handle_google_callback():
    code = st.query_params.get("code")
    if not code:
        return
    try:
        g = st.secrets["google"]
        data = _exchange_code(code, g["client_id"], g["client_secret"], g["redirect_uri"])
        st.query_params.clear()
        if "id_token" not in data:
            st.error("Erro ao autenticar com Google.")
            return
        info  = _decode_id_token(data["id_token"])
        email = info.get("email", "")
        nome  = info.get("name", email)
        if login_google(email, nome):
            st.rerun()
        else:
            st.error(f"Acesso não autorizado para {email}.")
    except Exception as e:
        st.query_params.clear()
        st.error(f"Erro no login Google: {e}")


@st.fragment(run_every=1)
def _poll_google_oauth(nonce: str):
    from data import get_pending_oauth
    result = get_pending_oauth(nonce)
    if result and login_google(result["email"], result["nome"]):
        st.rerun()


def tela_login():
    _handle_google_callback()

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

        # ── Botão Google (popup) ──────────────────────────────────────────────
        try:
            g = st.secrets["google"]
            if "oauth_nonce" not in st.session_state:
                st.session_state["oauth_nonce"] = _secrets.token_hex(16)
            nonce    = st.session_state["oauth_nonce"]
            auth_url = _build_auth_url(g["client_id"], g["redirect_uri"], state=f"popup_{nonce}")
            components.html(f"""
            <html><body style="margin:0;padding:0;background:transparent">
            <script>
            var _U = '{auth_url}';
            function _go() {{
                var w=480,h=560,x=Math.round(screen.width/2-240),y=Math.round(screen.height/2-280);
                window.open(_U,'_google_oauth','width='+w+',height='+h+',left='+x+',top='+y+',scrollbars=yes');
            }}
            </script>
            <button onclick="_go()" style="
                width:100%;padding:11px 16px;border-radius:8px;
                background:#1e2333;border:1px solid #2a2f42;
                color:#e8eaf0;font-size:14px;font-weight:500;cursor:pointer;
                display:flex;align-items:center;justify-content:center;gap:10px;
                font-family:-apple-system,BlinkMacSystemFont,sans-serif;box-sizing:border-box;
            " onmouseover="this.style.background='#252b3b';this.style.borderColor='#3d4460'"
               onmouseout="this.style.background='#1e2333';this.style.borderColor='#2a2f42'">
                {_GOOGLE_ICON} Continuar com Google
            </button>
            </body></html>
            """, height=52)
            _poll_google_oauth(nonce)
        except Exception:
            pass

        st.markdown('<div style="display:flex;align-items:center;gap:12px;margin:16px 0"><div style="flex:1;height:1px;background:#2a2f42"></div><span style="color:#4b5563;font-size:12px">ou</span><div style="flex:1;height:1px;background:#2a2f42"></div></div>', unsafe_allow_html=True)

        # ── E-mail / senha ────────────────────────────────────────────────────
        with st.form("login_form"):
            st.markdown('<style>div[data-testid="stForm"]{background:transparent!important;border:none!important;padding:0!important}</style>', unsafe_allow_html=True)
            email = st.text_input("E-mail", placeholder="seu@inchurch.com.br")
            senha = st.text_input("Senha", type="password", placeholder="••••••••")
            st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
            if st.form_submit_button("Entrar", width="stretch"):
                if login(email, senha):
                    st.rerun()
                else:
                    st.error("E-mail ou senha incorretos.")
