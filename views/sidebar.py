import streamlit as st

from config import LOGO_SRC
from auth import is_logged, current_role, current_email, current_nome
from data import ping_online, get_online_users


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
    # Especialista: análise por atendente (gráficos) — admin/gestor only
    if current_role() in ("admin", "gestor"):
        nav_item("Especialista",   "especialista")

    # ── Widget "Online agora" — fragment re-renderiza a cada 30s ─────────────
    # Pinga a própria sessão e mostra todos que pingaram nos últimos 90s.
    # Sem persistência: deploy zera; em 30s a lista reformula sozinha.
    @st.fragment(run_every=30)
    def _online_widget():
        ping_online(current_email(), current_nome())
        online = get_online_users(janela_s=90)
        if not online:
            return
        linhas = "".join(
            f'<div style="display:flex;align-items:center;gap:8px;padding:4px 0">'
            f'<span style="width:8px;height:8px;background:#22c55e;border-radius:50%;'
            f'box-shadow:0 0 0 3px rgba(34,197,94,.15);flex-shrink:0"></span>'
            f'<span style="font-size:12px;color:#e8eaf0;font-weight:500;'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{u["nome"]}</span>'
            f'</div>'
            for u in online
        )
        st.sidebar.markdown(
            f'<div style="padding:14px 20px 6px;margin-top:12px;border-top:1px solid #1e2333">'
            f'<div style="font-size:10px;color:#374151;text-transform:uppercase;'
            f'letter-spacing:1.5px;font-weight:700;margin-bottom:6px">Online agora</div>'
            f'{linhas}'
            f'</div>',
            unsafe_allow_html=True,
        )
    _online_widget()

    # Spacer pra não esconder último nav atrás do botão Sair (fixed bottom)
    st.sidebar.markdown('<div style="height:70px"></div>', unsafe_allow_html=True)

    if st.sidebar.button("Sair da conta", width="stretch"):
        # Limpa TODAS as chaves do session_state — garante que o login
        # subsequente faça fresh load do BQ + cache, sem heranças.
        for k in list(st.session_state.keys()):
            st.session_state.pop(k, None)
        st.rerun()
