"""Tela de debug pra validar conectividade e estrutura da API Superlógica.
Visível só pra admin/gestor enquanto a integração está em desenvolvimento.
Remover quando a integração estiver estável.
"""
import json as _json
import time as _time
from datetime import date as _date, timedelta as _timedelta
import streamlit as st

from auth import current_role
from data import testar_superlogica_api, fetch_cliente_superlogica, buscar_cliente_por_cnpj, _superlogica_get


def _render_debug_superlogica():
    if current_role() not in ("admin", "gestor"):
        st.error("Acesso restrito.")
        return

    st.markdown(
        '<div style="font-family:-apple-system,sans-serif;font-size:32px;'
        'font-weight:800;color:#e8eaf0;margin-top:16px;margin-bottom:24px;'
        'letter-spacing:-0.5px">🧪 Debug Superlógica API</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        "Use essa tela pra validar conectividade e estrutura de resposta da API. "
        "Tudo aqui é GET (leitura), seguro de rodar."
    )

    # ── Teste 1: ping da API ──────────────────────────────────────────────────
    st.markdown("### 1. Ping da API")
    st.caption("Chama `GET /clientes?itensPorPagina=1` — verifica se tokens funcionam.")
    if st.button("▶ Rodar ping", key="sl_ping"):
        with st.spinner("Consultando Superlógica..."):
            resultado = testar_superlogica_api()
        if resultado["ok"]:
            st.success(f"✅ {resultado['msg']}")
            st.markdown("**Amostra da resposta (primeiro cliente):**")
            st.json(resultado.get("amostra", {}))
        else:
            st.error(f"❌ {resultado['msg']}")
            if resultado.get("detalhes"):
                st.json(resultado["detalhes"])

    st.divider()

    # ── Teste 2: buscar cliente por ID ────────────────────────────────────────
    st.markdown("### 2. Cliente por ID")
    st.caption("Endpoint: `GET /clientes?id={id}`")
    cid_input = st.text_input("ID do cliente (ex: 5497)", key="sl_cid")
    if st.button("▶ Buscar por ID", key="sl_buscar_id") and cid_input:
        with st.spinner(f"Buscando cliente {cid_input}..."):
            cliente = fetch_cliente_superlogica(cid_input)
        if cliente:
            st.success("✅ Cliente encontrado")
            st.json(cliente)
        else:
            st.warning("Não encontrado ou erro na chamada.")

    st.divider()

    # ── Teste 3: buscar por CNPJ ──────────────────────────────────────────────
    st.markdown("### 3. Cliente por CNPJ/CPF")
    st.caption("Endpoint: `GET /clientes?pesquisa={cnpj}`")
    cnpj_input = st.text_input("CNPJ do cliente (com ou sem máscara)", key="sl_cnpj")
    if st.button("▶ Buscar por CNPJ", key="sl_buscar_cnpj") and cnpj_input:
        with st.spinner(f"Buscando CNPJ {cnpj_input}..."):
            cliente = buscar_cliente_por_cnpj(cnpj_input)
        if cliente:
            st.success("✅ Cliente encontrado")
            st.json(cliente)
        else:
            st.warning("Não encontrado ou erro na chamada.")

    st.divider()

    # ── Teste 4: GET genérico ─────────────────────────────────────────────────
    st.markdown("### 4. GET genérico (qualquer endpoint)")
    st.caption(
        "Pra testar outros endpoints. Path deve começar com `/` (ex: `/clientes`, "
        "`/cobrancas`). Base URL `https://api.superlogica.net/v2/financeiro` é "
        "adicionada automaticamente."
    )
    path_input = st.text_input("Path", value="/clientes", key="sl_path")
    params_input = st.text_area(
        "Params (JSON)",
        value='{\n  "itensPorPagina": 2,\n  "status": 2\n}',
        height=120,
        key="sl_params",
    )
    if st.button("▶ Executar GET", key="sl_get_generic"):
        try:
            params = _json.loads(params_input) if params_input.strip() else {}
        except _json.JSONDecodeError as e:
            st.error(f"JSON inválido: {e}")
            return
        with st.spinner(f"GET {path_input}..."):
            status, body, err = _superlogica_get(path_input, params)
        col1, col2 = st.columns(2)
        with col1:
            st.metric("HTTP Status", status)
        with col2:
            st.metric("Sucesso?", "Sim" if status == 200 else "Não")
        if err:
            st.error(f"❌ {err}")
        if body is not None:
            st.markdown("**Resposta:**")
            st.json(body)

    st.divider()

    # ── Teste 5: pagamentos liquidados hoje ───────────────────────────────────
    # Esse é o endpoint-chave pro delta real-time. Single call retorna só
    # cobranças liquidadas hoje → barato e rápido pra rodar a cada N minutos.
    st.markdown("### 5. Pagamentos liquidados hoje")
    st.caption(
        "Endpoint-alvo da integração real-time. "
        "`GET /cobranca?filtrarpor=liquidacao&dtInicio=hoje&dtFim=hoje`. "
        "Mede latência, conta registros, mostra IDs únicos de sacados e amostra do primeiro item."
    )
    hoje = _date.today()
    # Default: últimos 7 dias — cobre gap de fim de semana e mostra estrutura
    # mesmo se hoje for sábado/domingo (banco não liquida).
    col_dt1, col_dt2 = st.columns(2)
    with col_dt1:
        dt_ini = st.date_input("dtInicio", value=hoje - _timedelta(days=7), key="sl_pag_dt_ini")
    with col_dt2:
        dt_fim = st.date_input("dtFim", value=hoje, key="sl_pag_dt_fim")

    if st.button("▶ Buscar pagamentos", key="sl_pag_hoje"):
        params = {
            "filtrarpor": "liquidacao",
            "dtInicio": dt_ini.strftime("%Y-%m-%d"),
            "dtFim": dt_fim.strftime("%Y-%m-%d"),
            "apenasColunasPrincipais": 1,
            "exibirComposicaoDosBoletos": 1,
            "itensPorPagina": 200,
            "pagina": 1,
        }
        with st.spinner("Consultando..."):
            t0 = _time.perf_counter()
            status, body, err = _superlogica_get("/cobranca", params)
            elapsed = _time.perf_counter() - t0

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("HTTP Status", status)
        with col2:
            st.metric("Latência", f"{elapsed:.2f}s")
        with col3:
            qtd = len(body) if isinstance(body, list) else 0
            st.metric("Registros", qtd)

        if err:
            st.error(f"❌ {err}")
            if body is not None:
                st.json(body)
            return

        if not isinstance(body, list) or not body:
            st.warning("Sem cobranças liquidadas hoje (ou resposta vazia).")
            return

        # IDs únicos de sacados — pra estimar quantos clientes "regularizam" no dia
        sacados = set()
        for item in body:
            sid = item.get("id_sacado_sac") or item.get("st_idsacado_sac")
            if sid is not None:
                sacados.add(str(sid))
        st.markdown(f"**Clientes únicos (id_sacado_sac):** {len(sacados)}")
        st.caption(
            f"Capacidade da página (200) {'**ok**' if qtd < 200 else '⚠️ **lotada** — provavelmente precisa paginar'}"
        )

        st.markdown("**Campos disponíveis no primeiro registro:**")
        st.code(", ".join(sorted(body[0].keys())), language="text")

        st.markdown("**Amostra (primeiro registro completo):**")
        st.json(body[0])
