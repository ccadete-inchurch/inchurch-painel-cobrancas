from datetime import date

import streamlit as st

import time as _time

from helpers import get_hist, fmt_moeda_plain, dias_html, get_msg_status
from data import calcular_score, recomendar_acao, load_metricas_from_bq, gerar_tarefas_do_dia, atualizar_tarefas_bq, _EMAIL_GRUPO
from auth import current_nome, current_role, current_email
from views.dialog import dialog_anotar


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


def _render_card(score, acoes, c, role, idx):
    cor = _score_cor(score)
    inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;margin-left:6px;vertical-align:middle">INATIVO</span>' if c.get("_inativo") else ""
    acordo_badge  = '<span style="background:rgba(245,158,11,.2);color:#f59e0b;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-left:6px;vertical-align:middle">ACORDO VENCIDO</span>' if "urgente" in acoes else ""

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
        if st.button("📝 Anotar", key=f"atv_{c['id']}_{idx}", width="stretch"):
            dialog_anotar(c["id"])


def _render_atividades(store, clientes, role):
    # Recarrega métricas do dia a cada 5 min (query pequena, só hoje)
    _ts = st.session_state.get("_metricas_ts", 0)
    if _time.time() - _ts > 300:
        load_metricas_from_bq()
        st.session_state["_metricas_ts"] = _time.time()

    hoje_str = date.today().strftime("%d/%m/%Y")
    nome  = current_nome()  or "usuário"
    email = current_email() or ""

    # ── Gera / carrega lote de 80 tarefas do dia ──────────────────────────────
    _key_tarefas = f"_tarefas_{date.today().isoformat()}_{email}"
    if _key_tarefas not in st.session_state:
        with st.spinner("Preparando tarefas do dia..."):
            ids_hoje = gerar_tarefas_do_dia(clientes, email)
        st.session_state[_key_tarefas] = ids_hoje
    ids_hoje = set(st.session_state[_key_tarefas])

    # Filtra clientes para o lote do dia (gestor vê todos)
    from data import _EMAIL_GRUPO
    if email in _EMAIL_GRUPO:
        clientes = [c for c in clientes if c["id"] in ids_hoje]

    # Atualiza bools na tabela BQ com base no status n8n atual (máx 1x a cada 10 min)
    atendente_bq = _EMAIL_GRUPO.get(email)
    _ts_upd = st.session_state.get("_tarefas_update_ts", 0)
    if atendente_bq and _time.time() - _ts_upd > 600:
        status_map = st.session_state.get("_msg_status", {})
        atualizar_tarefas_bq(atendente_bq, status_map, clientes)
        st.session_state["_tarefas_update_ts"] = _time.time()

    st.markdown(
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:52px;'
        f'font-weight:800;color:#e8eaf0;margin-top:32px;margin-bottom:8px;letter-spacing:-1.5px;line-height:1.1">'
        f'Bem-vindo(a), {nome}!</div>'
        f'<div style="font-size:18px;font-weight:600;color:#6b7280;margin-bottom:32px">Atividades</div>',
        unsafe_allow_html=True,
    )

    # ── Progresso do dia — filtra pelo atendente logado ──────────────────────
    _zero = {"mensagens": 0, "ligacoes": 0, "atendidas": 0}
    n8n = st.session_state.get("_n8n_hoje", {"total": _zero, "Priscila Oliveira": _zero, "Ana Carolina": _zero})
    if "mensagens" in n8n:
        n8n = {"total": n8n, "Priscila Oliveira": _zero, "Ana Carolina": _zero}

    nome_logado = (current_nome() or "").lower()
    if "priscila" in nome_logado:
        dados_m, label_m = n8n.get("Priscila Oliveira", _zero), "Priscila Oliveira"
    elif "ana" in nome_logado or "adriely" in nome_logado or "carolina" in nome_logado:
        dados_m, label_m = n8n.get("Ana Carolina", _zero), "Ana Carolina"
    else:
        dados_m, label_m = n8n.get("total", _zero), "Total"

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
        if h.get("status") == "paid":
            continue
        fila.append((calcular_score(c, h), recomendar_acao(c, h), c, h))
    fila.sort(key=lambda x: x[0], reverse=True)

    # ── Filtros ───────────────────────────────────────────────────────────────
    grupos_disp = sorted({c.get("_grupo", "—") for c in clientes if c.get("_grupo") and c.get("_grupo") not in ("—", "")})
    fa, fb, fc = st.columns([1.3, 1.3, 2])
    with fa:
        filtro_grupo = st.selectbox("Grupo", ["Todos"] + grupos_disp, label_visibility="collapsed")
    with fb:
        filtro_inativo = st.selectbox("Situação", ["Todos", "Ativos", "Inativos"], label_visibility="collapsed")
    with fc:
        busca = st.text_input("Buscar", placeholder="Nome ou CNPJ...", label_visibility="collapsed")

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
    def _canal(acoes, msg_st):
        if "urgente" in acoes and msg_st != "concluida":
            return "urgente"
        if msg_st == "concluida":
            return "concluida"
        if msg_st == "tentar_novamente":
            return "tentar_novamente"
        # Mensagem já foi enviada pelo n8n
        if msg_st in ("mensagem", "ligacao_pendente"):
            if "ligar" not in acoes:
                return "concluida"   # só precisava de mensagem → concluída
            else:
                return "ligacao"     # mensagem feita, agora precisa ligar
        # Sem contato ainda → precisa de mensagem primeiro
        if "mensagem" in acoes:
            return "mensagem"
        if "ligar" in acoes:
            return "ligacao"
        return "aguardar"

    acordos = []; ligacao = []; so_msg = []; tentar_nov = []; concluida = []; aguardar = []
    for item in fila:
        s, a, c, h = item
        ms = get_msg_status(c.get("telefone", ""))
        canal = _canal(a, ms)
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
        (f'{_wait}AGUARDAR',          aguardar,   "#4b5563"),
    ]

    cols = st.columns(6)
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
                    with st.container():
                        _render_card(score, acoes, c, role, f"{titulo}_{idx}")

