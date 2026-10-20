import streamlit as st

from config import LOGO_SRC, VERSAO_CURTA
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
       tela estreita a sidebar encolhe pra 200px e o botao de 250px
       transbordava — era o que deixava ele torto no print do Caio. */
    @media (max-width:1500px){
      section[data-testid="stSidebar"] [data-testid="stElementContainer"]:last-of-type{
          width: 200px !important; padding: 0 10px !important;
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
    <div style="padding:18px 16px 14px;border-bottom:1px solid #1e2333;margin-bottom:14px">
        <div style="font-size:10px;color:#6b7280;font-weight:500;letter-spacing:0.5px;margin-bottom:4px">v{VERSAO_CURTA}</div>
        {logo_sb}
        <!-- letter-spacing 1.5px custava 25px so de espacamento e fazia
             "PAINEL DE COBRANCAS" quebrar em duas linhas na sidebar de
             200px. 0.8px e nowrap resolvem sem encolher a fonte. -->
        <div style="font-size:12px;color:#8b94a5;margin-top:6px;text-transform:uppercase;letter-spacing:0.8px;font-weight:600;white-space:nowrap">Painel de Cobranças</div>
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

    if st.sidebar.button("Sair", width="stretch"):
        # Limpa TODAS as chaves do session_state — garante que o login
        # subsequente faça fresh load do BQ + cache, sem heranças.
        for k in list(st.session_state.keys()):
            st.session_state.pop(k, None)
        # st.logout() invalida o cookie do OAuth (st.user) e redireciona
        # pra /. Sem isso, so limpar session_state mantinha o user
        # autenticado pelo Google (cookie ativo) e o painel logava de novo.
        st.logout()
