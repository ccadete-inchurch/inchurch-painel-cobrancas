"""Geração headless do lote diário (cron 08:15 BRT via GitHub Actions).

Executa a mesma lógica que o painel executa quando Ana/Priscila abrem o app:
processar_dados_bigquery → load_mensagens_from_bq → load_cooldowns_from_painel
→ gerar_tarefas_do_dia (insere lote no BQ se ainda não existe).

Lê credenciais de variáveis de ambiente (GCP_SA_JSON, PG_N8N_PASSWORD, etc).
Como `data.py` foi escrito acoplado ao Streamlit, instalamos um shim mínimo
do módulo `streamlit` antes de importar — só o suficiente pra resolver os
acessos a st.secrets, st.session_state, st.cache_resource e os no-ops de UI.
"""
import json
import os
import sys
import types
from pathlib import Path


# ── Shim do streamlit (precisa estar em sys.modules ANTES de qualquer import) ──

class _SecretsDict(dict):
    """Mimetiza st.secrets: suporta dict-access, attr-access e .get com default."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as e:
            raise AttributeError(key) from e


class _SessionState(dict):
    """Mimetiza st.session_state: dict-access + attr-access + setdefault/update."""
    def __getattr__(self, key):
        return self.get(key)
    def __setattr__(self, key, value):
        self[key] = value


def _cache_decorator(*dargs, **dkwargs):
    """Substitui @st.cache_resource e @st.cache_data — cacheia em dict simples."""
    def make_wrapper(func):
        cache = {}
        def wrapper(*args, **kwargs):
            try:
                key = (args, tuple(sorted(kwargs.items())))
            except TypeError:
                # args não-hasheáveis: chama direto sem cachear
                return func(*args, **kwargs)
            if key not in cache:
                cache[key] = func(*args, **kwargs)
            return cache[key]
        wrapper.clear = lambda: cache.clear()
        wrapper.__wrapped__ = func
        return wrapper
    # Suporta @st.cache_resource (sem parênteses) e @st.cache_data(ttl=3600)
    if dargs and callable(dargs[0]) and not dkwargs:
        return make_wrapper(dargs[0])
    return make_wrapper


def _log_info(*args, **kwargs):
    print("[INFO]", *args, flush=True)


def _log_warn(*args, **kwargs):
    print("[WARN]", *args, flush=True)


def _log_err(*args, **kwargs):
    print("[ERR]", *args, flush=True)


class _NoopCtx:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _build_secrets():
    sa_json = os.environ.get("GCP_SA_JSON")
    if not sa_json:
        raise SystemExit("❌ Falta env var GCP_SA_JSON (chave do service account em JSON)")
    try:
        sa = json.loads(sa_json)
    except json.JSONDecodeError as e:
        raise SystemExit(f"❌ GCP_SA_JSON inválido: {e}")

    pg_pwd = os.environ.get("PG_N8N_PASSWORD")
    if not pg_pwd:
        raise SystemExit("❌ Falta env var PG_N8N_PASSWORD")

    secrets = _SecretsDict({
        "gcp_service_account": sa,
        "n8n_postgres": _SecretsDict({
            "host":     os.environ.get("PG_N8N_HOST", "34.56.87.143"),
            "port":     int(os.environ.get("PG_N8N_PORT", "5432")),
            "database": os.environ.get("PG_N8N_DATABASE", "postgres"),
            "user":     os.environ.get("PG_N8N_USER", "n8n-Davi"),
            "password": pg_pwd,
            "schema":   os.environ.get("PG_N8N_SCHEMA", "public"),
            "table":    os.environ.get("PG_N8N_TABLE", "n8nfinchatbot_historico_msgs"),
            "sslmode":  os.environ.get("PG_N8N_SSLMODE", "require"),
        }),
    })

    # Superlógica: sem essas chaves a consulta de pagamentos volta vazia SEM
    # erro e o lote sai com clientes que já regularizaram (foi assim desde a
    # criação do cron até 15/09/2026). Não é fatal aqui — se gera ou não o
    # lote sem a API é decidido no main, conforme o estado do BQ.
    sl_app = os.environ.get("SL_APP_TOKEN")
    sl_access = os.environ.get("SL_ACCESS_TOKEN")
    if sl_app and sl_access:
        secrets["superlogica"] = _SecretsDict({
            "app_token":    sl_app,
            "access_token": sl_access,
        })
    else:
        print("[WARN] SL_APP_TOKEN/SL_ACCESS_TOKEN ausentes — API Superlógica indisponível", flush=True)
    return secrets


# Constrói o módulo fake e registra em sys.modules
_st = types.ModuleType("streamlit")
_st.secrets       = _build_secrets()
_st.session_state = _SessionState()
_st.cache_resource = _cache_decorator
_st.cache_data    = _cache_decorator
_st.error         = _log_err
_st.warning       = _log_warn
_st.info          = _log_info
_st.write         = _log_info
_st.success       = _log_info
_st.markdown      = _log_info
_st.toast         = _log_info
_st.spinner       = lambda msg="": _NoopCtx()
_st.empty         = lambda: types.SimpleNamespace(
    write=_log_info, success=_log_info, error=_log_err, info=_log_info, markdown=_log_info,
)
sys.modules["streamlit"] = _st


# ── Agora seguro importar o app ───────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Cache local seria escrito no workspace efêmero do runner — desligamos
# pra evitar confusão. Sobrescreve a função antes do primeiro uso.
import data  # noqa: E402
data.salvar_cache_local = lambda: None

from data import (  # noqa: E402
    processar_dados_bigquery,
    load_mensagens_from_bq,
    load_cooldowns_from_painel,
    gerar_tarefas_do_dia,
    salvar_snapshot_inadimplentes_hoje,
    aplicar_pagamentos_hoje_no_store,
    resetar_status_reincidentes,
    diagnosticar_bq_saude,
    _superlogica_get,
    _EMAIL_GRUPO,
)


def _api_superlogica_ok() -> tuple[bool, str]:
    """Testa a API antes do overlay. fetch_pagamentos_hoje_api devolve {} tanto
    quando ninguém pagou quanto quando a API falhou — aqui separamos os dois.
    Resposta válida é HTTP 200 com lista (vazia inclusive)."""
    from helpers import hoje_lote
    dia = hoje_lote()
    status, body, erro = _superlogica_get("/cobranca", {
        "filtrarpor": "liquidacao",
        "dtInicio": dia,
        "dtFim": dia,
        "itensPorPagina": 1,
        "pagina": 1,
    })
    if status == 200 and isinstance(body, list):
        return True, ""
    return False, erro or f"HTTP {status}"


def main():
    print("=" * 60, flush=True)
    print("Cron: gerando lote diário", flush=True)
    print("=" * 60, flush=True)

    print("[1/7] Carregando clientes do BigQuery...", flush=True)
    clientes, n_reg = processar_dados_bigquery()
    print(f"      {len(clientes)} clientes inadimplentes, {n_reg} regularizados", flush=True)

    print("[2/7] Lendo mensagens N8N (Postgres)...", flush=True)
    load_mensagens_from_bq()

    print("[3/7] Lendo cooldowns do painel...", flush=True)
    load_cooldowns_from_painel()

    print("[4/7] Conferindo pagamentos recentes na API Superlógica...", flush=True)
    # CRÍTICO: rodar ANTES de gerar_tarefas_do_dia. Cliente que regularizou e
    # o BQ ainda não mostra (boleto em compensação, ou BQ em time travel por
    # falha de pipeline) é marcado como _regularizado_hoje — e não entra no lote.
    #
    # Trava: sem a API, o lote só sai se o BQ estiver comprovadamente em dia
    # (motivo 'ok'). 'sem_conn'/'erro' devolvem e_confiavel=True sem ter
    # verificado nada, então contam como NÃO confirmado.
    diag = diagnosticar_bq_saude()
    bq_em_dia = bool(diag.get("e_confiavel")) and diag.get("motivo") == "ok"
    print(f"      BigQuery: {diag.get('motivo')} — {diag.get('detalhes')}", flush=True)

    overlay_ok = False
    api_ok, api_erro = _api_superlogica_ok()
    if api_ok:
        try:
            aplicar_pagamentos_hoje_no_store()
            overlay_ok = True
            _n_reg_overlay = sum(1 for c in clientes if c.get("_regularizado_hoje"))
            _n_parc_overlay = sum(1 for c in clientes if c.get("_pago_parcial_hoje"))
            print(f"      {_n_reg_overlay} regularizados e {_n_parc_overlay} parciais via API "
                  f"(regularizados ficam fora do lote)", flush=True)
        except Exception as e:
            api_erro = f"overlay falhou: {e}"

    bloquear_lote = False
    if not overlay_ok:
        if bq_em_dia:
            print(f"      [WARN] API indisponível ({api_erro}). BigQuery em dia — "
                  f"lote segue sem a conferência.", flush=True)
        else:
            bloquear_lote = True
            print(f"      [ERR] API indisponível ({api_erro}) e BigQuery desatualizado "
                  f"ou não confirmado — lote NÃO será gerado.", flush=True)

    print("[5/7] Resetando status de reincidentes...", flush=True)
    # Cliente que saiu da inadimplência e voltou tem status antigo (promessa,
    # retorno, negociando) referente à dívida JÁ PAGA. Reseta pra atendente
    # tratar como caso novo. Preserva notes e lastContact (contexto vale).
    try:
        n_resets = resetar_status_reincidentes(clientes)
        print(f"      {n_resets} historicos resetados", flush=True)
    except Exception as e:
        print(f"      [WARN] Reset de reincidentes falhou: {e}", flush=True)

    print("[6/7] Gerando lote por atendente...", flush=True)
    resumo = {}
    if bloquear_lote:
        # Sem lote do cron, o painel gera quando a atendente abrir Atividades
        # (gerar_tarefas_do_dia em views/atividades.py), já com o overlay do
        # próprio painel — se a API tiver voltado até lá.
        print("      PULADO — ver [ERR] no passo 4", flush=True)
    else:
        for email_atd, nome_atd in _EMAIL_GRUPO.items():
            buckets = gerar_tarefas_do_dia(clientes, email_atd) or {}
            n_lig = sum(1 for b in buckets.values() if b == "ligacao")
            n_msg = sum(1 for b in buckets.values() if b == "mensagem")
            resumo[nome_atd] = {"total": len(buckets), "ligacao": n_lig, "mensagem": n_msg}
            print(f"      {nome_atd}: {len(buckets)} tarefas (lig={n_lig}, msg={n_msg})", flush=True)

    # Snapshot é independente do lote (usa só BQ e tem a própria defesa).
    print("[7/7] Salvando snapshot diário de inadimplentes...", flush=True)
    salvar_snapshot_inadimplentes_hoje(clientes)
    print(f"      snapshot de {len(clientes)} clientes processado", flush=True)

    print("=" * 60, flush=True)
    if bloquear_lote:
        # Exit != 0 marca a execução como falha no GitHub Actions — é o aviso.
        print("❌ Lote NÃO gerado: API Superlógica indisponível com BigQuery "
              "desatualizado ou não confirmado.", flush=True)
        sys.exit(1)
    print("✅ Lote gerado com sucesso", flush=True)
    print(json.dumps(resumo, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
