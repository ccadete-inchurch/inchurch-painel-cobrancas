from datetime import date
import pandas as pd

from auth import current_uid, get_store


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
