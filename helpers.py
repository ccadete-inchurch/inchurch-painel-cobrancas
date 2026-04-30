import re
from datetime import date
import pandas as pd

from auth import current_uid, get_store
from pathlib import Path
import json


# ── Telefone ──────────────────────────────────────────────────────────────────

def fmt_tel(valor) -> str:
    if not valor:
        return "—"
    return str(valor).split(";")[0].strip() or "—"


def _norm_tel(phone: str) -> str:
    """Normaliza para DDD (2) + últimos 8 dígitos — chave para cruzar com n8n."""
    p = re.sub(r'\D', '', phone or '')
    if p.startswith('55') and len(p) > 11:
        p = p[2:]
    return (p[:2] + p[-8:]) if len(p) >= 10 else p


def get_msg_status(telefone: str) -> str:
    """Retorna o status da última interação n8n para o telefone do cliente.

    Valores possíveis: sem_contato | mensagem | ligacao_pendente |
                       tentar_novamente | concluida
    """
    import streamlit as st
    chave = _norm_tel(telefone)
    return st.session_state.get("_msg_status", {}).get(chave, "sem_contato")


def get_msg_concluida_dias(telefone: str):
    """Retorna quantos dias atrás foi a última ligação bem-sucedida, ou None."""
    import streamlit as st
    chave = _norm_tel(telefone)
    return st.session_state.get("_msg_concluida_dias", {}).get(chave)


# ── Datas ─────────────────────────────────────────────────────────────────────

def calc_dias(venc):
    if not venc:
        return None
    try:
        d = (
            date(*map(int, reversed(str(venc).split("/"))))
            if "/" in str(venc)
            else pd.to_datetime(venc).date()
        )
        return max((date.today() - d).days, 0)
    except Exception:
        return None


def parse_date_br(s):
    """Converte string 'dd/mm/yyyy' para date. Retorna None se inválido."""
    try:
        p = s.split("/")
        return date(int(p[2]), int(p[1]), int(p[0]))
    except Exception:
        return None


# ── HTML helpers ──────────────────────────────────────────────────────────────

def dias_html(dias):
    if dias is None or (isinstance(dias, float) and pd.isna(dias)):
        return '<span style="color:#6b7280;font-size:12px">—</span>'
    if dias == 0:
        return '<span class="da da-ok">Hoje</span>'
    if dias <= 30:
        return f'<span class="da da-30">{int(dias)}d</span>'
    if dias <= 60:
        return f'<span class="da da-60">{int(dias)}d</span>'
    if dias <= 90:
        return f'<span class="da da-90">{int(dias)}d</span>'
    return f'<span class="da da-max">{int(dias)}d</span>'


def status_html(s):
    cls = {
        "pending":     "badge-pending",
        "contacted":   "badge-contacted",
        "promise":     "badge-promise",
        "negotiating": "badge-negotiating",
        "paid":        "badge-paid",
    }
    lbl = {
        "pending":     "🔴 Sem contato",
        "contacted":   "🟡 Contactado",
        "promise":     "🟠 Prometeu pagar",
        "negotiating": "🔵 Negociando",
        "paid":        "✅ Regularizado",
    }
    return f'<span class="badge {cls.get(s, "badge-pending")}">{lbl.get(s, "Sem contato")}</span>'


# ── Formatação de moeda ───────────────────────────────────────────────────────

def fmt_moeda(v):
    try:
        f = float(v)
        fmt = f"R$ {f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if f >= 5000:
            return f'<span style="font-weight:700;color:#ff6b6b">{fmt}</span>'
        if f >= 1000:
            return f'<span style="font-weight:600;color:#f59e0b">{fmt}</span>'
        return f'<span style="font-weight:500">{fmt}</span>'
    except Exception:
        return "—"


def fmt_moeda_plain(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "—"


# ── Utilitários de dados ──────────────────────────────────────────────────────

def get_col(row, col):
    v = row.get(col)
    return "" if (v is None or (isinstance(v, float) and pd.isna(v))) else str(v).strip()


def get_hist(cid):
    return get_store()["historico"].get(current_uid(), {}).get(cid, {})


def save_hist(cid, data):
    store = get_store()
    uid   = current_uid()
    if uid not in store["historico"]:
        store["historico"][uid] = {}
    store["historico"][uid][cid] = data
    try:
        from data import save_hist_to_bq
        save_hist_to_bq(uid, cid, data)
    except Exception:
        pass
    _persistir_historico(store)


def _persistir_historico(store):
    cache_file = Path(__file__).parent / "cache_dados.json"
    if not cache_file.exists():
        return
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)
        cache["historico"] = store.get("historico", {})
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
