from datetime import datetime

import streamlit as st

from config import LOGO_SRC


_GOOGLE_ICON = (
    '<svg width="18" height="18" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0">'
    '<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>'
    '<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>'
    '<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>'
    '<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>'
    '</svg>'
)


def tela_login():
    """Tela de login usando st.login('google') — API oficial do Streamlit
    (>=1.42). Fluxo: usuario clica botao -> Streamlit redireciona pro Google
    -> Google devolve -> Streamlit valida e popula st.user. Sem popup, sem
    polling, sem tabela intermediaria.

    Autorizacao: apenas emails cadastrados em [usuarios] do secrets.toml
    conseguem passar do login (checagem em auth.is_logged)."""

    # Se ja esta autenticado no Google mas nao autorizado, mostra mensagem
    # e opcao de trocar de conta. Preserva o caso onde o Google devolveu
    # email valido mas o painel nao aceita esse email.
    try:
        _google_ok = bool(st.user.is_logged_in)
    except Exception:
        _google_ok = False
    _email_google = getattr(st.user, "email", "") if _google_ok else ""

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

    # ── CSS do botao Google — replica o visual do popup antigo
    # Icone SVG do Google injetado via ::before (background-image data URI).
    # Sem isso, botao ficaria so texto sem simbolo colorido. ─────────────────
    _svg_bytes = _GOOGLE_ICON.encode("utf-8")
    import base64 as _b64
    _svg_b64 = _b64.b64encode(_svg_bytes).decode("ascii")
    st.markdown(f"""
    <style>
    /* Estilo do botao 'Continuar com Google' — replica popup antigo.
       Aplica em stAppViewContainer (funciona no Streamlit 1.59). */
    /* Container do botao — centraliza no meio da coluna e limita a largura
       max pra nao virar barra gigante em telas 4K/ultrawide. */
    div[data-testid="stAppViewContainer"] div[data-testid="stButton"],
    div[data-testid="stAppViewContainer"] .stButton {{
        max-width:360px !important;
        margin-left:auto !important;
        margin-right:auto !important;
    }}
    div[data-testid="stAppViewContainer"] .stButton > button {{
        width:100% !important;
        max-width:360px !important;
        min-height:48px !important;
        padding:12px 24px !important;
        border-radius:10px !important;
        background:#1e2333 !important;
        border:1px solid #2a2f42 !important;
        color:#e8eaf0 !important;
        font-size:14px !important;
        font-weight:500 !important;
        display:flex !important;
        align-items:center !important;
        justify-content:center !important;
        gap:10px !important;
        font-family:-apple-system,BlinkMacSystemFont,sans-serif !important;
        transition:background .15s,border-color .15s !important;
        box-shadow:none !important;
        line-height:1.4 !important;
        letter-spacing:normal !important;
    }}
    div[data-testid="stAppViewContainer"] .stButton > button:hover {{
        background:#252b3b !important;
        border-color:#3d4460 !important;
        transform:none !important;
        box-shadow:none !important;
    }}
    /* Icone SVG do Google via ::before — replica o icone do popup antigo */
    div[data-testid="stAppViewContainer"] .stButton > button::before {{
        content: "" !important;
        display: inline-block !important;
        width: 18px !important;
        height: 18px !important;
        background-image: url("data:image/svg+xml;base64,{_svg_b64}") !important;
        background-size: contain !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
        flex-shrink: 0 !important;
        order: -1 !important;
    }}
    /* RESET: sidebar NAO deve ser afetada pelas regras acima (evita
       flash de estilo durante rerun apos logout). */
    section[data-testid="stSidebar"] div[data-testid="stButton"],
    section[data-testid="stSidebar"] .stButton {{
        max-width:none !important;
        margin-left:0 !important;
        margin-right:0 !important;
    }}
    section[data-testid="stSidebar"] .stButton > button {{
        max-width:none !important;
        min-height:auto !important;
        padding:10px 16px !important;
        font-size:13px !important;
        font-weight:500 !important;
        border-radius:8px !important;
        gap:0 !important;
    }}
    section[data-testid="stSidebar"] .stButton > button::before {{
        content: none !important;
        display: none !important;
        background-image: none !important;
        width: 0 !important;
        height: 0 !important;
    }}
    </style>
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
            # Se Google autenticou mas email nao esta em [usuarios] do secrets:
            # avisa e oferece trocar de conta (st.logout limpa a sessao Google).
            if _google_ok and _email_google:
                st.markdown(
                    f'<div style="padding:0 48px 12px 36px;color:#fb7185;'
                    f'font-size:14px;line-height:1.5">'
                    f'Acesso não autorizado para <b>{_email_google}</b>.<br>'
                    f'Faça login com outra conta @inchurch.com.br.'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if st.button("Trocar de conta", key="btn_logout_and_retry"):
                    st.logout()
            else:
                # Caso normal — nao autenticado ainda. Botao dispara st.login.
                # Sem icon=... pra deixar o SVG do Google injetado via CSS
                # ::before ser o unico simbolo do botao.
                if st.button(
                    "Continuar com Google",
                    key="btn_google_login",
                ):
                    st.login("google")
