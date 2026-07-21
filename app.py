import streamlit as st

st.set_page_config(
    page_title="InChurch · Cobranças",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

from config import CSS
from auth import is_logged, current_role
from data import get_store, carregar_cache_local, processar_dados_bigquery, load_historico_from_bq, load_mensagens_from_bq, load_cooldowns_from_painel, load_ultimo_contato_painel, load_atendente_atual_painel, load_grupo_atendente_map, aplicar_pagamentos_hoje_no_store, aplicar_grupo_nao_cobrar_no_store, precisa_processar_bq
from views import (
    render_sidebar, render_header, tela_login, tela_importar,
    _render_dashboard, _render_historico, _render_cliente, _render_proximas,
    _render_atividades, _render_especialista,
)

st.markdown(CSS, unsafe_allow_html=True)


def tela_principal():
    store    = get_store()
    clientes = store["clientes"]
    role     = current_role()

    render_header()
    page = st.session_state.get("page", "atividades")

    if page == "dashboard":
        _render_dashboard(store, clientes, role)
    elif page == "historico":
        _render_historico(store)
    elif page == "cliente":
        _render_cliente(store, clientes)
    elif page == "proximas":
        _render_proximas(store, clientes)
    elif page == "atividades":
        _render_atividades(store, clientes, role)
    elif page == "especialista":
        _render_especialista(store, clientes, role)


def main():
    # Checa login ANTES de renderizar sidebar. Sem isso, ao clicar 'Sair da conta'
    # a sidebar (com botoes de nav) renderiza brevemente durante o rerun apos
    # logout, causando flash de estilo (o CSS do login pega temporariamente os
    # botoes da sidebar). Chamando render_sidebar so quando logado, sidebar nunca
    # aparece na tela de login.
    if not is_logged():
        tela_login()
        return

    render_sidebar()

    store = get_store()

    # Carrega clientes: primeiro tenta cache local, depois BQ automaticamente
    if not store["clientes"]:
        carregar_cache_local()

    # Decide se precisa re-processar BQ.
    # Check time-based (data anterior OU pre-08:00 BRT) — sem gate de sessão.
    # Pipeline normalmente termina ~07:30 BRT. Sessões abertas antes (ou
    # cache_resource compartilhado de sessão anterior madrugada) ficam stale
    # até cruzar 08:00. O check detecta e re-processa automaticamente.
    if precisa_processar_bq(store):
        with st.spinner("Carregando dados do BigQuery..."):
            processar_dados_bigquery()

    # Carrega historico de atendimento do BQ uma vez por sessão
    if not st.session_state.get("_historico_loaded"):
        load_historico_from_bq()
        st.session_state["_historico_loaded"] = True

    # Carrega status n8n (fallback) + cooldowns do painel 1x por sessão
    if not st.session_state.get("_mensagens_loaded"):
        import time as _t
        load_mensagens_from_bq()
        load_cooldowns_from_painel()
        # Última interação por cliente sem janela temporal — alimenta o
        # "Último Contato" do dashboard mesmo pra ações antigas (>6 dias).
        load_ultimo_contato_painel()
        # Atendente atual no lote (painel_tarefas_diarias) — fallback do grupo.
        # Tem só clientes que já entraram em algum lote.
        load_atendente_atual_painel()
        st.session_state["_metricas_ts"] = _t.time()
        st.session_state["_mensagens_loaded"] = True

    # Mapa cliente → grupo (atendente). Fonte primária — todos os clientes
    # do splgc-grupo. Gate próprio pra não depender do _mensagens_loaded
    # (sessão antiga pode ter pulado o load se foi setado antes do deploy).
    if not st.session_state.get("_grupo_atendente"):
        load_grupo_atendente_map()

    # Overlay real-time de pagamentos do dia via API Superlógica.
    # Roda a cada render — fetch é cacheado (TTL 5min), apply é O(n) idempotente.
    aplicar_pagamentos_hoje_no_store()

    # Overlay do grupo SL 'NÃO COBRAR!' (id=55) — não existe no BQ, só na API.
    # Roda a cada render — fetch é cacheado (TTL 1h), apply é O(n) idempotente.
    aplicar_grupo_nao_cobrar_no_store()

    tela = st.session_state.get("tela", "principal")
    if not store["clientes"] or tela == "importar":
        tela_importar()
    else:
        st.session_state["tela"] = "principal"
        tela_principal()


if __name__ == "__main__":
    main()
