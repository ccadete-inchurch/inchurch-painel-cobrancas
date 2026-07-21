import base64
import json
import secrets as _secrets
import urllib.parse
from datetime import datetime

import requests
import streamlit as st

from config import LOGO_SRC
from auth import login_google

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
    # prompt='select_account consent' — forca Google a SEMPRE mostrar seletor
    # de conta + tela de consentimento. Sem isso, Google pula direto pra conta
    # padrao do browser e pode recusar com 403 se essa conta nao estiver em
    # test users. Com seletor, user escolhe manualmente qual conta usar.
    # (removido hd='inchurch.com.br' — bloqueava browser sem sessao ativa
    # de conta @inchurch.com.br mesmo antes de mostrar o seletor.)
    return _AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         "openid email profile",
        "prompt":        "select_account consent",
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
    """Processa o retorno do Google OAuth. Fluxo redirect direto (sem popup):
    a propria pagina do painel eh redirecionada pro Google e volta com
    ?code=X&state=Y. Sem popup, sem polling, sem tabela BQ intermediaria."""
    code = st.query_params.get("code")
    if not code:
        return
    state = st.query_params.get("state", "")
    expected_state = st.session_state.get("oauth_state", "")
    # CSRF: valida state se tiver um esperado na sessao. Se nao tiver (sessao
    # nova apos o redirect), aceita — usuario que veio de tela vazia pra tela
    # com code fresh eh o fluxo normal apos redirect.
    if expected_state and state != expected_state:
        st.query_params.clear()
        st.error("Erro de segurança no login (state invalido). Tente novamente.")
        return
    try:
        g = st.secrets["google"]
        data = _exchange_code(code, g["client_id"], g["client_secret"], g["redirect_uri"])
        st.query_params.clear()
        st.session_state.pop("oauth_state", None)
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


def tela_login():
    _handle_google_callback()

    # ── CSS global + painel esquerdo fixo ─────────────────────────────────────
    _logo_html = (
        f'<img src="{LOGO_SRC}" style="height:56px;object-fit:contain">'
        if LOGO_SRC else
        '<span style="font-family:Syne,sans-serif;font-weight:800;font-size:30px;color:#7cc243;letter-spacing:-0.5px">inChurch</span>'
    )
    st.markdown(f"""
    <style>
    html,body{{background:#0f1117!important}}
    .stApp{{background:#0f1117!important}}
    header,[data-testid="stToolbar"],[data-testid="stDecoration"],
    [data-testid="stStatusWidget"]{{display:none!important}}
    [data-testid="stAppViewBlockContainer"],.main .block-container{{
        padding-top:0!important;padding-bottom:0!important}}
    </style>

    <div style="position:fixed;left:0;top:0;width:50%;height:100vh;
                background:linear-gradient(155deg,#080c12 0%,#0e1520 55%,#0b1708 100%);
                border-right:1px solid rgba(124,194,67,0.12);
                display:flex;flex-direction:column;justify-content:space-between;
                padding:52px 64px;z-index:50;overflow:hidden">
      <div style="position:absolute;bottom:-110px;right:-110px;width:400px;height:400px;
                  border-radius:50%;border:1px solid rgba(124,194,67,0.07)"></div>
      <div style="position:absolute;bottom:-50px;right:-50px;width:220px;height:220px;
                  border-radius:50%;border:1px solid rgba(124,194,67,0.11)"></div>
      <div style="position:absolute;top:22%;left:-70px;width:200px;height:200px;
                  border-radius:50%;border:1px solid rgba(124,194,67,0.06)"></div>

      <div>
        <div style="font-size:11px;color:#6b7280;font-weight:500;letter-spacing:0.5px;margin-bottom:6px">v2.0</div>
        <div>{_logo_html}</div>
      </div>

      <div>
        <div style="display:inline-flex;align-items:center;gap:7px;
                    background:rgba(124,194,67,0.1);border:1px solid rgba(124,194,67,0.2);
                    color:#7cc243;font-size:13px;font-weight:700;letter-spacing:1.5px;
                    text-transform:uppercase;padding:6px 16px;border-radius:20px;margin-bottom:36px">
          <div style="width:7px;height:7px;border-radius:50%;background:#7cc243"></div>Financeiro
        </div>
        <h1 style="font-size:44px;font-weight:800;color:#f1f5f9;line-height:1.1;margin:0 0 24px;
                   letter-spacing:-1.5px;font-family:-apple-system,BlinkMacSystemFont,sans-serif">
          Painel de<br><span style="color:#7cc243">Cobranças</span>
        </h1>
        <p style="font-size:20px;color:#6b7280;line-height:1.7;margin:0 0 52px;max-width:400px">
          Plataforma de gestão de inadimplência: pagamentos em tempo real, dados consolidados no BigQuery e histórico completo das negociações.
        </p>
        <div style="display:flex;flex-direction:column;gap:24px">
          <div style="display:flex;align-items:center;gap:18px">
            <div style="width:44px;height:44px;border-radius:10px;flex-shrink:0;
                        background:rgba(124,194,67,0.1);border:1px solid rgba(124,194,67,0.2);
                        display:flex;align-items:center;justify-content:center;font-size:20px">⚡</div>
            <span style="color:#9ca3af;font-size:17px">Pagamentos do dia real-time via API Superlógica</span>
          </div>
          <div style="display:flex;align-items:center;gap:18px">
            <div style="width:44px;height:44px;border-radius:10px;flex-shrink:0;
                        background:rgba(124,194,67,0.1);border:1px solid rgba(124,194,67,0.2);
                        display:flex;align-items:center;justify-content:center;font-size:20px">📊</div>
            <span style="color:#9ca3af;font-size:17px">Carteira centralizada no BigQuery da inChurch</span>
          </div>
          <div style="display:flex;align-items:center;gap:18px">
            <div style="width:44px;height:44px;border-radius:10px;flex-shrink:0;
                        background:rgba(124,194,67,0.1);border:1px solid rgba(124,194,67,0.2);
                        display:flex;align-items:center;justify-content:center;font-size:20px">💬</div>
            <span style="color:#9ca3af;font-size:17px">Histórico de contatos e negociações por cliente</span>
          </div>
        </div>
      </div>

      <div style="font-size:14px;color:#6b7280">© {datetime.now().year} inChurch · Uso interno</div>
    </div>
    """, unsafe_allow_html=True)

    # ── Lado direito: área de login ────────────────────────────────────────────
    _, right = st.columns(2)
    with right:
        st.markdown('<div style="height:28vh"></div>', unsafe_allow_html=True)
        st.markdown("""
        <div style="padding:0 48px 0 36px">
          <h2 style="font-size:42px;font-weight:800;color:#f1f5f9;margin:0 0 14px;
                     letter-spacing:-1px;font-family:-apple-system,BlinkMacSystemFont,sans-serif">
            Bem-vindo
          </h2>
          <p style="font-size:17px;color:#6b7280;margin:0 0 36px;line-height:1.6">
            Use sua conta <span style="color:#7cc243;font-weight:600">@inchurch.com.br</span>
            para acessar o painel de cobranças.
          </p>
        </div>
        """, unsafe_allow_html=True)

        _, btn_col, _ = st.columns([0.18, 1, 0.18])
        with btn_col:
            try:
                g = st.secrets["google"]
                # State CSRF: gera 1x por sessao, guarda pra validar no callback.
                # Se ja existe, reusa (usuario pode ter clicado antes e voltado
                # sem completar OAuth).
                if "oauth_state" not in st.session_state:
                    st.session_state["oauth_state"] = _secrets.token_hex(16)
                state = st.session_state["oauth_state"]
                auth_url = _build_auth_url(g["client_id"], g["redirect_uri"], state=state)
                # Link target="_self" — redirect direto na mesma aba (sem popup).
                # Google devolve pra propria pagina do painel com ?code=Y&state=X
                # e _handle_google_callback (chamado no inicio de tela_login) processa.
                st.markdown(f"""
                <a href="{auth_url}" target="_self" style="
                    width:100%;padding:13px 16px;border-radius:10px;
                    background:#1e2333;border:1px solid #2a2f42;
                    color:#e8eaf0;font-size:14px;font-weight:500;cursor:pointer;
                    display:flex;align-items:center;justify-content:center;gap:10px;
                    font-family:-apple-system,BlinkMacSystemFont,sans-serif;box-sizing:border-box;
                    text-decoration:none;transition:background .15s,border-color .15s"
                    onmouseover="this.style.background='#252b3b';this.style.borderColor='#3d4460'"
                    onmouseout="this.style.background='#1e2333';this.style.borderColor='#2a2f42'">
                    {_GOOGLE_ICON} Continuar com Google
                </a>
                """, unsafe_allow_html=True)
            except Exception:
                pass

