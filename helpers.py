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
    """Retorna o primeiro telefone (legado — preservado pra compat)."""
    if not valor:
        return "—"
    return str(valor).split(";")[0].strip() or "—"


def fmt_tel_lista(valor) -> list[str]:
    """Retorna todos os telefones válidos do cliente (separados por ; no banco).
    Filtra entradas vazias e duplicadas, mantendo a ordem original."""
    if not valor:
        return []
    seen = set()
    out = []
    for raw in str(valor).split(";"):
        tel = raw.strip()
        if tel and tel not in seen:
            seen.add(tel)
            out.append(tel)
    return out


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


def get_streak_cooldown_dias(cliente_id: str):
    """Dias restantes de cooldown 7d por 3 tentativas falhadas consecutivas (lig sem atend).
    Retorna None se cooldown não está ativo. Bloqueia só ligação — mensagem segue regra normal."""
    import streamlit as st
    return st.session_state.get("_streak_cooldown_dias", {}).get(str(cliente_id))


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
        "pending":     "⏳ Sem contato",
        "contacted":   "💬 Contactado",
        "promise":     "🤝 Prometeu pagar",
        "negotiating": "⚖ Negociando",
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


def get_hist_unificado(cid: str) -> dict:
    """Histórico efetivo do cliente respeitando o role:
      - Atendente (Ana/Priscila): só o próprio histórico
      - Admin/gestor: união dos historicos das atendentes — escolhe estado
        mais 'ativo' quando duas marcaram o mesmo cliente
        (promise > negotiating > contacted > pending > paid). Também anota
        `_atendentes_origem` (lista de nomes) pra UI mostrar de quem veio.

    O histórico do próprio admin/gestor é ignorado pra evitar poluição.
    """
    import hashlib
    from auth import current_role
    role = current_role()
    if role not in ("admin", "gestor"):
        return get_hist(cid)

    # Lazy import pra evitar ciclo helpers ↔ data
    from data import _EMAIL_GRUPO as _EG
    nome_por_uid = {hashlib.md5(e.encode()).hexdigest(): nome for e, nome in _EG.items()}
    historicos = get_store().get("historico", {}) or {}
    atendente_uids = set(nome_por_uid.keys())
    melhor = {}
    origens = []
    ordem = {"promise": 3, "negotiating": 2, "contacted": 1, "pending": 0, "paid": -1}
    for uid, ch in historicos.items():
        if uid not in atendente_uids:
            continue
        h = ch.get(cid)
        if not h:
            continue
        origens.append(nome_por_uid[uid])
        if not melhor:
            melhor = dict(h)
            continue
        if ordem.get(h.get("status", "pending"), 0) > ordem.get(melhor.get("status", "pending"), 0):
            melhor.update(h)
        elif h.get("retorno") and not melhor.get("retorno"):
            melhor["retorno"] = h["retorno"]
        elif h.get("promiseDate") and not melhor.get("promiseDate"):
            melhor["promiseDate"] = h["promiseDate"]
    if origens:
        melhor["_atendentes_origem"] = origens
    return melhor


# ── Status efetivo (combina histórico manual + painel_tarefas_diarias) ────────
# Garante que a tela Inadimplência reflete a mesma fonte de verdade do kanban,
# independente de quem está logado. Painel_tarefas_diarias é o source-of-truth
# pra ações do bot; historico manual prevalece pra promise/negotiating/paid.

def get_effective_status(cid) -> str:
    """Status visível na tela. Regra:
    - Decisões manuais (promise/negotiating/paid) sempre vencem — lê do
      histórico unificado (admin vê das atendentes, atendente vê próprio)
    - Senão, se o bot agiu em QUALQUER momento do histórico (sem janela
      temporal), retorna 'contacted'
    - Senão, retorna o que o histórico manual tem (pending por default)
    """
    h = get_hist_unificado(cid)
    manual_st = h.get("status", "")
    if manual_st in ("promise", "negotiating", "paid"):
        return manual_st
    import streamlit as st
    cid_str = str(cid)
    if st.session_state.get("_painel_ultimo_contato_dias", {}).get(cid_str) is not None:
        return "contacted"
    return manual_st or "pending"


def get_effective_atendente(cid) -> str:
    """Atendente dono do cliente. Prioridade:
    1. Manual do histórico unificado (admin vê das atendentes; atendente vê próprio)
       — só vale se for nome de atendente REAL (Ana/Priscila). Filtra fora
       qualquer outro nome legado.
    2. Atendente atual em painel_tarefas_diarias (registro mais recente)
    """
    import streamlit as st
    from data import _EMAIL_GRUPO
    h = get_hist_unificado(cid)
    manual = (h.get("atendente") or "").strip()
    if manual and manual in _EMAIL_GRUPO.values():
        return manual
    return st.session_state.get("_painel_atendente_atual", {}).get(str(cid), "")


def get_effective_lastContact(cid) -> str:
    """Último contato (formato DD/MM/AAAA). Mais recente entre:
    - lastContact manual (do histórico unificado — admin vê das atendentes)
    - última ação do bot em painel_tarefas_diarias (sem janela temporal)
    """
    import streamlit as st
    h = get_hist_unificado(cid)
    manual_lc = h.get("lastContact", "") or ""
    cid_str = str(cid)

    dias_painel = st.session_state.get("_painel_ultimo_contato_dias", {}).get(cid_str)
    if dias_painel is None:
        return manual_lc

    painel_d = date.today() - timedelta(days=int(dias_painel))
    painel_lc = painel_d.strftime("%d/%m/%Y")

    if not manual_lc:
        return painel_lc

    m_d = parse_date_br(manual_lc)
    if m_d is None:
        return painel_lc
    return (m_d if m_d > painel_d else painel_d).strftime("%d/%m/%Y")


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
