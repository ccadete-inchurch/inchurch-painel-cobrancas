import streamlit as st

st.set_page_config(
    page_title="InChurch · Cobranças",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

from config import CSS
from auth import is_logged, current_role
from data import get_store, carregar_cache_local, processar_dados_bigquery, load_historico_from_bq, load_mensagens_from_bq, load_metricas_from_bq
from views import (
    render_sidebar, render_header, tela_login, tela_importar,
    _render_dashboard, _render_historico, _render_cliente, _render_proximas,
    _render_atividades,
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


def main():
    # Popup OAuth callback: processa o código e fecha o popup
    _code  = st.query_params.get("code")
    _state = st.query_params.get("state", "")
    if _code and isinstance(_state, str) and _state.startswith("popup_"):
        nonce = _state[len("popup_"):]
        try:
            from views.login import _exchange_code, _decode_id_token
            g   = st.secrets["google"]
            tok = _exchange_code(_code, g["client_id"], g["client_secret"], g["redirect_uri"])
            if "id_token" in tok:
                info  = _decode_id_token(tok["id_token"])
                email = info.get("email", "")
                nome  = info.get("name", email)
                from data import set_pending_oauth
                set_pending_oauth(nonce, email, nome)
        except Exception:
            pass
        st.markdown("""
        <style>
        header{display:none!important}
        [data-testid="stToolbar"]{display:none!important}
        .stApp{background:#181c26!important}
        </style>
        <div style="position:fixed;inset:0;background:#181c26;display:flex;flex-direction:column;
                    align-items:center;justify-content:center;text-align:center;gap:10px;
                    font-family:-apple-system,BlinkMacSystemFont,sans-serif;color:#e8eaf0">
            <div style="font-size:52px;color:#7cc243;line-height:1">✓</div>
            <div style="font-size:18px;font-weight:700;margin:4px 0 0">Login realizado!</div>
            <div style="font-size:13px;color:#6b7280">Pode fechar esta janela.</div>
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    render_sidebar()

    if not is_logged():
        tela_login()
        return

    store = get_store()

    # Carrega clientes: primeiro tenta cache local, depois BQ automaticamente
    if not store["clientes"]:
        carregar_cache_local()

    # Força atualização do BQ se não há dados ou o cache é de um dia anterior
    ultima = store.get("ultima_atualizacao", "")
    cache_desatualizado = True
    if ultima:
        try:
            from datetime import datetime as _datetime, date as _date
            cache_desatualizado = _datetime.strptime(ultima[:10], "%d/%m/%Y").date() < _date.today()
        except Exception:
            pass

    if not store["clientes"] or cache_desatualizado:
        with st.spinner("Carregando dados do BigQuery..."):
            processar_dados_bigquery()

    # Carrega historico de atendimento do BQ uma vez por sessão
    if not st.session_state.get("_historico_loaded"):
        load_historico_from_bq()
        st.session_state["_historico_loaded"] = True

    # Carrega status n8n 1x por sessão (tabela completa)
    if not st.session_state.get("_mensagens_loaded"):
        import time as _t
        load_mensagens_from_bq()
        load_metricas_from_bq()
        st.session_state["_metricas_ts"] = _t.time()
        st.session_state["_mensagens_loaded"] = True

    tela = st.session_state.get("tela", "principal")
    if not store["clientes"] or tela == "importar":
        tela_importar()
    else:
        st.session_state["tela"] = "principal"
        tela_principal()


if __name__ == "__main__":
    main()
