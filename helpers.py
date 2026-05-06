import re
from datetime import date, datetime, timedelta, timezone
import pandas as pd

_BRT = timezone(timedelta(hours=-3))


def hoje_brt() -> str:
    """Data de hoje no fuso BRT (America/Sao_Paulo) em ISO. Usar como chave de
    'dia útil' em vez de date.today(), que segue o timezone do servidor (UTC)."""
    return datetime.now(_BRT).date().isoformat()


def hoje_lote() -> str:
    """Data do 'dia operacional' do lote. Vira às 08:15 BRT, não à meia-noite.
    Antes das 08:15, ainda retorna o dia anterior — pra dar tempo da base do BQ
    refletir os pagamentos da noite e evitar gerar lote com dados desatualizados.
    """
    agora = datetime.now(_BRT)
    if agora.hour < 8 or (agora.hour == 8 and agora.minute < 15):
        return (agora.date() - timedelta(days=1)).isoformat()
    return agora.date().isoformat()

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


def get_ultimo_contato_n8n_dias(telefone: str):
    """Retorna quantos dias atrás foi o último contato pelo n8n (qualquer mensagem), ou None."""
    import streamlit as st
    chave = _norm_tel(telefone)
    return st.session_state.get("_msg_ultimo_contato_dias", {}).get(chave)


# ── Painel de tarefas (cooldowns autoritativos) ──────────────────────────────

def get_painel_dias_msg(cliente_id: str):
    """Dias desde a última mensagem registrada em painel_tarefas_diarias, ou None."""
    import streamlit as st
    return st.session_state.get("_painel_dias_msg", {}).get(str(cliente_id))


def get_painel_dias_lig(cliente_id: str):
    """Dias desde a última ligação ATENDIDA (concluída) em painel_tarefas_diarias, ou None.
    Cooldown de 5 dias só conta ligação atendida — tentativas não atendidas não bloqueiam."""
    import streamlit as st
    return st.session_state.get("_painel_dias_lig", {}).get(str(cliente_id))


def get_painel_dias_lig_tentada(cliente_id: str):
    """Dias desde a última tentativa de ligação (atendida OU não), ou None.
    Usado pra badge 'Não atendeu ligação há Xd' — informativo, não afeta cooldown."""
    import streamlit as st
    return st.session_state.get("_painel_dias_lig_tentada", {}).get(str(cliente_id))


def get_painel_acoes_hoje(cliente_id: str) -> dict:
    """Bools do dia atual em painel_tarefas_diarias: {'msg': bool, 'lig': bool, 'atend': bool}."""
    import streamlit as st
    return st.session_state.get("_painel_acoes_hoje", {}).get(str(cliente_id), {})


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
