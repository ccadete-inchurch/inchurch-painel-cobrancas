from datetime import date

import streamlit as st

import time as _time

from helpers import get_hist, fmt_moeda_plain, dias_html, get_msg_status, get_ultimo_contato_n8n_dias, get_msg_concluida_dias, get_painel_dias_lig, get_painel_dias_lig_tentada, get_painel_dias_msg, get_painel_acoes_hoje, hoje_brt
from data import calcular_score, recomendar_acao, load_mensagens_from_bq, load_cooldowns_from_painel, gerar_tarefas_do_dia, atualizar_tarefas_bq, get_lote_buckets_bq, _EMAIL_GRUPO
from auth import current_nome, current_role, current_email
from views.dialog import dialog_editar


@st.fragment(run_every=60)
def _auto_refresh_n8n():
    """A cada 60s: recarrega status N8N direto do Postgres (responsivo, sem atraso de transferência).
    Detecta virada de dia BRT e força rerun do app inteiro pra renovar o lote."""
    hoje = hoje_brt()
    if st.session_state.get("_dia_ativo") != hoje:
        st.session_state["_dia_ativo"] = hoje
        st.rerun(scope="app")
        return
    last_ts = st.session_state.get("_metricas_ts", 0)
    if _time.time() - last_ts < 50:
        return
    load_mensagens_from_bq()
    st.session_state["_metricas_ts"] = _time.time()
    st.rerun(scope="app")


@st.fragment(run_every=90)
def _auto_refresh_painel():
    """Ciclo curto (~90s): MERGE bools no painel + recarrega cooldowns/metricas.
    Mantém contadores do topo e estado de hoje atualizados quase em tempo real."""
    last_ts = st.session_state.get("_painel_refresh_ts", 0)
    if _time.time() - last_ts < 80:
        return
    from auth import get_store
    status_map = st.session_state.get("_msg_status", {})
    clientes = get_store().get("clientes", []) if status_map else []
    if status_map and clientes:
        for _atd in _EMAIL_GRUPO.values():
            atualizar_tarefas_bq(_atd, status_map, clientes)
    load_cooldowns_from_painel()
    st.session_state["_painel_refresh_ts"] = _time.time()
    st.rerun(scope="app")


def _acao_badge(acoes: list[str]) -> str:
    if "urgente" in acoes:
        return '<span style="background:rgba(239,68,68,.18);color:#ff5555;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">🔥 Urgente</span>'
    if "ligar" in acoes and "mensagem" in acoes:
        return '<span style="background:rgba(124,194,67,.15);color:#7cc243;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">📞 Ligar</span> <span style="background:rgba(95,163,255,.15);color:#5fa3ff;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">💬 Msg</span>'
    if "ligar" in acoes:
        return '<span style="background:rgba(124,194,67,.15);color:#7cc243;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">📞 Ligar</span>'
    if "mensagem" in acoes:
        return '<span style="background:rgba(95,163,255,.15);color:#5fa3ff;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">💬 Mensagem</span>'
    return '<span style="background:rgba(107,114,128,.15);color:#6b7280;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">✓ Aguardar</span>'


def _score_cor(score: int) -> str:
    if score >= 150:
        return "#ff5555"
    if score >= 80:
        return "#f59e0b"
    return "#5fa3ff"


_ICON_PERSON = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="#4b5563" style="flex-shrink:0;vertical-align:middle">'
    '<path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>'
    '</svg>'
)
_ICON_PHONE = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="#6b7280" style="flex-shrink:0;vertical-align:middle">'
    '<path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z"/>'
    '</svg>'
)
_ICON_GROUP = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="#6b7280" style="flex-shrink:0;vertical-align:middle">'
    '<path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>'
    '</svg>'
)


def _motivo(bucket, acoes, c) -> tuple:
    """Retorna (texto, estilo) pro badge do card.
    Fonte primária: painel_tarefas_diarias. Fallback: N8N (histórico mais antigo).
    estilo ∈ 'red' | 'blue' | 'purple' | 'gray' | ''.

    Distingue ligação ATENDIDA (cooldown 5d) de TENTATIVA não atendida (informativo).
    """
    cid = c.get("id")
    tel = c.get("telefone", "")
    acoes_hj = get_painel_acoes_hoje(cid)
    msg_st_n8n  = get_msg_status(tel)
    dsc_n8n     = get_ultimo_contato_n8n_dias(tel)
    dias_lig_atend = get_painel_dias_lig(cid)             # atendida (concluída)
    dias_lig_tent  = get_painel_dias_lig_tentada(cid)     # qualquer tentativa
    if dias_lig_atend is None:
        dias_lig_atend = get_msg_concluida_dias(tel)      # fallback N8N
    dias_msg = get_painel_dias_msg(cid)
    if dias_msg is None:
        dias_msg = dsc_n8n

    if "urgente" in acoes:
        dias = c.get("dias_atraso") or 0
        return f"Acordo vencido há {dias}d · ligação prioritária", "red"

    # Estado HOJE — painel + fallback N8N (sempre exigir contato HOJE no N8N)
    n8n_hoje = (dsc_n8n == 0)
    if acoes_hj.get("atend") or (msg_st_n8n == "concluida" and n8n_hoje):
        return "Ligação atendida hoje", "blue"
    if acoes_hj.get("lig") or (msg_st_n8n == "tentar_novamente" and n8n_hoje):
        return "Não atendeu ligação hoje", "purple"
    if acoes_hj.get("msg") or (msg_st_n8n in ("mensagem", "ligacao_pendente") and n8n_hoje):
        return "Mensagem enviada hoje", "blue"

    # Tentativa não atendida recente (sem atendida posterior) → roxo
    tentou_sem_atender = (
        dias_lig_tent is not None
        and (dias_lig_atend is None or dias_lig_tent < dias_lig_atend)
    )

    if bucket == "ligacao":
        if tentou_sem_atender:
            return f"Não atendeu ligação há {dias_lig_tent}d · Ligação", "purple"
        if dias_lig_atend is not None:
            return f"Última ligação há {dias_lig_atend}d · Ligação", "lig"
        return "Sem ligação anterior · Ligação", "lig"
    if bucket == "mensagem":
        if dias_msg is not None:
            return f"Última mensagem há {dias_msg}d · Mensagem", "msg"
        return "Sem mensagem anterior · Mensagem", "msg"

    # Sem bucket (gestor "Todos os clientes") — fallback por acoes
    if "ligar" in acoes:
        if tentou_sem_atender:
            return f"Não atendeu ligação há {dias_lig_tent}d · Ligação", "purple"
        return (f"Última ligação há {dias_lig_atend}d · Ligação" if dias_lig_atend is not None
                else "Sem ligação anterior · Ligação"), "lig"
    if "mensagem" in acoes:
        return (f"Última mensagem há {dias_msg}d · Mensagem" if dias_msg is not None
                else "Sem mensagem anterior · Mensagem"), "msg"
    return "", ""


def _render_card(score, acoes, c, role, idx, bucket=None):
    cor           = _score_cor(score)
    inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;margin-left:6px;vertical-align:middle">INATIVO</span>' if c.get("_inativo") else ""
    acordo_badge  = '<span style="background:rgba(245,158,11,.2);color:#f59e0b;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-left:6px;vertical-align:middle">ACORDO VENCIDO</span>' if "urgente" in acoes else ""
    motivo_txt, motivo_style = _motivo(bucket, acoes, c)
    _motivo_css = {
        "red":    "color:#ff5555;background:rgba(239,68,68,.08);border-left:2px solid #ff5555;padding:4px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:0.4px",
        "blue":   "color:#7cc243;background:rgba(124,194,67,.08);border-left:2px solid #7cc243;padding:4px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:0.4px",
        "purple": "color:#a78bfa;background:rgba(167,139,250,.08);border-left:2px solid #a78bfa;padding:4px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:0.4px",
        "lig":    "color:#5fa3ff;background:rgba(95,163,255,.08);border-left:2px solid #5fa3ff;padding:4px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:0.4px",
        "msg":    "color:#5fa3ff;background:rgba(95,163,255,.08);border-left:2px solid #5fa3ff;padding:4px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:0.4px",
    }
    motivo_html = (
        f'<div style="font-size:11px;font-weight:600;margin-bottom:8px;{_motivo_css.get(motivo_style, "")}">{motivo_txt}</div>'
        if motivo_txt else ""
    )

    st.markdown(
        f'<div style="background:#181c26;border:1px solid #2a2f42;border-radius:12px;'
        f'padding:14px 16px;margin-bottom:10px;border-top:2px solid {cor}99">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">'
        f'<div style="font-weight:700;font-size:17px;color:#e8eaf0;line-height:1.3;flex:1;margin-right:8px">'
        f'{c["nome"]}'
        f'<div style="font-size:11px;color:#9ca3af;font-weight:400;margin-top:4px;display:flex;align-items:center;flex-wrap:wrap;gap:4px">'
        f'<span>{c.get("cnpj","—")} · ID {c.get("id","—")}</span>'
        f'{inativo_badge}{acordo_badge}'
        f'</div>'
        f'</div>'
        f'<div style="text-align:right;flex-shrink:0">'
        f'<div style="font-size:20px;font-weight:800;color:{cor};line-height:1">{score}</div>'
        f'<div style="font-size:14px;color:#6b7280">pts</div>'
        f'</div></div>'
        f'{motivo_html}'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
        f'<span style="font-size:13px;font-weight:600;color:#e8eaf0">{fmt_moeda_plain(c["valor"])}</span>'
        f'{dias_html(c.get("dias_atraso"))}'
        f'</div>'
        f'<div style="font-size:12px;color:#6b7280">'
        f'<div style="display:flex;align-items:center;gap:5px;margin-bottom:4px">'
        f'{_ICON_PHONE}<span style="color:#9ca3af">{c.get("telefone","—")}</span>'
        f'</div>'
        f'<div style="display:flex;align-items:center;gap:5px">'
        f'{_ICON_GROUP}<span style="color:#9ca3af">{c.get("_grupo","—")}</span>'
        f'</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if role != "gestor":
        if st.button("📋 Detalhes", key=f"atv_{c['id']}_{idx}", width="stretch"):
            dialog_editar(c["id"])


def _render_atividades(store, clientes, role):
    # Ciclo curto (~90s): atualiza painel/metricas. Ciclo longo (30min): cache N8N de fallback.
    _auto_refresh_painel()
    _auto_refresh_n8n()

    hoje_str = date.today().strftime("%d/%m/%Y")
    nome  = current_nome()  or "usuário"
    email = current_email() or ""

    # ── Gera / carrega lote de 80 tarefas do dia ──────────────────────────────
    # session_state guarda {id: bucket} pra rotear cada cliente direto na coluna
    # certa (mensagem/ligacao) sem recalcular acoes. Gestor/admin só geram lote
    # quando entram no modo "Lote do dia" (lá embaixo).
    buckets_hoje = {}
    if email in _EMAIL_GRUPO:
        _key_tarefas = f"_tarefas_{hoje_brt()}_{email}"
        if _key_tarefas not in st.session_state:
            with st.spinner("Preparando tarefas do dia..."):
                st.session_state[_key_tarefas] = gerar_tarefas_do_dia(clientes, email)
        buckets_hoje = st.session_state[_key_tarefas] or {}
    ids_hoje = set(buckets_hoje.keys())

    # Lote estático do dia: 80 IDs fixos. Tarefas concluídas vão pra coluna
    # CONCLUÍDA e ficam visíveis. Renovação só na virada do dia.
    if email in _EMAIL_GRUPO:
        clientes = [c for c in clientes if c["id"] in ids_hoje]

    # ── Painel administrativo (alinhado à direita) ──────────────────────────
    _nomes_atendentes = list(_EMAIL_GRUPO.values())
    _modo_admin       = "Todos os clientes"
    _atendente_sel    = None
    if role in ("admin", "gestor"):
        _admin_spacer, _admin_box = st.columns([2.6, 2.4])
        with _admin_box:
            with st.container(border=True):
                st.markdown(
                    '<div style="display:flex;align-items:center;gap:6px;'
                    'font-size:11px;font-weight:700;color:#9ca3af;text-transform:uppercase;'
                    'letter-spacing:0.7px;margin-bottom:8px">'
                    '<svg width="13" height="13" viewBox="0 0 24 24" fill="#9ca3af">'
                    '<path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/>'
                    '</svg>'
                    'Painel Administrativo</div>',
                    unsafe_allow_html=True,
                )
                _cm, _ca = st.columns([1, 1])
                with _cm:
                    _modo_admin = st.selectbox(
                        "Visualização",
                        ["Todos os clientes", "Lote do dia"],
                        label_visibility="collapsed",
                        key="_admin_modo",
                    )
                with _ca:
                    if _modo_admin == "Lote do dia":
                        _atendente_sel = st.selectbox(
                            "Atendente",
                            _nomes_atendentes,
                            label_visibility="collapsed",
                            key="_admin_atendente",
                        )

        if _modo_admin == "Lote do dia" and _atendente_sel:
            _key_lote = f"_tarefas_admin_{hoje_brt()}_{_atendente_sel}"
            if _key_lote not in st.session_state:
                with st.spinner(f"Carregando lote de {_atendente_sel}..."):
                    buckets_bq = get_lote_buckets_bq(_atendente_sel, store["clientes"])
                    if not buckets_bq:
                        _GRUPO_EMAIL = {v: k for k, v in _EMAIL_GRUPO.items()}
                        _email_atend = _GRUPO_EMAIL.get(_atendente_sel, "")
                        buckets_bq = gerar_tarefas_do_dia(clientes, _email_atend)
                    st.session_state[_key_lote] = buckets_bq
            buckets_lote = st.session_state[_key_lote] or {}
            ids_lote = set(buckets_lote.keys())

            # Lote estático do dia: mostra os 80 IDs fixos do atendente selecionado
            clientes = [c for c in clientes if c["id"] in ids_lote]
            # Quando admin visualiza lote de outro atendente, usa o bucket dele
            buckets_hoje = buckets_lote

    st.markdown(
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:52px;'
        f'font-weight:800;color:#e8eaf0;margin-top:32px;margin-bottom:32px;letter-spacing:-1.5px;line-height:1.1">'
        f'Bem-vindo(a), {nome}!</div>',
        unsafe_allow_html=True,
    )

    # ── Progresso do dia — contagem direto do painel_tarefas_diarias ─────────
    _zero = {"mensagens": 0, "ligacoes": 0, "atendidas": 0}

    def _metricas_lote_painel(ids_lote=None):
        """Conta bools do painel hoje. Se ids_lote=None, conta total geral."""
        acoes = st.session_state.get("_painel_acoes_hoje", {})
        if ids_lote is None:
            items = list(acoes.values())
        else:
            items = [acoes.get(str(cid), {}) for cid in ids_lote]
        return {
            "mensagens": sum(1 for a in items if a.get("msg")),
            "ligacoes":  sum(1 for a in items if a.get("lig")),
            "atendidas": sum(1 for a in items if a.get("atend")),
        }

    atendente_logado = _EMAIL_GRUPO.get(email)
    if atendente_logado:
        dados_m, label_m = _metricas_lote_painel(ids_hoje), atendente_logado
    elif role in ("admin", "gestor") and _modo_admin == "Lote do dia" and _atendente_sel:
        _key_lote_adm = f"_tarefas_admin_{hoje_brt()}_{_atendente_sel}"
        _ids_lote_adm = set(st.session_state.get(_key_lote_adm, {}))
        dados_m, label_m = _metricas_lote_painel(_ids_lote_adm), _atendente_sel
    else:
        dados_m, label_m = _metricas_lote_painel(None), "Total"

    meta_msg, meta_lig, meta_atend = 50, 30, 15
    n_msg, n_lig, n_atend = dados_m.get("mensagens", 0), dados_m.get("ligacoes", 0), dados_m.get("atendidas", 0)

    st.markdown(f'<div style="font-size:13px;font-weight:700;color:#6b7280;margin-bottom:6px">{label_m}</div>', unsafe_allow_html=True)
    m1, m2, m3 = st.columns(3)
    with m1:
        pct = min(int(n_msg / meta_msg * 100), 100)
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Mensagens Enviadas</div>'
            f'<div class="metric-value" style="color:#5fa3ff;font-size:32px">{n_msg}<span style="font-size:18px;color:#6b7280">/{meta_msg}</span></div>'
            f'<div style="background:#1e2333;border-radius:4px;height:6px;margin-top:10px">'
            f'<div style="background:#5fa3ff;width:{pct}%;height:6px;border-radius:4px"></div></div></div>',
            unsafe_allow_html=True,
        )
    with m2:
        pct = min(int(n_lig / meta_lig * 100), 100)
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Ligações Realizadas</div>'
            f'<div class="metric-value" style="color:#f59e0b;font-size:32px">{n_lig}<span style="font-size:18px;color:#6b7280">/{meta_lig}</span></div>'
            f'<div style="background:#1e2333;border-radius:4px;height:6px;margin-top:10px">'
            f'<div style="background:#f59e0b;width:{pct}%;height:6px;border-radius:4px"></div></div></div>',
            unsafe_allow_html=True,
        )
    with m3:
        pct = min(int(n_atend / meta_atend * 100), 100)
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Ligações Atendidas</div>'
            f'<div class="metric-value" style="color:#7cc243;font-size:32px">{n_atend}<span style="font-size:18px;color:#6b7280">/{meta_atend}</span></div>'
            f'<div style="background:#1e2333;border-radius:4px;height:6px;margin-top:10px">'
            f'<div style="background:#7cc243;width:{pct}%;height:6px;border-radius:4px"></div></div></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ── Montar fila ───────────────────────────────────────────────────────────
    fila = []
    for c in clientes:
        h = get_hist(c["id"])
        fila.append((calcular_score(c, h), recomendar_acao(c), c, h))
    fila.sort(key=lambda x: x[0], reverse=True)

    # ── Filtros ───────────────────────────────────────────────────────────────
    grupos_disp = sorted({c.get("_grupo", "—") for c in clientes if c.get("_grupo") and c.get("_grupo") not in ("—", "")})
    fa, fb, fc = st.columns([1.3, 1.3, 2])
    with fa:
        filtro_grupo = st.selectbox("Grupo", ["Todos"] + grupos_disp, label_visibility="collapsed", key="atv_filtro_grupo")
    with fb:
        filtro_inativo = st.selectbox("Situação", ["Todos", "Ativos", "Inativos"], label_visibility="collapsed", key="atv_filtro_inativo")
    with fc:
        busca = st.text_input("Buscar", placeholder="Nome ou CNPJ...", label_visibility="collapsed", key="atv_busca")

    if filtro_grupo != "Todos":
        fila = [(s, a, c, h) for s, a, c, h in fila if c.get("_grupo") == filtro_grupo]
    if filtro_inativo == "Ativos":
        fila = [(s, a, c, h) for s, a, c, h in fila if not c.get("_inativo")]
    elif filtro_inativo == "Inativos":
        fila = [(s, a, c, h) for s, a, c, h in fila if c.get("_inativo")]
    if busca:
        b = busca.lower()
        fila = [(s, a, c, h) for s, a, c, h in fila
                if b in str(c.get("nome", "")).lower() or b in str(c.get("cnpj", "")).lower()]

    # ── Separar por coluna ────────────────────────────────────────────────────
    # Lote estático: cliente entra na coluna inicial (URGENTE/LIGAÇÃO/MENSAGEM)
    # definida pelo bucket gravado no BQ na geração do lote, e só sai pra
    # CONCLUÍDA ou TENTAR NOVAMENTE quando bool do painel registra ação hoje.
    # Sem transição MSG ↔ LIG no meio do dia. Fonte: painel_tarefas_diarias.
    def _canal(bucket, acoes, acoes_hj, msg_st_n8n, dsc_n8n):
        """Painel é fonte primária pra 'atendido hoje'. N8N entra como fallback
        responsivo (latência: bot atua em segundos, painel só atualiza a cada 10min).
        Fallback N8N só vale se contato foi HOJE (dsc_n8n==0) — status do cache vive 3d.
        """
        n8n_hoje = (dsc_n8n == 0)
        if acoes_hj.get("atend") or (msg_st_n8n == "concluida" and n8n_hoje):
            return "concluida"
        if acoes_hj.get("lig") or (msg_st_n8n == "tentar_novamente" and n8n_hoje):
            return "tentar_novamente"
        if acoes_hj.get("msg") or (msg_st_n8n in ("mensagem", "ligacao_pendente") and n8n_hoje):
            return "concluida"

        if "urgente" in acoes:
            return "urgente"
        if bucket == "ligacao":
            return "ligacao"
        if bucket == "mensagem":
            return "mensagem"
        if "ligar" in acoes:
            return "ligacao"
        if "mensagem" in acoes:
            return "mensagem"
        return "aguardar"

    # Na visão do lote, esconder só os passivos extremos (sem ação alguma)
    _e_lote = email in _EMAIL_GRUPO or (role in ("admin", "gestor") and _modo_admin == "Lote do dia")

    acordos = []; ligacao = []; so_msg = []; tentar_nov = []; concluida = []; aguardar = []
    for item in fila:
        s, a, c, h = item
        tel = c.get("telefone", "")
        bucket = buckets_hoje.get(c["id"]) if isinstance(buckets_hoje, dict) else None
        acoes_hj = get_painel_acoes_hoje(c["id"])
        ms_n8n = get_msg_status(tel)
        dsc_n8n = get_ultimo_contato_n8n_dias(tel)
        canal = _canal(bucket, a, acoes_hj, ms_n8n, dsc_n8n)

        if _e_lote and canal == "aguardar":
            continue

        if   canal == "urgente":          acordos.append(item)
        elif canal == "ligacao":          ligacao.append(item)
        elif canal == "mensagem":         so_msg.append(item)
        elif canal == "tentar_novamente": tentar_nov.append(item)
        elif canal == "concluida":        concluida.append(item)
        else:                             aguardar.append(item)

    def _svg(path, color, size=13, ml=0, mr=6):
        return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="{color}" '
                f'style="flex-shrink:0;margin-left:{ml}px;margin-right:{mr}px">'
                f'<path d="{path}"/></svg>')

    _fire  = _svg("M13.5.67s.74 2.65.74 4.8c0 2.06-1.35 3.73-3.41 3.73-2.07 0-3.63-1.67-3.63-3.73l.03-.36C5.21 7.51 4 10.62 4 14c0 4.42 3.58 8 8 8s8-3.58 8-8C20 8.61 17.41 3.8 13.5.67z", "#7cc243", 17)
    _phone = _svg("M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z", "#f59e0b", 16)
    _env   = _svg("M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z", "#e8eaf0", 15)
    _wait  = _svg("M6 2v6l4 4-4 4v6h12v-6l-4-4 4-4V2H6zm10 14.5V20H8v-3.5l4-4 4 4zm-4-5l-4-4V4h8v3.5l-4 4z", "#6b7280", 16)
    _retry = _svg("M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z", "#a78bfa", 16)
    _check = _svg("M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z", "#7cc243", 16)
    _dot   = '<span style="color:#6b7280;margin:0 7px;font-weight:300;font-size:18px;line-height:1">|</span>'

    colunas = [
        (f'{_fire}URGENTE',           acordos,    "#7cc243"),
        (f'{_env}MENSAGEM',           so_msg,     "#5fa3ff"),
        (f'{_phone}LIGAÇÃO',          ligacao,    "#f59e0b"),
        (f'{_retry}TENTAR NOVAMENTE', tentar_nov, "#a78bfa"),
        (f'{_check}CONCLUÍDA',        concluida,  "#7cc243"),
    ]

    cols = st.columns(len(colunas))
    for col, (titulo, itens, cor) in zip(cols, colunas):
        with col:
            st.markdown(
                f'<div style="background:#1e2333;border-radius:10px 10px 0 0;padding:10px 12px;'
                f'margin-bottom:8px;display:flex;justify-content:space-between;align-items:center">'
                f'<span style="display:inline-flex;align-items:center;font-size:13px;font-weight:800;color:#e8eaf0;letter-spacing:0.3px">{titulo}</span>'
                f'<span style="background:#2a2f42;color:#e8eaf0;font-size:14px;font-weight:800;'
                f'padding:2px 8px;border-radius:10px">{len(itens)}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if not itens:
                st.markdown(
                    '<div style="background:#181c26;border:1px solid #2a2f42;border-radius:10px;'
                    'padding:20px;text-align:center;color:#4b5563;font-size:11px">Nenhum cliente</div>',
                    unsafe_allow_html=True,
                )
            else:
                for idx, (score, acoes, c, h) in enumerate(itens):
                    bk = buckets_hoje.get(c["id"]) if isinstance(buckets_hoje, dict) else None
                    with st.container():
                        _render_card(score, acoes, c, role, f"{titulo}_{idx}", bucket=bk)

