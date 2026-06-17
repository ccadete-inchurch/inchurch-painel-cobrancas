"""Roda o fetch da API Superlógica isoladamente e imprime os primeiros itens
da resposta + formato do dt_liquidacao_recb. Pra confirmar/refutar a hipótese
de que o parse %m/%d/%Y está rejeitando datas.

Executar com as mesmas env vars do cron (GCP_SA_JSON, PG_N8N_PASSWORD).
"""
import json
import os
import sys
import types
from pathlib import Path


class _SecretsDict(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as e:
            raise AttributeError(key) from e


class _SessionState(dict):
    def __getattr__(self, key):
        return self.get(key)
    def __setattr__(self, key, value):
        self[key] = value


def _cache_decorator(*dargs, **dkwargs):
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


def _noop(*a, **k): pass


def _build_secrets():
    sa_json = os.environ.get("GCP_SA_JSON")
    if not sa_json:
        raise SystemExit("Falta GCP_SA_JSON")
    return _SecretsDict({
        "gcp_service_account": json.loads(sa_json),
        "n8n_postgres": _SecretsDict({
            "host":     os.environ.get("PG_N8N_HOST", "34.56.87.143"),
            "port":     int(os.environ.get("PG_N8N_PORT", "5432")),
            "database": os.environ.get("PG_N8N_DATABASE", "postgres"),
            "user":     os.environ.get("PG_N8N_USER", "n8n-Davi"),
            "password": os.environ.get("PG_N8N_PASSWORD", ""),
            "schema":   "public",
            "table":    "n8nfinchatbot_historico_msgs",
            "sslmode":  "require",
        }),
    })


_st = types.ModuleType("streamlit")
_st.secrets = _build_secrets()
_st.session_state = _SessionState()
_st.cache_resource = _cache_decorator
_st.cache_data = _cache_decorator
_st.error = _noop
_st.warning = _noop
_st.info = _noop
_st.write = _noop
_st.success = _noop
_st.markdown = _noop
_st.toast = _noop
_st.spinner = lambda *a, **k: type("X", (), {"__enter__": lambda s: s, "__exit__": lambda *a: None})()
_st.empty = lambda: types.SimpleNamespace(
    write=_noop, success=_noop, error=_noop, info=_noop, markdown=_noop,
)
sys.modules["streamlit"] = _st


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data import _superlogica_get  # noqa: E402
from helpers import hoje_lote  # noqa: E402
from datetime import date, timedelta


hoje = date.fromisoformat(hoje_lote())
dt_inicio = hoje - timedelta(days=2)
print(f"Janela: {dt_inicio.isoformat()} a {hoje.isoformat()}")
print()

status, body, _ = _superlogica_get("/cobranca", {
    "filtrarpor": "liquidacao",
    "dtInicio":   dt_inicio.isoformat(),
    "dtFim":      hoje.isoformat(),
    "itensPorPagina": 200,
    "pagina": 1,
})

print(f"HTTP status: {status}")
print(f"Body type: {type(body).__name__}")
print(f"Body len: {len(body) if hasattr(body, '__len__') else 'N/A'}")
print()

if isinstance(body, list) and body:
    print("Primeiros 3 itens (chaves relevantes):")
    for i, item in enumerate(body[:3]):
        print(f"\n  Item {i+1}:")
        for k in ("id_sacado_sac", "st_nome_sac", "dt_liquidacao_recb",
                  "dt_recebimento_recb", "vl_total_recb", "id_recebimento_recb"):
            print(f"    {k}: {item.get(k)!r}")
elif isinstance(body, dict):
    print("Body é dict (não list). Chaves:", list(body.keys())[:10])
    print("Conteúdo parcial:", json.dumps(body, ensure_ascii=False, indent=2)[:500])
else:
    print("Body vazio ou inesperado:", body)
