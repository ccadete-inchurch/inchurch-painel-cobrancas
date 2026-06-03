from datetime import date

import pandas as pd
import streamlit as st

from config import SORT_MAP, STATUS_FILTER_MAP, PAGE_SIZE
from auth import get_store, current_role
from helpers import get_hist, fmt_moeda, fmt_moeda_plain, dias_html, get_effective_status, get_effective_lastContact, get_effective_atendente, parse_date_br
from data import calcular_pendencias, fetch_regularizados_mes_atual, fetch_snapshot_inicio_mes, fetch_snapshot_ontem, fetch_snapshot_semana_passada, fetch_inadimplentes_uniao_mes, fetch_inadimplentes_uniao_semana, concluir_pendencia
import re as _re_tel


# Ícones monocromáticos pros cards de fixado (mesmo padrão da Atividades)
_ICON_FIX_PHONE = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="#6b7280" '
    'style="flex-shrink:0;vertical-align:middle">'
    '<path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 '
    '2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 '
    '1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z"/>'
    '</svg>'
)
_ICON_FIX_GROUP = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="#6b7280" '
    'style="flex-shrink:0;vertical-align:middle">'
    '<path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 '
    '3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 '
    '8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5z'
    'm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33'
    '-4.67-3.5-7-3.5z"/>'
    '</svg>'
)
_ICON_FIX_PERSON = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="#6b7280" '
    'style="flex-shrink:0;vertical-align:middle">'
    '<path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 '
    '2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>'
    '</svg>'
)
_ICON_FIX_WHATSAPP = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="#6b7280" '
    'style="flex-shrink:0;vertical-align:middle">'
    '<path d="M17.5 14.4c-.3-.1-1.7-.8-2-.9-.3-.1-.5-.1-.7.1-.2.3-.7.9-.9 '
    '1.1-.2.2-.3.2-.6.1-1.8-.9-3-1.6-4.2-3.6-.3-.5.3-.5.9-1.6.1-.2.1-.4 '
    '0-.5-.1-.1-.7-1.6-.9-2.2-.2-.6-.5-.5-.7-.5h-.6c-.2 0-.5.1-.8.4-.3.3-1 '
    '1-1 2.5s1 2.9 1.2 3.1c.1.2 2 3.1 4.9 4.3 1.8.8 2.5.9 3.4.7.5-.1 '
    '1.7-.7 1.9-1.4.2-.7.2-1.3.2-1.4-.2-.1-.4-.2-.7-.2zM12 22c-1.7 '
    '0-3.3-.5-4.7-1.3L3 22l1.3-4.4C3.5 16.2 3 14.7 3 13c0-5 4-9 9-9s9 4 '
    '9 9-4 9-9 9z"/>'
    '</svg>'
)


def _tel_only_digits(tel: str) -> str:
    """Normaliza telefone pra links tel:/wa.me. Adiciona DDI 55 se faltando."""
    digits = _re_tel.sub(r"\D", "", tel or "")
    if len(digits) >= 10 and not digits.startswith("55"):
        digits = "55" + digits
    return digits


def _hex_to_rgba(hex_color: str, alpha: float = 0.15) -> str:
    """Converte cor hex (#rrggbb) pra rgba pra background tintado de badge."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return f"rgba(107,114,128,{alpha})"
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    except ValueError:
        return f"rgba(107,114,128,{alpha})"
from views.dialog import dialog_editar


def _reset_filtros():
    from config import SORT_MAP as _SM
    st.session_state["fpills"]    = "Todos"
    st.session_state["fordenar"]  = list(_SM.keys())[0]
    st.session_state["fgrupo"]    = "Todos"
    st.session_state["fsituacao"] = "Todos"
    st.session_state["fatraso"]   = "Todos"
    st.session_state["fvalor"]    = "Todos"
    st.session_state["facordo"]   = "Todos"
    st.session_state["busca"]     = ""


def _render_dashboard(store, clientes, role):
    # Pequeno espaço no topo (cards são o primeiro elemento agora).
    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)

    # Remove regularizados-hoje (pagaram hoje via API Superlógica) de TODAS
    # as métricas/tabela. Saem da inadimplência em tempo real, aparecem na
    # aba Regularizados via overlay aplicado em app.py.
    clientes = [c for c in clientes if not c.get("_regularizado_hoje")]

    # ── Lê filtros do session_state pra cards e tabela usarem o mesmo df ──
    # Widgets renderizam depois, mas session_state preserva seleção entre runs
    # (default na primeira renderização, valor do usuário daí em diante).
    busca           = st.session_state.get("busca",     "") or ""
    filtro_status   = st.session_state.get("fpills",    "Todos") or "Todos"
    filtro_grupo    = st.session_state.get("fgrupo",    "Todos")
    filtro_situacao = st.session_state.get("fsituacao", "Todos")
    filtro_atraso   = st.session_state.get("fatraso",   "Todos")
    filtro_valor    = st.session_state.get("fvalor",    "Todos")
    filtro_acordo   = st.session_state.get("facordo",   "Todos")
    ordenar         = st.session_state.get("fordenar",  list(SORT_MAP.keys())[0])

    # ── Constrói df e aplica filtros (compartilhado: métricas, tabela, CSV) ──
    df = pd.DataFrame(clientes)
    if not df.empty:
        df["_status"]      = df["id"].apply(get_effective_status)
        df["_lastContact"] = df["id"].apply(get_effective_lastContact)
        df["_atendente"]   = df["id"].apply(get_effective_atendente)
        df["_notes"]       = df["id"].apply(lambda i: get_hist(i).get("notes", ""))
        from data import calcular_score
        df["_score"]       = df.apply(lambda r: calcular_score(r.to_dict(), get_hist(r["id"])), axis=1)
        df["_score_pct"]   = df["_score"].rank(pct=True, method="max").fillna(0)

        if busca:
            b = busca.lower()
            mask = df.apply(lambda r: b in str(r.get("nome", "")).lower() or b in str(r.get("cnpj", "")).lower() or b in str(r.get("id", "")).lower(), axis=1)
            df = df[mask]
        if filtro_status != "Todos":
            df = df[df["_status"] == STATUS_FILTER_MAP.get(filtro_status, "pending")]
        if filtro_atraso == "1-30 dias":
            df = df[df["dias_atraso"].apply(lambda d: d is not None and 1 <= d <= 30)]
        elif filtro_atraso == "31-60 dias":
            df = df[df["dias_atraso"].apply(lambda d: d is not None and 31 <= d <= 60)]
        elif filtro_atraso == "61-90 dias":
            df = df[df["dias_atraso"].apply(lambda d: d is not None and 61 <= d <= 90)]
        elif filtro_atraso == "+90 dias":
            df = df[df["dias_atraso"].apply(lambda d: d is not None and d > 90)]
        if filtro_valor == "≤ R$500":
            df = df[df["valor"] <= 500]
        elif filtro_valor == "R$500–2k":
            df = df[(df["valor"] > 500) & (df["valor"] <= 2000)]
        elif filtro_valor == "R$2k–5k":
            df = df[(df["valor"] > 2000) & (df["valor"] <= 5000)]
        elif filtro_valor == "> R$5k":
            df = df[df["valor"] > 5000]
        if filtro_acordo != "Todos":
            tem_acordo = df["_tem_acordo"].fillna(False).astype(bool) if "_tem_acordo" in df.columns else pd.Series(False, index=df.index)
            if filtro_acordo == "Com acordo":
                df = df[tem_acordo]
            elif filtro_acordo == "Sem acordo":
                df = df[~tem_acordo]
        if filtro_grupo != "Todos" and "_grupo" in df.columns:
            df = df[df["_grupo"] == filtro_grupo]
        if filtro_situacao == "Ativos" and "_inativo" in df.columns:
            df = df[~df["_inativo"].fillna(False).astype(bool)]
        elif filtro_situacao == "Inativos" and "_inativo" in df.columns:
            df = df[df["_inativo"].fillna(False).astype(bool)]

    # ── Métricas (do df filtrado — reagem aos filtros em tempo real) ─────────
    # Cards separados por status pra cada um casar com o filtro do pill.
    # Antes 'Promessas' somava promise+negotiating, mas o filtro tem opções
    # distintas ('Prometeu pagar' vs 'Negociando') — gerava inconsistência.
    total = len(df)
    pending = contacted = promise = negotiating = 0
    if not df.empty:
        vc = df["_status"].value_counts()
        pending     = int(vc.get("pending", 0))
        contacted   = int(vc.get("contacted", 0))
        promise     = int(vc.get("promise", 0))
        negotiating = int(vc.get("negotiating", 0))

    # ── Variação no mês: novos inadimplentes (↑) vs regularizados (↓) ────────
    # Fonte preferida: snapshot diário (cobrancas_snapshot_diario). Quando
    # disponível, comparamos IDs do primeiro snapshot do mês com IDs atuais
    # — diferença exata. Sem snapshot, cai pra heurística.
    hoje       = date.today()
    mes_inicio = hoje.replace(day=1)
    ids_atuais = {str(c["id"]) for c in clientes}
    ids_inicio = fetch_snapshot_inicio_mes()

    # IDs que pagaram hoje via API Superlógica (overlay real-time). Lê do
    # store original — `clientes` aqui já tá filtrado, mas precisamos saber
    # quais foram tirados pra somar manualmente no edge case (cliente que
    # virou inadimplente no meio do mês — não estava no snapshot inicial).
    ids_pagos_hoje = {
        str(c["id"]) for c in store["clientes"] if c.get("_regularizado_hoje")
    }

    if ids_inicio:
        # NOVOS no mês — atuais que não estavam no 1º dia do mês.
        # Usa snapshot único do dia 01 (cliente "novo" = está agora E não
        # estava no início).
        novos_mes = len(ids_atuais - ids_inicio)

        # REGULARIZADOS no mês — UNIÃO de todos snapshots do mês.
        # Captura quem virou inadimplente NO MEIO do mês e regularizou
        # (que o método de 1 ponto perdia — Igreja Y vence 02/06 paga 03/06).
        ids_uniao_mes = fetch_inadimplentes_uniao_mes()
        reg_mes = len(ids_uniao_mes - ids_atuais) if ids_uniao_mes else len(ids_inicio - ids_atuais)
        # Edge case: pagou hoje mas snapshot de hoje ainda não rodou
        # (ou virou inad. e pagou no mesmo dia depois do snapshot).
        reg_mes += len(ids_pagos_hoje - ids_uniao_mes - ids_inicio)

        snapshot_dt = st.session_state.get("_snapshot_inicio_mes_data", "")
        variacao_sub = f"desde {snapshot_dt}" if snapshot_dt and not snapshot_dt.startswith("01/") else "no mês"
    else:
        # Fallback heurístico — usado enquanto o snapshot não foi populado
        ids_pagaram_em_atraso = fetch_regularizados_mes_atual()
        reg_mes               = len(ids_pagaram_em_atraso - ids_atuais)
        # Mesmo edge case no fallback (dedup contra ids_pagaram_em_atraso)
        reg_mes += len(ids_pagos_hoje - ids_pagaram_em_atraso)
        novos_mes = sum(
            1 for c in clientes
            if (vd := parse_date_br(c.get("vencimento", ""))) and mes_inicio <= vd <= hoje
        )
        variacao_sub = "no mês (aproximado)"
    saldo_mes = novos_mes - reg_mes

    s1, s2, s3, s4, s5, s6 = st.columns(6)
    for col, label, val, cor, sub in [
        (s1, "Total Clientes",       total,       "#e8eaf0", "filtro atual"),
        (s2, "Não Contactados",     pending,     "#ef4444", "nunca foi tocado"),
        (s3, "Contactados",         contacted,   "#f59e0b", "em acompanhamento"),
        (s4, "Promessas",           promise,     "#f97316", "prometeu pagar"),
        (s5, "Negociando",          negotiating, "#4f7cff", "em negociação"),
    ]:
        with col:
            st.markdown(
                f'<div class="metric-card" style="min-height:220px;padding:20px 18px;display:flex;flex-direction:column">'
                f'<div class="metric-label" style="font-size:12px">{label}</div>'
                f'<div class="metric-value" style="color:{cor};font-size:46px">{val:,}</div>'
                f'<div class="metric-sub" style="font-size:13px">{sub}</div></div>',
                unsafe_allow_html=True,
            )
    # 6º card: variação no mês (layout vertical com sub-linhas)
    with s6:
        sinal = "+" if saldo_mes >= 0 else ""
        cor_saldo = "#ef4444" if saldo_mes > 0 else ("#22c55e" if saldo_mes < 0 else "#e8eaf0")

        # Métricas do DIA — comparam snapshot de ontem com store atual.
        ids_ontem = fetch_snapshot_ontem()
        ids_atuais_set = ids_atuais
        regs_hoje_n = sum(
            1 for c in store.get("clientes", [])
            if c.get("_regularizado_hoje")
        )
        novos_hoje_n = len(ids_atuais_set - ids_ontem) if ids_ontem else None

        # Métricas da SEMANA (janela rolante 7d, união pra reg)
        ids_semana = fetch_snapshot_semana_passada()
        if ids_semana:
            novos_semana_n = len(ids_atuais_set - ids_semana)
            ids_uniao_semana = fetch_inadimplentes_uniao_semana()
            reg_semana_n   = len(ids_uniao_semana - ids_atuais_set) if ids_uniao_semana else len(ids_semana - ids_atuais_set)
            reg_semana_n  += len(ids_pagos_hoje - ids_uniao_semana - ids_semana)
        else:
            novos_semana_n = None
            reg_semana_n   = None

        # Helpers de formatação (sem setas, palavras inteiras, valores em
        # vermelho/verde inline com o label)
        def _fmt_v(n, kind):
            """kind: 'novos' (red) | 'reg' (green)"""
            cor = "#ef4444" if kind == "novos" else "#22c55e"
            if n is None:
                return f'<span style="color:#6b7280;font-weight:700">— {kind}</span>'
            label = "regularizados" if kind == "reg" else "novos"
            return f'<span style="color:{cor};font-weight:700">{n}</span> <span style="color:#8b94a5">{label}</span>'

        # Tooltips
        _tt_saldo = "Saldo = novos inadimplentes − regularizados. Negativo é bom (caiu)."
        _tt_mes   = "Período: do dia 01 do mês atual até agora."
        _tt_hoje  = "Comparado com snapshot de ontem (+ regularizações capturadas em tempo real)."
        _tt_7d    = "Janela rolante de 7 dias — pode cruzar fronteira de mês."

        st.markdown(
            f'<div class="metric-card" style="min-height:220px;padding:20px 18px;display:flex;flex-direction:column">'
            f'<div class="metric-label" style="font-size:12px">Variação {variacao_sub}</div>'
            f'<div title="{_tt_saldo}" style="cursor:help;display:flex;align-items:baseline;gap:8px;margin-top:4px">'
            f'<span class="metric-value" style="color:{cor_saldo};font-size:42px">{sinal}{saldo_mes:,}</span>'
            f'<span style="font-size:13px;color:#8b94a5;font-weight:600">inadimplentes</span>'
            f'</div>'
            f'<div title="{_tt_mes}" class="metric-sub" style="cursor:help;font-size:11px;margin-top:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
            f'<span style="color:#8b94a5">Mês: </span>'
            f'{_fmt_v(novos_mes, "novos")} · {_fmt_v(reg_mes, "reg")}'
            f'</div>'
            f'<div title="{_tt_hoje}" class="metric-sub" style="cursor:help;font-size:11px;margin-top:6px;padding-top:6px;border-top:1px solid #2a2f42;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
            f'<span style="color:#8b94a5">Hoje: </span>'
            f'{_fmt_v(novos_hoje_n, "novos")} · {_fmt_v(regs_hoje_n, "reg")}'
            f'</div>'
            f'<div title="{_tt_7d}" class="metric-sub" style="cursor:help;font-size:11px;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
            f'<span style="color:#8b94a5">Últimos 7 dias: </span>'
            f'{_fmt_v(novos_semana_n, "novos")} · {_fmt_v(reg_semana_n, "reg")}'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    # ── Clientes fixados ──────────────────────────────────────────────────────
    # Lista ordenada por dias_atraso DESC. Cor da borda reflete urgência.
    # Concluir agora vive dentro do dialog (botão Ver abre, ✅ Concluir fica lá).
    pendencias = calcular_pendencias(clientes)
    if pendencias:
        st.markdown("""
        <style>
        .pend-wrap .stButton > button {
            font-size:11px!important;
            padding:4px 8px!important;
            min-height:0!important;
            line-height:1.2!important;
        }
        </style>
        """, unsafe_allow_html=True)

        # Header — título + badge da contagem + filtro de atendente (admin)
        hcol, fcol = st.columns([3.4, 1.2])
        with hcol:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:14px;margin-bottom:6px">'
                f'<span style="font-weight:800;font-size:24px;color:#e8eaf0;'
                f'text-transform:uppercase;letter-spacing:1.5px;white-space:nowrap">'
                f'Clientes Fixados</span>'
                f'<span style="background:#ef4444;color:white;font-size:22px;padding:7px 18px;'
                f'border-radius:20px;font-weight:800;letter-spacing:0.3px;line-height:1">'
                f'{len(pendencias)}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        filtro_atend = "Todos"
        with fcol:
            if role in ("admin", "gestor"):
                from data import _EMAIL_GRUPO as _EG
                filtro_atend = st.selectbox(
                    "Grupo",
                    ["Todos"] + list(_EG.values()),
                    key="fix_filtro_atendente",
                    label_visibility="collapsed",
                )

        # Aplica filtro de atendente nas pendências
        if filtro_atend != "Todos":
            pendencias = [
                p for p in pendencias
                if filtro_atend in (p[1].get("_atendentes_origem") or [])
            ]

        if not pendencias:
            st.markdown(
                '<div style="color:#6b7280;font-size:13px;padding:14px 0">'
                'Nenhum fixado nesse filtro.</div>',
                unsafe_allow_html=True,
            )
        else:
            # Paginação: 5 cards por linha × 2 linhas = 10 por página
            CARDS_POR_LINHA = 5
            PAGE_SIZE_FIX   = 10
            total_fix    = len(pendencias)
            total_pg_fix = max(1, -(-total_fix // PAGE_SIZE_FIX))
            page_fix     = max(1, min(st.session_state.get("_fix_page", 1), total_pg_fix))
            inicio       = (page_fix - 1) * PAGE_SIZE_FIX
            fim          = inicio + PAGE_SIZE_FIX
            pend_pag     = pendencias[inicio:fim]

            st.markdown('<div class="pend-wrap">', unsafe_allow_html=True)
            cols_p = st.columns(min(CARDS_POR_LINHA, len(pend_pag)))
            # Ícone do botão adapta por role
            icone_btn = "✏" if role not in ("admin", "gestor") else "👁"
            help_btn  = "Atender" if role not in ("admin", "gestor") else "Ver detalhes"
            # Cor do card vem do STATUS efetivo da cobrança (não do prazo).
            # Promessa vencida normalmente vem com status='promise', mas o
            # cliente pode ter status='negotiating' com retorno vencido — daí
            # a cor reflete a fase real de cobrança.
            from config import STATUS_COLORS
            for i, (c, _h, tipo, msg, dias_atraso) in enumerate(pend_pag):
                status_c = _h.get("status", "pending")
                cor_borda = STATUS_COLORS.get(status_c, "#8b94a5")
                # Cor secundária pro 'há Xd' — vermelho intenso só pra muito
                # atrasado (≥7d); senão usa cinza neutro pra não competir
                # visualmente com a borda.
                cor_atraso = "#ef4444" if dias_atraso >= 7 else "#8b94a5"
                sufixo = "hoje" if dias_atraso == 0 else f"há {dias_atraso}d"

                # Telefones do cliente com ícones clicáveis (tel: + wa.me).
                # WhatsApp aparece pra QUALQUER fixado — atendente pode
                # precisar contatar por ambos os canais independente do tipo.
                tels = c.get("telefones") or ([c.get("telefone")] if c.get("telefone") else [])
                tels = [t for t in tels if t]
                if not tels:
                    tel_html = ""
                else:
                    if len(tels) == 1:
                        tels_text = tels[0]
                    else:
                        extras = " · ".join(tels[1:])
                        tels_text = (
                            f'{tels[0]} '
                            f'<span style="color:#6b7280;font-size:10px;font-weight:500">'
                            f'· {extras}</span>'
                        )
                    digits = _tel_only_digits(tels[0])
                    if digits:
                        tel_link = (
                            f'<a href="tel:+{digits}" style="text-decoration:none">'
                            f'{_ICON_FIX_PHONE}</a>'
                        )
                        wa_link = (
                            f'<a href="https://wa.me/{digits}" target="_blank" '
                            f'style="text-decoration:none;margin-left:4px">'
                            f'{_ICON_FIX_WHATSAPP}</a>'
                        )
                    else:
                        tel_link = _ICON_FIX_PHONE
                        wa_link  = _ICON_FIX_WHATSAPP
                    tel_html = (
                        f'<div style="display:flex;align-items:center;gap:5px;margin-top:6px;font-size:12px">'
                        f'{tel_link}{wa_link}'
                        f'<span style="color:#9ca3af;margin-left:2px">{tels_text}</span>'
                        f'</div>'
                    )

                origens = _h.get("_atendentes_origem") or []
                origem_tag = ""
                if origens and role in ("admin", "gestor"):
                    # Ícone de pessoa (mesmo SVG da tela Atividades) + nome
                    origem_tag = (
                        f'<div style="display:flex;align-items:center;gap:5px;'
                        f'margin-top:4px;font-size:11px;color:#9ca3af;font-weight:500">'
                        f'{_ICON_FIX_PERSON}<span>{" / ".join(origens)}</span>'
                        f'</div>'
                    )
                # Badge em CAIXA ALTA com 'há Xd' embutido — tudo na mesma
                # cor do status (sem vermelho conflitando). Diferenciação
                # sutil via opacity no 'há Xd'.
                bg_badge = _hex_to_rgba(cor_borda, 0.15)
                msg_badge = (
                    f'<span style="background:{bg_badge};color:{cor_borda};'
                    f'font-size:10px;font-weight:700;padding:3px 9px;'
                    f'border-radius:6px;display:inline-block;'
                    f'text-transform:uppercase;letter-spacing:0.5px">'
                    f'{msg} <span style="opacity:0.7">• {sufixo}</span>'
                    f'</span>'
                )
                # Grupo (igreja) com ícone — mesmo padrão dos cards de
                # Atividades. Pra atendente só (admin já vê origem '• Ana').
                grupo_html = ""
                if role not in ("admin", "gestor") and c.get("_grupo"):
                    grupo_html = (
                        f'<div style="display:flex;align-items:center;gap:5px;'
                        f'margin-top:4px;font-size:11px;color:#9ca3af">'
                        f'{_ICON_FIX_GROUP}<span>{c.get("_grupo", "—")}</span>'
                        f'</div>'
                    )

                # Tags ACORDO / INATIVO inline com o nome (à direita)
                tags_inline = ""
                if c.get("_tem_acordo"):
                    tags_inline += (
                        '<span style="background:#4f7cff;color:#fff;font-size:9px;'
                        'font-weight:700;padding:2px 6px;border-radius:4px;'
                        'flex-shrink:0">ACORDO</span>'
                    )
                if c.get("_inativo"):
                    tags_inline += (
                        '<span style="background:#6b7280;color:#fff;font-size:9px;'
                        'font-weight:700;padding:2px 6px;border-radius:4px;'
                        'flex-shrink:0;margin-left:4px">INATIVO</span>'
                    )
                # Layout flex pra nome (com ellipsis) + tags à direita
                nome_row = (
                    f'<div style="display:flex;align-items:center;gap:6px">'
                    f'<span style="font-weight:700;font-size:15px;overflow:hidden;'
                    f'text-overflow:ellipsis;white-space:nowrap;min-width:0;flex:1">'
                    f'{c["nome"]}</span>'
                    f'{tags_inline}'
                    f'</div>'
                )

                with cols_p[i % CARDS_POR_LINHA]:
                    st.markdown(
                        f'<div class="pend-card" style="border-left:4px solid {cor_borda}">'
                        f'{nome_row}'
                        f'<div style="margin-top:7px">{msg_badge}</div>'
                        f'<div style="font-size:15px;color:#ef4444;margin-top:7px;font-weight:700">{fmt_moeda_plain(c["valor"])}</div>'
                        f'{tel_html}'
                        f'{grupo_html}'
                        f'{origem_tag}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button(icone_btn, key=f"pend_atend_{i}_{c['id']}", width="stretch", help=help_btn):
                        dialog_editar(c["id"])
            st.markdown('</div>', unsafe_allow_html=True)

            # Paginação minimalista: só setas + indicador 'X / Y'.
            # vertical_alignment="center" alinha os 3 itens visualmente
            # (botão tem altura diferente do texto, sem isso fica torto).
            if total_pg_fix > 1:
                pc1, pc2, pc3, pc4, pc5 = st.columns(
                    [4, 0.5, 0.7, 0.5, 4], vertical_alignment="center"
                )
                with pc2:
                    if st.button("←", disabled=(page_fix <= 1),
                                 key="_fix_prev", help="Página anterior",
                                 width="stretch"):
                        st.session_state["_fix_page"] = page_fix - 1
                        st.rerun()
                with pc3:
                    st.markdown(
                        f'<div style="text-align:center;color:#6b7280;font-size:13px;font-weight:600">'
                        f'{page_fix} / {total_pg_fix}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                with pc4:
                    if st.button("→", disabled=(page_fix >= total_pg_fix),
                                 key="_fix_next", help="Próxima página",
                                 width="stretch"):
                        st.session_state["_fix_page"] = page_fix + 1
                        st.rerun()
        st.markdown("---")

    # ── Barra de ações ────────────────────────────────────────────────────────
    _, tb = st.columns([7, 1])
    with tb:
        # CSV exporta a base FILTRADA atual (consistente com o que aparece na tela)
        if not df.empty:
            sl   = {"pending": "Sem contato", "contacted": "Contactado", "promise": "Prometeu pagar", "negotiating": "Negociando", "paid": "Regularizado"}
            rows = []
            for _, c in df.iterrows():
                rows.append([
                    c.get("_grupo", "") or "", c["nome"], c.get("cnpj", ""), c["valor"],
                    c.get("parcelas", ""), c.get("vencimento", ""), c.get("dias_atraso", ""),
                    sl.get(c.get("_status", "pending"), ""), c.get("_lastContact", ""), c.get("_notes", ""),
                    "Sim" if c.get("_tem_acordo") else "Não",
                ])
            df_exp = pd.DataFrame(rows, columns=["Grupo","Nome","CNPJ","Saldo","Competências","Vencimento","Dias Atraso","Status","Último Contato","Observações","Acordo"])
            st.download_button(
                "⬇ CSV",
                df_exp.to_csv(index=False).encode("utf-8-sig"),
                f"cobrancas_{date.today()}.csv",
                "text/csv",
                width="stretch",
                help="Exportar lista filtrada",
            )

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── Filtros ───────────────────────────────────────────────────────────────
    pill_status = st.pills("Status", ["Todos", "Sem contato", "Contactado", "Prometeu pagar", "Negociando"], default="Todos", key="fpills")

    grupos_disp = sorted({c.get("_grupo", "—") for c in clientes if c.get("_grupo") and c.get("_grupo") not in ("—", "")})
    fc1, fc2, fc3, fc4, fc5, fc6 = st.columns([1.5, 1.6, 1.3, 1.4, 1.4, 1.3])
    with fc1:
        ordenar = st.selectbox("Ordenar por", list(SORT_MAP.keys()), key="fordenar")
    with fc2:
        filtro_grupo = st.selectbox("Grupo", ["Todos"] + grupos_disp, key="fgrupo")
    with fc3:
        filtro_situacao = st.selectbox("Situação", ["Todos", "Ativos", "Inativos"], key="fsituacao")
    with fc4:
        filtro_atraso = st.selectbox("Dias de atraso", ["Todos", "1-30 dias", "31-60 dias", "61-90 dias", "+90 dias"], key="fatraso")
    with fc5:
        filtro_valor = st.selectbox("Valor em aberto", ["Todos", "≤ R$500", "R$500–2k", "R$2k–5k", "> R$5k"], key="fvalor")
    with fc6:
        filtro_acordo = st.selectbox("Acordo", ["Todos", "Com acordo", "Sem acordo"], key="facordo")

    sb1, sb2 = st.columns([5, 1], vertical_alignment="bottom")
    with sb1:
        st.text_input("Buscar", placeholder="Buscar por nome do cliente, CNPJ ou código do sacado...", label_visibility="collapsed", key="busca")
    with sb2:
        st.button("✕ Limpar", on_click=_reset_filtros, width="stretch")

    if not clientes:
        st.info("Nenhum dado disponível. Aguarde o carregamento automático do BigQuery.")
        return

    # Ordenação (filtros já foram aplicados ao df no topo da função).
    sort_col_name, sort_asc = SORT_MAP[ordenar]
    if sort_col_name in df.columns:
        df = df.sort_values(sort_col_name, ascending=sort_asc, na_position="last")

    top10 = set(pd.DataFrame(clientes).nlargest(10, "valor")["id"].tolist())

    # ── Paginação ─────────────────────────────────────────────────────────────
    total_f  = len(df)
    total_pg = max(1, -(-total_f // PAGE_SIZE))
    if st.session_state.get("_prev_ord", "") != ordenar:
        st.session_state["page_num"] = 1
    st.session_state["_prev_ord"] = ordenar
    page    = max(1, min(st.session_state.get("page_num", 1), total_pg))
    df_page = df.iloc[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    sort_active = ordenar
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
        f'<span style="font-size:14px;color:#6b7280"><b style="color:#e8eaf0;font-size:15px">{total_f}</b> clientes encontrados</span>'
        f'<span style="font-size:11px;color:#4b5563;background:#181c26;border:1px solid #1e2333;padding:4px 10px;border-radius:6px">Ordenado por: <b style="color:#8b94a5">{sort_active}</b></span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Tabela ────────────────────────────────────────────────────────────────
    # Score: coluna dedicada com gradiente branco→cinza pra valores baixos,
    # laranja só pra score alto (>=150). Reduz ruído visual sem perder a info.
    has_edit = (role != "gestor")
    col_w    = [2.8, 1.1, 1.4, 1, 1, 1.5, 1.5, 1.5] + ([0.7] if has_edit else [])
    hdrs_t   = ["Cliente", "Score", "Saldo devedor", "Atraso em dias", "Histórico", "Telefone", "Grupo", "Último Contato"] + ([""] if has_edit else [])

    # Header usa st.columns (mesmo sistema das células) pra ficar alinhado.
    # Fundo escuro aplicado via container CSS abaixo.
    st.markdown(
        '<div style="background:#1e2333;border:1px solid #2a2f42;'
        'border-radius:12px 12px 0 0;padding:0;margin-bottom:0;'
        'box-shadow:0 2px 8px rgba(0,0,0,.1)">',
        unsafe_allow_html=True,
    )
    hdr_cols = st.columns(col_w, vertical_alignment="center")
    for hcol, htxt in zip(hdr_cols, hdrs_t):
        with hcol:
            st.markdown(
                f'<div style="padding:14px 14px;font-size:12px;text-transform:uppercase;'
                f'letter-spacing:1.2px;color:#8b94a5;font-weight:700;white-space:nowrap;'
                f'overflow:hidden;text-overflow:ellipsis">{htxt}</div>',
                unsafe_allow_html=True,
            )
    st.markdown('</div>', unsafe_allow_html=True)

    if df_page.empty:
        st.markdown(
            '<div style="background:#181c26;border:1px solid #2a2f42;border-top:none;'
            'border-radius:0 0 12px 12px;padding:60px;text-align:center;color:#6b7280;font-size:14px">'
            'Nenhum resultado — ajuste os filtros</div>',
            unsafe_allow_html=True,
        )
    else:
        n_rows = len(df_page)
        for ridx, (_, row) in enumerate(df_page.iterrows()):
            is_top = row["id"] in top10
            tags   = "".join([
                '<span class="top-badge">★ TOP</span>'               if is_top                    else "",
                '<span class="tag-novo">NOVO</span>'                 if row.get("_novo")          else "",
                '<span class="tag-upd">ATUALIZADO</span>'           if row.get("_atualizado")    else "",
                '<span class="tag-nova-cob">+ Nova cobrança</span>' if row.get("_nova_cobranca") else "",
                '<span style="background:#4f7cff;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:4px">ACORDO</span>'  if row.get("_tem_acordo") else "",
                '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:4px">INATIVO</span>' if row.get("_inativo")    else "",
            ])
            obs_icon  = ' <span style="color:#5fa3ff;font-size:12px;font-weight:700">●</span>' if str(row["_notes"] or "") else ""
            row_bl    = "border-left:4px solid rgba(239,68,68,.6);" if is_top else ""
            row_bg    = "background:rgba(239,68,68,.04);"           if is_top else ""

            rcols = st.columns(col_w, vertical_alignment="center")
            with rcols[0]:
                atend_tag = f'<span style="font-size:11px;color:#8b94a5;margin-left:4px;font-weight:500">· {row["_atendente"]}</span>' if row["_atendente"] else ""
                st.markdown(
                    f'<div style="padding:12px 12px;{row_bg}{row_bl}">'
                    f'<div style="margin-bottom:3px">{tags}</div>'
                    f'<div style="font-weight:600;font-size:18px;color:#e8eaf0;line-height:1.3">{row["nome"]}{obs_icon}</div>'
                    f'<div style="color:#8b94a5;font-size:15px;margin-top:2px;font-weight:500">{row.get("cnpj","")}{atend_tag}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with rcols[1]:
                # Gradiente relativo ao ranking, não ao valor: top 10% laranja,
                # resto interpola branco (top 10-90%) até cinza (baixo). Assim
                # scores muito altos (+2000) não distorcem a escala dos outros.
                _sc  = int(row.get("_score") or 0)
                _pct = float(row.get("_score_pct") or 0)  # 0..1, percentil na base
                if _pct >= 0.90:
                    cor_sc = "#f59e0b"  # top 10% — laranja
                else:
                    _ratio = _pct / 0.90  # 0..1 dentro dos 90% inferiores
                    _r1, _g1, _b1 = 0x6b, 0x72, 0x80  # cinza (low percentile)
                    _r2, _g2, _b2 = 0xe8, 0xea, 0xf0  # branco (high percentile)
                    _r = int(_r1 + (_r2 - _r1) * _ratio)
                    _g = int(_g1 + (_g2 - _g1) * _ratio)
                    _b = int(_b1 + (_b2 - _b1) * _ratio)
                    cor_sc = f"#{_r:02x}{_g:02x}{_b:02x}"
                st.markdown(
                    f'<div style="padding:12px 6px;text-align:center;white-space:nowrap">'
                    f'<span style="color:{cor_sc};font-weight:800;font-size:17px">{_sc}</span>'
                    f'<span style="color:#6b7280;font-size:10px;margin-left:3px">pts</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with rcols[2]:
                st.markdown(f'<div style="padding:12px 12px;font-size:17px;font-weight:600">{fmt_moeda(row["valor"])}</div>', unsafe_allow_html=True)
            with rcols[3]:
                st.markdown(f'<div style="padding:12px 12px;font-size:14px">{dias_html(row.get("dias_atraso"))}</div>', unsafe_allow_html=True)
            with rcols[4]:
                m = int(row.get("_meses_atraso") or 0)
                cor_m = "#ef4444" if m >= 9 else ("#f97316" if m >= 5 else "#f59e0b")
                st.markdown(
                    f'<div style="padding:12px 12px">'
                    f'<span style="color:{cor_m};font-weight:700;font-size:16px">{m}</span>'
                    f'<span style="color:#8b94a5;font-size:14px">/12</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with rcols[5]:
                # Telefones: primeiro destacado e os demais inline em fonte
                # menor — selecionáveis/copiáveis (sem tooltip não-copiável).
                tels = row.get("telefones") or []
                if not tels:
                    tel_display = row.get("telefone", "—") or "—"
                elif len(tels) == 1:
                    tel_display = tels[0]
                else:
                    extras_txt = " · ".join(tels[1:])
                    tel_display = (
                        f'{tels[0]} '
                        f'<span style="color:#6b7280;font-size:11px;font-weight:500">'
                        f'· {extras_txt}</span>'
                    )
                st.markdown(f'<div style="padding:12px 12px;font-size:16px;color:#8b94a5">{tel_display}</div>', unsafe_allow_html=True)
            with rcols[6]:
                st.markdown(f'<div style="padding:12px 12px;font-size:16px;color:#8b94a5">{row.get("_grupo","—")}</div>', unsafe_allow_html=True)
            with rcols[7]:
                st.markdown(f'<div style="padding:12px 12px;font-size:16px;color:#8b94a5">{row["_lastContact"] or "—"}</div>', unsafe_allow_html=True)
            if has_edit:
                with rcols[8]:
                    if st.button("✏", key=f"edit_{row['id']}_{ridx}", width="stretch", help=f"Editar {row['nome']}"):
                        dialog_editar(row["id"])

            if ridx < n_rows - 1:
                st.markdown('<div style="height:0.5px;background:#2a2f42;margin:0"></div>', unsafe_allow_html=True)

        st.markdown(
            f'<div style="background:#1e2333;border:1px solid #2a2f42;border-top:none;'
            f'border-radius:0 0 12px 12px;padding:12px 16px;display:flex;'
            f'justify-content:space-between;font-size:13px;color:#8b94a5;font-weight:500;box-shadow:0 2px 8px rgba(0,0,0,.1)">'
            f'<span>Mostrando {(page-1)*PAGE_SIZE+1}–{min(page*PAGE_SIZE,total_f)} de {total_f}</span>'
            f'<span>Página {page} de {total_pg}</span></div>',
            unsafe_allow_html=True,
        )

    if total_pg > 1:
        st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)
        pc1, pc2, pc3 = st.columns([1, 2, 1])
        with pc1:
            if st.button("← Anterior", disabled=(page <= 1), width="stretch"):
                st.session_state["page_num"] = page - 1
                st.rerun()
        with pc2:
            st.markdown(f'<div style="text-align:center;color:#6b7280;font-size:12px;padding-top:6px">Página {page} de {total_pg}</div>', unsafe_allow_html=True)
        with pc3:
            if st.button("Próxima →", disabled=(page >= total_pg), width="stretch"):
                st.session_state["page_num"] = page + 1
                st.rerun()

