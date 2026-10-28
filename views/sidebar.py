import streamlit as st

from config import logo_src, VERSAO_CURTA
from auth import is_logged


def render_sidebar():
    if not is_logged():
        st.markdown("""
        <style>
        section[data-testid="stSidebar"]{display:none!important}
        </style>
        """, unsafe_allow_html=True)
        return

    page  = st.session_state.get("page", "atividades")
    claro = st.session_state.get("tema_claro", False)
    # A arte muda com o tema: a do painel tem "inchurch" em branco e sumiria
    # no fundo claro, sobrando so os quadradinhos verdes.
    _src    = logo_src(claro)
    logo_sb = f'<img src="{_src}" style="height:30px;object-fit:contain">' if _src else '<span style="font-family:Syne,sans-serif;font-weight:800;font-size:18px;color:var(--brand)">InChurch</span>'

    # O 'Sair' fica no rodape da sidebar por FLEX, nao por position:fixed.
    #
    # Com fixed ele saia do fluxo e ancorava na JANELA, nao na sidebar — e
    # cada consequencia disso virou um remendo: largura fixa em 250/200px
    # (porque width:100% passava a medir a janela), display:none ao recolher
    # (porque o translateX da sidebar nao levava ele junto), um espacador de
    # 70px pro ultimo item nao ficar atras dele, e ainda assim, em janela
    # baixa, ele cobria o menu — que nao rolava, por causa do overflow:hidden
    # logo acima.
    #
    # margin-top:auto numa coluna flex faz o mesmo trabalho sem nenhum dos
    # quatro: o espaco que sobra empurra o botao pro fim, e quando nao sobra
    # espaco ele simplesmente segue o ultimo item e rola junto.
    st.sidebar.markdown("""
    <style>
    section[data-testid="stSidebar"],
    section[data-testid="stSidebar"] > div,
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        overflow: hidden !important;
        overscroll-behavior: contain !important;
    }
    /* A lista de navegacao rola quando a janela e baixa demais pra ela.
       'auto' nao mostra barra nenhuma enquanto couber, entao em altura
       normal nada muda. */
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
        overflow-y: auto !important;
        overscroll-behavior: contain !important;
        height: 100% !important;
    }
    /* Coluna flex ocupando a altura toda — e o que da ao margin-top:auto o
       espaco pra distribuir. */
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > [data-testid="stVerticalBlock"] {
        display: flex !important;
        flex-direction: column !important;
        min-height: 100% !important;
    }
    /* O empurrao vai no ULTIMO elemento, que hoje e o 'Sair' sozinho. Enquanto
       o botao de tema morava aqui, ele ia no PENULTIMO pros dois descerem
       juntos como um rodape; o tema foi pra topbar e deixar :nth-last-of-type(2)
       jogaria o "Desempenho" pro fundo da sidebar. */
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="stElementContainer"]:last-of-type {
        margin-top: auto !important;
        padding-bottom: 8px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.sidebar.markdown(f"""
    <div style="padding:18px 16px 14px;border-bottom:1px solid var(--surface-2);margin-bottom:14px">
        <div style="font-size:10px;color:var(--txt-3);font-weight:500;letter-spacing:0.5px;margin-bottom:4px">v{VERSAO_CURTA}</div>
        {logo_sb}
        <!-- letter-spacing 1.5px custava 25px so de espacamento e fazia
             "PAINEL DE COBRANCAS" quebrar em duas linhas na sidebar de
             200px. 0.8px e nowrap resolvem sem encolher a fonte. -->
        <div style="font-size:12px;color:var(--txt-2);margin-top:6px;text-transform:uppercase;letter-spacing:0.8px;font-weight:600;white-space:nowrap">Painel de Cobranças</div>
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

    nav_item("Lote do Dia",          "atividades")
    nav_item("Inadimplência",        "dashboard")
    nav_item("Pagamentos em Atraso", "historico")
    nav_item("A Vencer",             "proximas")
    nav_item("Ficha do Cliente",     "cliente")
    # "Desempenho" e nao "Resultados da Cobranca": o painel inteiro ja se
    # chama "de Cobrancas", entao o nome antigo nao distinguia esta tela de
    # nenhuma outra — e ela fala da EQUIPE (ranking, matriz, taxas), nao das
    # cobrancas. A chave "especialista" fica: e so rotulo.
    # Liberada pra todos os perfis — as atendentes veem a equipe inteira,
    # nao so a si mesmas.
    nav_item("Desempenho",           "especialista")

    # O alternador de tema foi pra topbar (views/header.py): virou um
    # botao redondo de sol/lua no canto, em vez de um item de menu de
    # largura inteira competindo com a navegacao.

    # Sem espacador: ele existia porque o 'Sair' era position:fixed e cobria
    # o ultimo item. Agora o botao esta no fluxo e o margin-top:auto cuida do
    # espaco — o espacador so roubaria altura da lista em janela baixa.
    if st.sidebar.button("Sair", width="stretch"):
        # Limpa TODAS as chaves do session_state — garante que o login
        # subsequente faça fresh load do BQ + cache, sem heranças.
        for k in list(st.session_state.keys()):
            st.session_state.pop(k, None)
        # st.logout() invalida o cookie do OAuth (st.user) e redireciona
        # pra /. Sem isso, so limpar session_state mantinha o user
        # autenticado pelo Google (cookie ativo) e o painel logava de novo.
        st.logout()
