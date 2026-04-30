from datetime import date

import streamlit as st

from config import PAGE_SIZE
from helpers import get_hist, fmt_moeda_plain, dias_html
from data import calcular_score, recomendar_acao
from views.dialog import dialog_editar


def _acao_html(acoes: list[str]) -> str:
    if not acoes:
        return '<span style="background:rgba(107,114,128,.15);color:#6b7280;font-size:11px;font-weight:700;padding:3px 10px;border-radius:6px">✓ Aguardar</span>'
    partes = []
    if "urgente" in acoes:
        partes.append('<span style="background:rgba(239,68,68,.18);color:#ff5555;font-size:11px;font-weight:700;padding:3px 10px;border-radius:6px">🔥 URGENTE</span>')
    if "ligar" in acoes:
        partes.append('<span style="background:rgba(124,194,67,.15);color:#7cc243;font-size:11px;font-weight:700;padding:3px 10px;border-radius:6px">📞 Ligar</span>')
    if "mensagem" in acoes:
        partes.append('<span style="background:rgba(95,163,255,.15);color:#5fa3ff;font-size:11px;font-weight:700;padding:3px 10px;border-radius:6px">💬 Mensagem</span>')
    return " ".join(partes)


def _render_atividades(store, clientes, role):
    hoje_str = date.today().strftime("%d/%m/%Y")

    st.markdown(
        '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:52px;'
        'font-weight:800;color:#e8eaf0;margin-top:32px;margin-bottom:32px;letter-spacing:-1.5px;line-height:1.1">'
        'Atividades</div>',
        unsafe_allow_html=True,
    )

    # ── Progresso do dia ──────────────────────────────────────────────────────
    atendidos_hoje = [
        c for c in clientes
        if get_hist(c["id"]).get("lastContact") == hoje_str
    ]
    n_hoje     = len(atendidos_hoje)
    meta_msg   = 50
    meta_lig   = 30

    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown(
            f'<div class="metric-card">'
            f'<div class="metric-label">Clientes Atendidos Hoje</div>'
            f'<div class="metric-value" style="color:#7cc243;font-size:32px">{n_hoje}</div>'
            f'<div class="metric-sub">contatos registrados</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with m2:
        pct_msg = min(int(n_hoje / meta_msg * 100), 100)
        st.markdown(
            f'<div class="metric-card">'
            f'<div class="metric-label">Meta Mensagens</div>'
            f'<div class="metric-value" style="color:#5fa3ff;font-size:32px">{n_hoje}<span style="font-size:18px;color:#6b7280">/{meta_msg}</span></div>'
            f'<div style="background:#1e2333;border-radius:4px;height:6px;margin-top:10px">'
            f'<div style="background:#5fa3ff;width:{pct_msg}%;height:6px;border-radius:4px"></div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with m3:
        pct_lig = min(int(n_hoje / meta_lig * 100), 100)
        st.markdown(
            f'<div class="metric-card">'
            f'<div class="metric-label">Meta Ligações</div>'
            f'<div class="metric-value" style="color:#f59e0b;font-size:32px">{n_hoje}<span style="font-size:18px;color:#6b7280">/{meta_lig}</span></div>'
            f'<div style="background:#1e2333;border-radius:4px;height:6px;margin-top:10px">'
            f'<div style="background:#f59e0b;width:{pct_lig}%;height:6px;border-radius:4px"></div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ── Calcular scores e filtrar clientes com ação ───────────────────────────
    fila = []
    for c in clientes:
        h     = get_hist(c["id"])
        if h.get("status") == "paid":
            continue
        score = calcular_score(c, h)
        acoes = recomendar_acao(c, h)
        fila.append((score, acoes, c, h))

    fila.sort(key=lambda x: x[0], reverse=True)

    total_fila   = len(fila)
    com_acao     = sum(1 for _, a, _, _ in fila if a)
    sem_acao     = total_fila - com_acao

    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">'
        f'<span style="font-size:15px;font-weight:700;color:#e8eaf0">Fila de Prioridade</span>'
        f'<span style="font-size:13px;color:#6b7280">'
        f'<b style="color:#7cc243">{com_acao}</b> com ação · '
        f'<b style="color:#6b7280">{sem_acao}</b> aguardando · '
        f'<b style="color:#e8eaf0">{total_fila}</b> total'
        f'</span></div>',
        unsafe_allow_html=True,
    )

    # ── Filtro rápido ─────────────────────────────────────────────────────────
    fa, fb, fc = st.columns([3, 1.2, 1])
    with fa:
        mostrar = st.radio(
            "Exibir",
            ["Com ação hoje", "Todos"],
            horizontal=True,
            label_visibility="collapsed",
        )
    with fb:
        filtro_inativo = st.selectbox("Situação", ["Todos", "Ativos", "Inativos"], label_visibility="collapsed")
    with fc:
        busca = st.text_input("Buscar", placeholder="Nome ou CNPJ...", label_visibility="collapsed")

    if mostrar == "Com ação hoje":
        fila = [(s, a, c, h) for s, a, c, h in fila if a]
    if filtro_inativo == "Ativos":
        fila = [(s, a, c, h) for s, a, c, h in fila if not c.get("_inativo")]
    elif filtro_inativo == "Inativos":
        fila = [(s, a, c, h) for s, a, c, h in fila if c.get("_inativo")]
    if busca:
        b    = busca.lower()
        fila = [(s, a, c, h) for s, a, c, h in fila
                if b in str(c.get("nome", "")).lower() or b in str(c.get("cnpj", "")).lower()]

    # ── Paginação ─────────────────────────────────────────────────────────────
    total_f  = len(fila)
    total_pg = max(1, -(-total_f // PAGE_SIZE))
    page     = max(1, min(st.session_state.get("atv_page", 1), total_pg))
    fila_pg  = fila[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    # ── Header da tabela ──────────────────────────────────────────────────────
    col_w  = [0.7, 2.5, 1.2, 1, 1.8] + ([0.6] if role != "gestor" else [])
    hdrs   = ["Score", "Cliente", "Saldo", "Atraso", "Ação"] + ([""] if role != "gestor" else [])
    hdr_cells = "".join(
        f'<div style="flex:{w};padding:12px 14px;font-size:12px;text-transform:uppercase;'
        f'letter-spacing:1.2px;color:#8b94a5;font-weight:700;white-space:nowrap">{h}</div>'
        for w, h in zip(col_w, hdrs)
    )
    st.markdown(
        f'<div style="display:flex;gap:0.5rem;background:#1e2333;border:1px solid #2a2f42;'
        f'border-radius:12px 12px 0 0;overflow:hidden">{hdr_cells}</div>',
        unsafe_allow_html=True,
    )

    if not fila_pg:
        st.markdown(
            '<div style="background:#181c26;border:1px solid #2a2f42;border-top:none;'
            'border-radius:0 0 12px 12px;padding:60px;text-align:center;color:#6b7280;font-size:14px">'
            'Nenhum cliente na fila</div>',
            unsafe_allow_html=True,
        )
    else:
        n_rows = len(fila_pg)
        for ridx, (score, acoes, c, h) in enumerate(fila_pg):
            last = h.get("lastContact", "")
            dias_sem = None
            if last:
                try:
                    from datetime import datetime as _dt
                    dias_sem = (date.today() - _dt.strptime(last, "%d/%m/%Y").date()).days
                except Exception:
                    pass

            score_cor = "#ff5555" if score >= 150 else ("#f59e0b" if score >= 80 else "#5fa3ff")
            rcols = st.columns(col_w, vertical_alignment="center")

            with rcols[0]:
                st.markdown(
                    f'<div style="padding:12px 14px;text-align:center">'
                    f'<div style="font-size:20px;font-weight:800;color:{score_cor};line-height:1">{score}</div>'
                    f'<div style="font-size:10px;color:#6b7280;margin-top:2px">pts</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with rcols[1]:
                sem_contato_txt = f'sem contato há {dias_sem}d' if dias_sem is not None else 'nunca contatado'
                st.markdown(
                    f'<div style="padding:12px 14px">'
                    f'<div style="font-weight:600;font-size:16px;color:#e8eaf0">{c["nome"]}'
                    f'{"<span style=\\"background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-left:6px;vertical-align:middle\\">INATIVO</span>" if c.get("_inativo") else ""}'
                    f'</div>'
                    f'<div style="font-size:13px;color:#6b7280;margin-top:2px">{c.get("cnpj","—")} · {sem_contato_txt}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with rcols[2]:
                st.markdown(
                    f'<div style="padding:12px 14px;font-size:15px;font-weight:600">'
                    f'{fmt_moeda_plain(c["valor"])}</div>',
                    unsafe_allow_html=True,
                )
            with rcols[3]:
                st.markdown(
                    f'<div style="padding:12px 14px">{dias_html(c.get("dias_atraso"))}</div>',
                    unsafe_allow_html=True,
                )
            with rcols[4]:
                st.markdown(
                    f'<div style="padding:12px 14px;display:flex;gap:6px;flex-wrap:wrap">'
                    f'{_acao_html(acoes)}</div>',
                    unsafe_allow_html=True,
                )
            if role != "gestor":
                with rcols[5]:
                    if st.button("✏", key=f"atv_edit_{c['id']}_{ridx}", width="stretch", help=f"Editar {c['nome']}"):
                        dialog_editar(c["id"])

            if ridx < n_rows - 1:
                st.markdown('<div style="height:0.5px;background:#2a2f42;margin:0"></div>', unsafe_allow_html=True)

        st.markdown(
            f'<div style="background:#1e2333;border:1px solid #2a2f42;border-top:none;'
            f'border-radius:0 0 12px 12px;padding:12px 16px;display:flex;'
            f'justify-content:space-between;font-size:13px;color:#8b94a5;font-weight:500">'
            f'<span>Mostrando {(page-1)*PAGE_SIZE+1}–{min(page*PAGE_SIZE,total_f)} de {total_f}</span>'
            f'<span>Página {page} de {total_pg}</span></div>',
            unsafe_allow_html=True,
        )

    if total_pg > 1:
        pc1, pc2, pc3 = st.columns([1, 2, 1])
        with pc1:
            if st.button("← Anterior", key="atv_prev", disabled=(page <= 1), width="stretch"):
                st.session_state["atv_page"] = page - 1
                st.rerun()
        with pc2:
            st.markdown(f'<div style="text-align:center;color:#6b7280;font-size:12px;padding-top:6px">Página {page} de {total_pg}</div>', unsafe_allow_html=True)
        with pc3:
            if st.button("Próxima →", key="atv_next", disabled=(page >= total_pg), width="stretch"):
                st.session_state["atv_page"] = page + 1
                st.rerun()
