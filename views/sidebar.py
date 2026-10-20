import streamlit as st

from config import LOGO_SRC
from auth import is_logged


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
    /* A largura do 'Sair' e fixa porque position:fixed mede 100% contra a
       JANELA, nao contra a sidebar. Entao ela precisa acompanhar a mao: em
       tela estreita a sidebar encolhe pra 190px e o botao de 250px
       transbordava — era o que deixava ele torto no print do Caio. */
    @media (max-width:1500px){
      section[data-testid="stSidebar"] [data-testid="stElementContainer"]:last-of-type{
          width: 190px !important; padding: 0 10px !important;
      }
    }
    /* Com a sidebar recolhida o 'Sair' ficaria flutuando sobre o conteudo,
       porque position:fixed o tira do fluxo e o translateX da sidebar nao o
       acompanha. */
    section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stElementContainer"]:last-of-type{
        display: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.sidebar.markdown(f"""
    <div style="padding:18px 20px 14px;border-bottom:1px solid #1e2333;margin-bottom:8px">
        {logo_sb}
        <div style="font-size:12px;color:#8b94a5;margin-top:6px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600">Painel de Cobrança</div>
    </div>
    """, unsafe_allow_html=True)

    def nav_item(label, key_page):
        # Pagina ativa vira type="primary" — CSS override no config.py
        # transforma isso em "hover fixo" (fundo verde translucido + texto
        # verde), sem competir com CTAs primary sólidos das outras telas.
        is_active = page == key_page
        btn_type = "primary" if is_active else "secondary"
        if st.sidebar.button(label, key=f"nav_{key_page}", width="stretch", type=btn_type):
            st.session_state["page"] = key_page
            st.rerun()

    nav_item("Lote do Dia",         "atividades")
    nav_item("Inadimplência",      "dashboard")
    nav_item("Pagamentos em Atraso", "historico")
    nav_item("Próximas Cobranças", "proximas")
    nav_item("Ficha do Cliente",   "cliente")
    # Resultados da Cobrança (page key "especialista"): liberada pra todos
    # os perfis — as atendentes veem a equipe inteira, não só a si mesmas.
    nav_item("Resultados da Cobrança", "especialista")

    # Spacer pra não esconder último nav atrás do botão Sair (fixed bottom)
    st.sidebar.markdown('<div style="height:70px"></div>', unsafe_allow_html=True)

    # A versao saiu da tela a pedido do Caio (20/10/2026). A constante fica
    # no config porque e ela que o deploy usa pra confirmar o que subiu.
    if st.sidebar.button("Sair", width="stretch"):
        # Limpa TODAS as chaves do session_state — garante que o login
        # subsequente faça fresh load do BQ + cache, sem heranças.
        for k in list(st.session_state.keys()):
            st.session_state.pop(k, None)
        # st.logout() invalida o cookie do OAuth (st.user) e redireciona
        # pra /. Sem isso, so limpar session_state mantinha o user
        # autenticado pelo Google (cookie ativo) e o painel logava de novo.
        st.logout()
