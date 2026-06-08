"""Snapshot diário de inadimplentes (cron 06:00 BRT via GitHub Actions).

Roda 7 DIAS POR SEMANA, independente do lote (que só roda em dias úteis
via n8n). Mantém a tabela cobrancas_snapshot_diario sem buracos —
necessário pra métricas que comparam dia-a-dia (Variação 'Hoje' no
dashboard, Eficácia do contato no Especialista, etc).

Lê só GCP_SA_JSON do environment (não precisa do Postgres n8n).

Estrutura idêntica ao gerar_lote_cron.py (shim do streamlit + import
do data.py) — mas main() faz só 2 passos: load BQ + save snapshot.
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
    """Mimetiza st.session_state: dict-access + attr-access."""
    def __getattr__(self, key):
        return self.get(key)
    def __setattr__(self, key, value):
        self[key] = value


def _cache_decorator(*dargs, **dkwargs):
    """Substitui @st.cache_resource e @st.cache_data — dict simples."""
    def make_wrapper(func):
        cache = {}
        def wrapper(*args, **kwargs):
            try:
                key = (args, tuple(sorted(kwargs.items())))
            except TypeError:
                return func(*args, **kwargs)
            if key not in cache:
                cache[key] = func(*args, **kwargs)
            return cache[key]
        wrapper.clear = lambda: cache.clear()
        wrapper.__wrapped__ = func
        return wrapper
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

    # Snapshot só precisa do BigQuery — passa dict vazio pro n8n_postgres pra
    # não falhar em data.py (que tem código que tenta ler essa secret).
    return _SecretsDict({
        "gcp_service_account": sa,
        "n8n_postgres": _SecretsDict({}),
    })


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

import data  # noqa: E402
data.salvar_cache_local = lambda: None

from data import (  # noqa: E402
    processar_dados_bigquery,
    salvar_snapshot_inadimplentes_hoje,
)


def main():
    print("=" * 60, flush=True)
    print("Cron: snapshot diário de inadimplentes", flush=True)
    print("=" * 60, flush=True)

    print("[1/2] Carregando clientes do BigQuery...", flush=True)
    clientes, n_reg = processar_dados_bigquery()
    print(f"      {len(clientes)} clientes inadimplentes, {n_reg} regularizados", flush=True)

    print("[2/2] Salvando snapshot diário...", flush=True)
    salvar_snapshot_inadimplentes_hoje(clientes)
    print(f"      ✓ snapshot de {len(clientes)} clientes gravado", flush=True)

    print("=" * 60, flush=True)
    print("✅ Snapshot concluído com sucesso", flush=True)


if __name__ == "__main__":
    main()
