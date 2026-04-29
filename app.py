import streamlit as st

st.set_page_config(
    page_title="InChurch · Cobranças",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

from config import CSS
from auth import is_logged, current_role
from data import get_store, carregar_cache_local, processar_dados_bigquery, load_historico_from_bq
from views import (
    render_sidebar, render_header, tela_login, tela_importar,
    _render_dashboard, _render_historico, _render_cliente, _render_proximas,
)

st.markdown(CSS, unsafe_allow_html=True)


def tela_principal():
    store    = get_store()
    clientes = store["clientes"]
    role     = current_role()

    render_header()
    page = st.session_state.get("page", "dashboard")

    if page == "dashboard":
        _render_dashboard(store, clientes, role)
    elif page == "historico":
        _render_historico(store)
    elif page == "cliente":
        _render_cliente(store, clientes)
    elif page == "proximas":
        _render_proximas(store, clientes)


def main():
    # Handle Google OAuth popup callback before anything else (avoids BQ loading in popup)
    _code = st.query_params.get("code")
    _state = st.query_params.get("state", "")
    if _code and _state == "popup":
        import streamlit.components.v1 as _components
        import urllib.parse as _urlparse
        parent_url = f"/?code={_urlparse.quote(str(_code), safe='')}"
        _components.html(f"""
        <html><body style="background:#181c26;color:#e8eaf0;font-family:sans-serif;padding:40px;text-align:center">
        <p id="msg">Autenticando...</p>
        <script>
        var _url = '{parent_url}';
        try {{
            // popup foi aberto pelo iframe do botão → parent.opener = iframe botão → .parent = janela principal
            window.parent.opener.parent.location.href = _url;
            setTimeout(function(){{ window.parent.close(); }}, 500);
        }} catch(e) {{
            try {{
                // fallback: opener é a janela principal diretamente
                window.parent.opener.location.href = _url;
                setTimeout(function(){{ window.parent.close(); }}, 500);
            }} catch(e2) {{
                document.getElementById('msg').textContent = 'Autenticado! Pode fechar esta janela.';
            }}
        }}
        </script>
        </body></html>
        """, height=300)
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

    tela = st.session_state.get("tela", "principal")
    if not store["clientes"] or tela == "importar":
        tela_importar()
    else:
        st.session_state["tela"] = "principal"
        tela_principal()


if __name__ == "__main__":
    main()
