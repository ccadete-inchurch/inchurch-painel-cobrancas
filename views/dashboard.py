from datetime import date, datetime

import re

import pandas as pd
import streamlit as st

from config import SORT_MAP, STATUS_FILTER_MAP, STATUS_LABELS, PAGE_SIZE, token
from helpers import get_hist, get_hist_unificado, fmt_moeda, fmt_moeda_plain, dias_html, get_effective_status, get_effective_lastContact, get_ultimo_login, get_effective_atendente, parse_date_br, telefone_wa_link, telefones_cliente, telefones_texto, carimbo_dia_cache
from data import calcular_pendencias, fetch_regularizados_mes_atual, fetch_snapshot_inicio_mes, fetch_snapshot_ontem, fetch_snapshot_inicio_semana, fetch_inadimplentes_uniao_mes, fetch_inadimplentes_uniao_esta_semana
import re as _re_tel


# Ícones monocromáticos pros cards de fixado (mesmo padrão da Atividades)
_ICON_FIX_PHONE = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="var(--txt-3)" '
    'style="flex-shrink:0;vertical-align:middle">'
    '<path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 '
    '2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 '
    '1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z"/>'
    '</svg>'
)
_ICON_FIX_GROUP = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="var(--txt-3)" '
    'style="flex-shrink:0;vertical-align:middle">'
    '<path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 '
    '3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 '
    '8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5z'
    'm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33'
    '-4.67-3.5-7-3.5z"/>'
    '</svg>'
)
_ICON_FIX_PERSON = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="var(--txt-3)" '
    'style="flex-shrink:0;vertical-align:middle">'
    '<path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 '
    '2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>'
    '</svg>'
)
_ICON_FIX_WHATSAPP = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="var(--txt-3)" '
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


def _eh_fixo(tel: str) -> bool:
    """Fixo BR = 55 + DDD(2) + 8 digitos = 12. Celular = 55 + DDD(2) + 9 = 13
    (o nono digito). Numero internacional nao da' pra classificar por tamanho,
    entao cai no else e assume celular — que e' o palpite util aqui (WhatsApp).
    """
    d = _tel_only_digits(tel)
    return d.startswith("55") and len(d) == 12


def _hex_to_rgba(hex_color: str, alpha: float = 0.15) -> str:
    """Converte cor hex (#rrggbb) pra rgba pra background tintado de badge.

    O alfa sai multiplicado pelo --tint-k, igual aos tints escritos no CSS:
    um veu de 15% aparece sobre fundo escuro e vira lavagem sobre branco.
    Este e o unico tint montado em tempo de execucao — a cor vem do status do
    cliente, entao nao da pra tokenizar como os outros.
    """
    h = hex_color.lstrip("#")
    _a = f"calc({alpha} * var(--tint-k))"
    if len(h) != 6:
        return f"rgba(var(--txt-4-rgb),{_a})"
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{_a})"
    except ValueError:
        return f"rgba(var(--txt-4-rgb),{_a})"
from views.dialog import dialog_editar


def _reset_filtros():
    st.session_state["fpills"]    = "Todos"
    st.session_state["fordenar"]  = []
    st.session_state["fgrupo"]    = []
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
    filtro_grupo    = st.session_state.get("fgrupo",    []) or []
    filtro_situacao = st.session_state.get("fsituacao", "Todos")
    filtro_atraso   = st.session_state.get("fatraso",   "Todos")
    filtro_valor    = st.session_state.get("fvalor",    "Todos")
    filtro_acordo   = st.session_state.get("facordo",   "Todos")
    ordenar         = st.session_state.get("fordenar", []) or []

    # ── Constrói df e aplica filtros (compartilhado: métricas, tabela, CSV) ──
    df = pd.DataFrame(clientes)
    if not df.empty:
        df["_status"]      = df["id"].apply(get_effective_status)
        df["_lastContact"] = df["id"].apply(get_effective_lastContact)
        # Ultimo login no painel de controle. Guarda o rotulo (exibicao) e a
        # ordem (int) separados: ordenar pelo texto sairia alfabetico — "9d"
        # depois de "372d".
        _ul = df["id"].apply(get_ultimo_login)
        df["_ultimoLogin"]      = _ul.apply(lambda r: r["curto"])
        df["_ultimoLoginOrdem"] = _ul.apply(lambda r: r["ordem"])
        # Dias e data crus vao pro CSV: numero ordena/filtra em planilha, o
        # rotulo curto ("+853d", "—") nao.
        df["_ultimoLoginDias"]  = _ul.apply(lambda r: r["dias"])
        df["_ultimoLoginData"]  = _ul.apply(lambda r: r["data"])
        df["_atendente"]   = df["id"].apply(get_effective_atendente)
        df["_notes"]       = df["id"].apply(lambda i: get_hist(i).get("notes", ""))
        # get_hist_unificado une historicos das atendentes pro admin —
        # get_hist (proprio uid) sempre voltava vazio pro admin e o badge
        # 'TELEFONE FIXO' nunca aparecia mesmo em clientes que Ana ou
        # Priscila marcaram.
        df["_tel_fixo"]    = df["id"].apply(lambda i: bool(get_hist_unificado(i).get("tel_fixo")))
        from data import calcular_score
        df["_score"]       = df.apply(lambda r: calcular_score(r.to_dict(), get_hist(r["id"])), axis=1)
        df["_score_pct"]   = df["_score"].rank(pct=True, method="max").fillna(0)

        if busca:
            b = busca.lower()
            mask = df.apply(lambda r: b in str(r.get("nome", "")).lower() or b in str(r.get("cnpj", "")).lower() or b in str(r.get("id", "")).lower(), axis=1)
            df = df[mask]
        if filtro_status == "Telefone fixo":
            df = df[df["_tel_fixo"].fillna(False).astype(bool)] if "_tel_fixo" in df.columns else df.iloc[0:0]
        elif filtro_status != "Todos":
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
        if filtro_grupo and "_grupo" in df.columns:
            # Multi-select: lista de grupos escolhidos. Vazio = todos (sem filtro).
            # "Sem especialista" e' pseudo-grupo pra clientes sem atribuicao.
            _sem_esp_sel = "Sem especialista" in filtro_grupo
            _grupos_sel = [g for g in filtro_grupo if g != "Sem especialista"]
            _grupo_norm = df["_grupo"].fillna("").astype(str)
            _mask_sem_esp = _grupo_norm.isin(["", "—", "nan", "NaN"]) if _sem_esp_sel else pd.Series(False, index=df.index)
            _mask_grupos = _grupo_norm.isin(_grupos_sel) if _grupos_sel else pd.Series(False, index=df.index)
            df = df[_mask_sem_esp | _mask_grupos]
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
    ids_inicio = fetch_snapshot_inicio_mes(dia=carimbo_dia_cache())

    # IDs que pagaram hoje via API Superlógica (overlay real-time). Lê do
    # store original — `clientes` aqui já tá filtrado, mas precisamos saber
    # quais foram tirados pra somar manualmente no edge case (cliente que
    # virou inadimplente no meio do mês — não estava no snapshot inicial).
    ids_pagos_hoje = {
        str(c["id"]) for c in store["clientes"] if c.get("_regularizado_hoje")
    }

    if ids_inicio:
        # MATEMÁTICA SIMÉTRICA com UNIÃO em ambos novos e reg.
        # Captura transients (clientes que entraram E saíram no mesmo mês,
        # tipo Igreja Y vence 02/06 paga 03/06) E mantém saldo = delta real.
        #
        # Demonstração: pra cada cliente
        #   Transient:        novos +1, reg +1  → saldo 0     ✓
        #   Permanente novo:  novos +1, reg 0   → saldo +1    ✓
        #   Permanente saiu:  novos 0,  reg +1  → saldo -1    ✓
        #   Estável:          novos 0,  reg 0   → saldo 0     ✓
        # Soma: saldo = |atuais| − |inicio| = delta real ✓
        ids_uniao_mes = fetch_inadimplentes_uniao_mes(dia=carimbo_dia_cache())
        if ids_uniao_mes:
            novos_mes = len(ids_uniao_mes - ids_inicio)
            reg_mes   = len(ids_uniao_mes - ids_atuais)
        else:
            # Fallback: sem união disponível, usa simples
            novos_mes = len(ids_atuais - ids_inicio)
            reg_mes   = len(ids_inicio - ids_atuais)
        # Edge case: pagamentos via overlay HOJE de clientes que ainda
        # não estavam em nenhum snapshot do mês (virou inad e regularizou
        # hoje mesmo, antes de qualquer snapshot capturar). Adiciona em
        # AMBOS pra preservar simetria (saldo += 0).
        _orfãos = ids_pagos_hoje - (ids_uniao_mes or set()) - ids_inicio - ids_atuais
        novos_mes += len(_orfãos)
        reg_mes   += len(_orfãos)

        snapshot_dt = st.session_state.get("_snapshot_inicio_mes_data", "")
        variacao_sub = f"desde {snapshot_dt}" if snapshot_dt and not snapshot_dt.startswith("01/") else "no mês"
    else:
        # Fallback heurístico — usado enquanto o snapshot não foi populado
        ids_pagaram_em_atraso = fetch_regularizados_mes_atual(dia=carimbo_dia_cache())
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
        (s1, "Total Clientes",       total,       "var(--txt)", "inadimplentes"),
        (s2, "Não Contactados",     pending,     "var(--erro)", "pendentes"),
        (s3, "Contactados",         contacted,   "var(--alerta)", "em acompanhamento"),
        (s4, "Promessas",           promise,     "var(--laranja-3)", "prometeu pagar"),
        (s5, "Negociando",          negotiating, "var(--azul-2)", "em negociação"),
    ]:
        with col:
            st.markdown(
                f'<div class="metric-card" style="min-height:220px;padding:20px 18px;display:flex;flex-direction:column">'
                f'<div class="metric-label" style="font-size:13px">{label}</div>'
                f'<div class="metric-value" style="color:{cor};font-size:46px">{val:,}</div>'
                f'<div class="metric-sub" style="font-size:15px">{sub}</div></div>',
                unsafe_allow_html=True,
            )
    # 6º card: variação no mês (layout vertical com sub-linhas)
    with s6:
        sinal = "+" if saldo_mes >= 0 else ""
        cor_saldo = "var(--erro)" if saldo_mes > 0 else ("var(--ok)" if saldo_mes < 0 else "var(--txt)")

        # Métricas do DIA — JANELA ÚNICA do snapshot de referência (sex em
        # segundas, ontem em dias normais) até agora. Antes havia incoerência:
        # novos vinham de diff snapshot (3 dias na segunda), reg vinha só do
        # overlay (1 dia). Agora ambos usam a mesma janela.
        ids_ontem = fetch_snapshot_ontem(dia=carimbo_dia_cache())
        ids_atuais_set = ids_atuais
        if ids_ontem:
            # Quem ENTROU desde o snapshot de referência
            novos_hoje_n = len(ids_atuais_set - ids_ontem)
            # Quem SAIU desde o snapshot de referência
            regs_hoje_n = len(ids_ontem - ids_atuais_set)
            # Edge case: pagamento via overlay HOJE de cliente que nem
            # estava no snapshot (virou inad sáb/dom e regularizou hoje).
            # Soma com dedup pra não contar 2x.
            regs_hoje_n += len(ids_pagos_hoje - ids_ontem - ids_atuais_set)
        else:
            novos_hoje_n = None
            # Fallback: sem snapshot de referência, usa só overlay (hoje)
            regs_hoje_n = sum(
                1 for c in store.get("clientes", [])
                if c.get("_regularizado_hoje")
            )

        # Métricas de ESTA SEMANA (seg → hoje, cap no início do mês).
        # Garante que Esta semana ⊆ Mês sempre. Quando dia 1 do mês cai
        # no meio da semana, baseline é capada — Esta semana coincide
        # com Mês até a próxima segunda.
        ids_semana = fetch_snapshot_inicio_semana(dia=carimbo_dia_cache())
        if ids_semana:
            novos_semana_n = len(ids_atuais_set - ids_semana)
            ids_uniao_semana = fetch_inadimplentes_uniao_esta_semana(dia=carimbo_dia_cache())
            reg_semana_n   = len(ids_uniao_semana - ids_atuais_set) if ids_uniao_semana else len(ids_semana - ids_atuais_set)
            reg_semana_n  += len(ids_pagos_hoje - ids_uniao_semana - ids_semana)
        else:
            novos_semana_n = None
            reg_semana_n   = None

        # Helpers de formatação. Primeira linha (Mês) tem label completo
        # 'novos'/'reg.'. Linhas seguintes só seta + número.
        # 'reg.' abreviado pra caber no card (era cortado em telas estreitas).
        def _fmt_full(n, kind):
            """Com seta + número + label ('↑ 8 novos' / '↓ 59 reg.')"""
            seta = "↑" if kind == "novos" else "↓"
            cor = "var(--erro)" if kind == "novos" else "var(--ok)"
            label = "reg." if kind == "reg" else "novos"
            if n is None:
                return f'<span style="color:var(--txt-3);font-weight:700">{seta} —</span> <span style="color:var(--txt-2)">{label}</span>'
            return f'<span style="color:{cor};font-weight:700">{seta} {n}</span> <span style="color:var(--txt-2)">{label}</span>'

        def _fmt_short(n, kind):
            """Seta + número colorido ('↑ 8' / '↓ 59')"""
            seta = "↑" if kind == "novos" else "↓"
            cor = "var(--erro)" if kind == "novos" else "var(--ok)"
            if n is None:
                return f'<span style="color:var(--txt-3);font-weight:700">{seta} —</span>'
            return f'<span style="color:{cor};font-weight:700">{seta} {n}</span>'

        # Tooltips — curtos e diretos
        _tt_saldo = "Variação líquida da carteira no mês."
        _tt_mes   = "Acumulado desde o dia 01."
        # Label dinâmico do "Hoje" — adapta quando snapshot de referência
        # não é literalmente de ontem (ex: segunda compara com sexta).
        _ontem_data = st.session_state.get("_snapshot_ontem_data", "")
        _hoje_dt = date.today()
        _label_hoje = "Hoje"
        if _ontem_data:
            try:
                _ref_dt = datetime.strptime(_ontem_data, "%d/%m/%Y").date()
                _dias_gap = (_hoje_dt - _ref_dt).days
                if _dias_gap > 1:
                    _ref_curta = _ref_dt.strftime("%d/%m")
                    _label_hoje = f"Desde {_ref_curta}"
            except Exception:
                pass
        _tt_hoje = f"Comparado com snapshot de {_ontem_data}." if _ontem_data else "Período curto."
        _tt_sem  = "Da segunda da semana atual."

        # Sem label depois do número — cor (vermelho/verde/branco) e o
        # sinal +/- já comunicam a direção. Título 'Variação no mês' diz
        # do que se trata. Menos é mais.
        st.markdown(
            f'<div class="metric-card" style="min-height:220px;padding:20px 18px;display:flex;flex-direction:column">'
            f'<div class="metric-label" style="font-size:13px">Variação {variacao_sub}</div>'
            f'<div title="{_tt_saldo}" style="cursor:help;margin-top:4px">'
            f'<span class="metric-value" style="color:{cor_saldo};font-size:42px">{sinal}{saldo_mes:,}</span>'
            f'</div>'
            f'<div title="{_tt_mes}" class="metric-sub" style="cursor:help;font-size:11px;margin-top:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
            f'<span style="color:var(--txt-2)">Mês: </span>'
            f'{_fmt_full(novos_mes, "novos")} · {_fmt_full(reg_mes, "reg")}'
            f'</div>'
            f'<div title="{_tt_sem}" class="metric-sub" style="cursor:help;font-size:11px;margin-top:6px;padding-top:6px;border-top:1px solid var(--border);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
            f'<span style="color:var(--txt-2)">Semana: </span>'
            f'{_fmt_short(novos_semana_n, "novos")} · {_fmt_short(reg_semana_n, "reg")}'
            f'</div>'
            f'<div title="{_tt_hoje}" class="metric-sub" style="cursor:help;font-size:11px;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
            f'<span style="color:var(--txt-2)">{_label_hoje}: </span>'
            f'{_fmt_short(novos_hoje_n, "novos")} · {_fmt_short(regs_hoje_n, "reg")}'
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

        # Header — título + badge da contagem
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:14px;margin-bottom:6px">'
            f'<span style="font-weight:800;font-size:24px;color:var(--txt);'
            f'text-transform:uppercase;letter-spacing:1.5px;white-space:nowrap">'
            f'Clientes Fixados</span>'
            f'<span style="background:var(--erro);color:white;font-size:22px;padding:7px 18px;'
            f'border-radius:20px;font-weight:800;letter-spacing:0.3px;line-height:1">'
            f'{len(pendencias)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if not pendencias:
            st.markdown(
                '<div style="color:var(--txt-3);font-size:13px;padding:14px 0">'
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
            icone_btn = "✏" if role != "admin" else "👁"
            help_btn  = "Atender" if role != "admin" else "Ver detalhes"
            # Cor do card vem do STATUS efetivo da cobrança (não do prazo).
            # Promessa vencida normalmente vem com status='promise', mas o
            # cliente pode ter status='negotiating' com retorno vencido — daí
            # a cor reflete a fase real de cobrança.
            from config import STATUS_COLORS
            for i, (c, _h, tipo, msg, dias_atraso) in enumerate(pend_pag):
                status_c = _h.get("status", "pending")
                cor_borda = STATUS_COLORS.get(status_c, "var(--txt-2)")
                # Cor secundária pro 'há Xd' — vermelho intenso só pra muito
                # atrasado (≥7d); senão usa cinza neutro pra não competir
                # visualmente com a borda.
                sufixo = "hoje" if dias_atraso == 0 else f"há {dias_atraso}d"

                # Telefones do cliente: 1 icone WhatsApp por numero, cada um
                # linkando pro proprio wa.me. telefones_cliente descarta o que
                # nao chega a ser telefone, tira o repetido por DIGITO (o mesmo
                # numero vem escrito de formas diferentes nos 4 campos do
                # cadastro) e marca o que nao da pra discar.
                _raw_tels_fix = c.get("telefones") or ([c.get("telefone")] if c.get("telefone") else [])
                _itens_fix = telefones_cliente(_raw_tels_fix)
                if not _itens_fix:
                    tel_html = ""
                else:
                    def _wa_por_tel(t: str) -> str:
                        wa_num = telefone_wa_link(t)
                        if not wa_num:
                            return ""
                        return (
                            f'<a href="https://wa.me/{wa_num}" target="_blank" '
                            f'style="text-decoration:none;margin-right:3px;vertical-align:middle">'
                            f'{_ICON_FIX_WHATSAPP}</a>'
                        )
                    # numero que existe no cadastro mas nao da pra discar sai
                    # em vermelho e sem icone de WhatsApp; os bons vem antes,
                    # pra que o destaque nunca seja um numero furado.
                    _ps = [f'{_wa_por_tel(_b)}{_f}' for _b, _f, _p in _itens_fix if not _p]
                    _ps += [f'<span style="color:var(--erro)" title="cadastro '
                            f'incompleto — {_p}">{_f}</span>'
                            for _b, _f, _p in _itens_fix if _p]
                    if len(_ps) == 1:
                        conteudo = _ps[0]
                    else:
                        conteudo = (
                            f'{_ps[0]} '
                            f'<span style="color:var(--txt-3);font-size:10px;font-weight:500">'
                            f'· {" · ".join(_ps[1:])}</span>'
                        )
                    tel_html = (
                        f'<div style="display:flex;align-items:center;gap:5px;margin-top:6px;font-size:12px">'
                        f'{_ICON_FIX_PHONE}'
                        f'<span style="color:var(--txt-2);margin-left:2px">{conteudo}</span>'
                        f'</div>'
                    )

                origens = _h.get("_atendentes_origem") or []
                origem_tag = ""
                if origens and role == "admin":
                    # Ícone de pessoa (mesmo SVG da tela Atividades) + nome
                    origem_tag = (
                        f'<div style="display:flex;align-items:center;gap:5px;'
                        f'margin-top:4px;font-size:11px;color:var(--txt-2);font-weight:500">'
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
                _g = c.get("_grupo") or ""
                _g_display = _g if _g and _g not in ("nan", "NaN", "—") else "Sem especialista"
                if role != "admin" and c.get("_grupo"):
                    grupo_html = (
                        f'<div style="display:flex;align-items:center;gap:5px;'
                        f'margin-top:4px;font-size:11px;color:var(--txt-2)">'
                        f'{_ICON_FIX_GROUP}<span>{_g_display}</span>'
                        f'</div>'
                    )

                # Tags ACORDO / INATIVO inline com o nome (à direita)
                tags_inline = ""
                if c.get("_tem_acordo"):
                    tags_inline += (
                        '<span style="background:var(--azul-2);color:var(--txt-inv);font-size:9px;'
                        'font-weight:700;padding:2px 6px;border-radius:4px;'
                        'flex-shrink:0">ACORDO</span>'
                    )
                if c.get("_inativo"):
                    tags_inline += (
                        '<span style="background:var(--txt-3);color:var(--txt-inv);font-size:9px;'
                        'font-weight:700;padding:2px 6px;border-radius:4px;'
                        'flex-shrink:0;margin-left:4px">INATIVO</span>'
                    )
                if _h.get("tel_fixo"):
                    tags_inline += (
                        '<span style="background:rgba(var(--rosa-v),calc(.18 * var(--tint-k)));color:var(--rosa);'
                        'border:1px solid rgba(var(--rosa-v),.4);'
                        'font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;'
                        'flex-shrink:0;margin-left:4px">TELEFONE FIXO</span>'
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
                        f'<div style="font-size:15px;color:var(--erro);margin-top:7px;font-weight:700">{fmt_moeda_plain(c["valor"])}</div>'
                        f'{tel_html}'
                        f'{grupo_html}'
                        f'{origem_tag}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    if st.button(icone_btn, key=f"pend_atend_{i}_{c['id']}", width="stretch", help=help_btn):
                        dialog_editar(c["id"], from_fixados=True)
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
                        f'<div style="text-align:center;color:var(--txt-3);font-size:13px;font-weight:600">'
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
            # Usa STATUS_LABELS direto pra reutilizar a fonte canonica
            # (inclui automaticamente 'Telefone errado' e 'Igreja fechada')
            # Colunas novas entram DEPOIS das antigas: planilha que ja usa o
            # arquivo continua lendo as mesmas posicoes.
            def _fmt_data_br(v):
                # BQ devolve YYYY-MM-DD; planilha do time le dd/mm/aaaa.
                v = str(v or "")
                return f"{v[8:10]}/{v[5:7]}/{v[0:4]}" if len(v) >= 10 else ""

            def _fmt_doc(v):
                # CNPJ/CPF com mascara: sem ela o Excel le como numero e come
                # o zero a esquerda (CNPJ 01.234.../CPF 012...).
                d = re.sub(r"\D", "", str(v or ""))
                if len(d) == 14:
                    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
                if len(d) == 11:
                    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
                return str(v or "")

            def _fmt_num(v, casas=0):
                # Decimal com virgula (planilha pt-BR) e sem separador de
                # milhar, pra entrar como numero e nao como texto.
                try:
                    if v is None or v == "":
                        return ""
                    return f"{float(v):.{casas}f}".replace(".", ",")
                except (TypeError, ValueError):
                    return ""

            rows = []
            for _, c in df.iterrows():
                _dt_login = c.get("_ultimoLoginData")
                rows.append([
                    c.get("_grupo", "") or "", c["nome"], _fmt_doc(c.get("cnpj", "")), _fmt_num(c["valor"], 2),
                    _fmt_num(c.get("parcelas")), c.get("vencimento", ""), _fmt_num(c.get("dias_atraso")),
                    STATUS_LABELS.get(c.get("_status", "pending"), ""), c.get("_lastContact", ""), c.get("_notes", ""),
                    "Sim" if c.get("_tem_acordo") else "Não",
                    str(c.get("id", "") or ""), c.get("_atendente", "") or "",
                    telefones_texto(c.get("telefones") or c.get("telefone")),
                    "Sim" if c.get("_tel_fixo") else "Não",
                    "Inativo" if c.get("_inativo") else "Ativo",
                    _fmt_data_br(c.get("_dt_desativacao")),
                    _fmt_num(c.get("_score")),
                    _fmt_num(c.get("_ultimoLoginDias")),
                    _dt_login.strftime("%d/%m/%Y") if hasattr(_dt_login, "strftime") else (_dt_login or ""),
                    _fmt_num(c.get("_meses_atraso") or 0),
                ])
            df_exp = pd.DataFrame(rows, columns=[
                "Grupo","Nome","CNPJ","Saldo","Competências","Vencimento","Dias Atraso","Status",
                "Último Contato","Observações","Acordo",
                "ID","Especialista","Telefone","Telefone fixo","Situação","Data desativação","Score",
                "Dias sem login","Data último login","Meses com atraso",
            ])
            st.download_button(
                "⬇ CSV",
                df_exp.to_csv(index=False, sep=";").encode("utf-8-sig"),
                f"cobrancas_{date.today()}.csv",
                "text/csv",
                width="stretch",
                help="Exportar lista filtrada",
            )

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── Filtros ───────────────────────────────────────────────────────────────
    # Le opcoes de STATUS_FILTER_MAP (config.py) e injeta 'Telefone fixo'
    # antes de 'Telefone errado' como filtro derivado (nao vem de _status,
    # vem da flag _tel_fixo).
    _pill_opts = list(STATUS_FILTER_MAP.keys())
    if "Telefone errado" in _pill_opts:
        _pill_opts.insert(_pill_opts.index("Telefone errado"), "Telefone fixo")
    else:
        _pill_opts.append("Telefone fixo")
    st.pills(
        "Status",
        ["Todos"] + _pill_opts,
        default="Todos",
        key="fpills",
    )

    # 'nan' (string) cai aqui quando _grupo veio de pandas com NaN convertido
    # via str() em algum ponto do pipeline. Trata junto com None, '—' e ''
    # como ausência de grupo.
    grupos_disp = sorted({
        c.get("_grupo", "—") for c in clientes
        if c.get("_grupo") and c.get("_grupo") not in ("—", "", "nan", "NaN")
    })
    # Tem cliente sem grupo? Adiciona opção 'Sem especialista' no filtro.
    _tem_sem_grupo = any(
        not c.get("_grupo") or c.get("_grupo") in ("—", "", "nan", "NaN")
        for c in clientes
    )
    fc1, fc2, fc3, fc4, fc5, fc6 = st.columns([2.2, 1.7, 1.15, 1.3, 1.3, 1.15])
    with fc1:
        # Multiselect (e nao selectbox) pra permitir ordenacao combinada:
        # a ordem de selecao vira a ordem dos criterios — 1o desempata pelo
        # 2o, e assim por diante.
        ordenar = st.multiselect(
            "Ordenar por",
            list(SORT_MAP.keys()),
            key="fordenar",
            placeholder="Padrão",
        )
    with fc2:
        filtro_grupo = st.multiselect(
            "Grupo",
            grupos_disp + (["Sem especialista"] if _tem_sem_grupo else []),
            key="fgrupo",
            placeholder="Todos",
        )
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

    # Ordenação combinada (filtros já foram aplicados ao df no topo da função).
    # Cada critério escolhido entra como uma coluna do sort, na ordem em que
    # foi selecionado. Se o usuário marcar ↑ e ↓ do MESMO campo, vale o
    # primeiro — senão o pandas recebe a coluna duplicada e a segunda direção
    # nunca teria efeito de qualquer forma.
    _cols, _ascs, _vistas = [], [], set()
    for _o in ordenar:
        _c, _a = SORT_MAP[_o]
        if _c in _vistas or _c not in df.columns:
            continue
        _vistas.add(_c)
        _cols.append(_c)
        _ascs.append(_a)
    if _cols:
        df = df.sort_values(_cols, ascending=_ascs, na_position="last")

    top10 = set(pd.DataFrame(clientes).nlargest(10, "valor")["id"].tolist())

    # ── Paginação ─────────────────────────────────────────────────────────────
    total_f  = len(df)
    total_pg = max(1, -(-total_f // PAGE_SIZE))
    if st.session_state.get("_prev_ord", "") != ordenar:
        st.session_state["page_num"] = 1
    st.session_state["_prev_ord"] = ordenar
    page    = max(1, min(st.session_state.get("page_num", 1), total_pg))
    df_page = df.iloc[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    sort_active = " · ".join(ordenar) if ordenar else "padrão"
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
        f'<span style="font-size:14px;color:var(--txt-3)"><b style="color:var(--txt);font-size:15px">{total_f}</b> clientes encontrados</span>'
        f'<span style="font-size:11px;color:var(--txt-4);background:var(--surface);border:1px solid var(--border-card);padding:4px 10px;border-radius:6px">Ordenado por: <b style="color:var(--txt-2)">{sort_active}</b></span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Tabela ────────────────────────────────────────────────────────────────
    # Score: coluna dedicada com gradiente branco→cinza pra valores baixos,
    # laranja só pra score alto (>=150). Reduz ruído visual sem perder a info.
    # "Login" (e nao "Últ. login") de proposito: o header e' o que estica a
    # coluna, nao o valor — os valores sao curtos ("5d", "372d", "—").
    #
    # A coluna nova NAO foi paga com aperto geral: medido em 1366px, so'
    # acrescentar 0.9 truncava o header "Histórico" e quebrava Telefone,
    # Grupo e Saldo em duas linhas. O espaco sai de Cliente (que quebra
    # linha de qualquer jeito) e de Últ. contato (data cabe em 1.1). A soma
    # caiu de 12.5 pra 12.35, entao nada ficou mais apertado que hoje.
    col_w    = [2.75, 0.95, 1.5, 1.05, 1.4, 1.35, 1.15, 1.3, 1.0, 0.55]
    hdrs_t   = ["Cliente", "Score", "Saldo", "Atraso", "Hist.", "Telefone", "Grupo", "Últ. ctt", "Login", ""]

    # Header usa st.columns (mesmo sistema das células) pra ficar alinhado.
    # Fundo escuro aplicado via container CSS abaixo.
    st.markdown(
        '<div style="background:var(--faixa);border:1px solid var(--border);'
        'border-radius:12px 12px 0 0;padding:0;margin-bottom:0;'
        'box-shadow:var(--sombra-tabela)">',
        unsafe_allow_html=True,
    )
    hdr_cols = st.columns(col_w, vertical_alignment="center")
    for hcol, htxt in zip(hdr_cols, hdrs_t):
        with hcol:
            st.markdown(
                f'<div style="padding:14px 14px;font-size:12px;text-transform:uppercase;'
                f'letter-spacing:1.2px;color:var(--txt-2);font-weight:700;white-space:nowrap;'
                f'overflow:hidden;text-overflow:ellipsis">{htxt}</div>',
                unsafe_allow_html=True,
            )
    st.markdown('</div>', unsafe_allow_html=True)

    if df_page.empty:
        st.markdown(
            '<div style="background:var(--surface);border:1px solid var(--border);border-top:none;'
            'border-radius:0 0 12px 12px;padding:60px;text-align:center;color:var(--txt-3);font-size:14px">'
            'Nenhum resultado — ajuste os filtros</div>',
            unsafe_allow_html=True,
        )
    else:
        n_rows = len(df_page)
        # Extremos do gradiente do Score. Eles estavam escritos na mao com as
        # cores do tema ESCURO (#6b7280 -> #e8eaf0), entao no modo claro o
        # percentil alto saia quase branco em cima da linha branca — o score
        # mais importante era o mais invisivel.
        # "Destacar" troca de direcao com o tema: no escuro e clarear, no
        # claro e escurecer. Por isso os dois extremos trocam de lado.
        _sc_claro = st.session_state.get("tema_claro", False)
        # O piso do claro sobe de txt-4 (3.39 de contraste) pra txt-3 (5.54):
        # no escuro o cinza baixo ainda e legivel porque o fundo e escuro e o
        # texto so precisa se afastar dele; no claro, cinza claro sobre branco
        # some de vez.
        # Os dois temas usam txt-3 aqui, mas por motivos diferentes: no escuro
        # ele e o #6b7280 que sempre foi o piso; no claro e o degrau que faltava.
        _sc_lo = token("txt-3", _sc_claro)                            # percentil baixo, recua
        _sc_hi = token("txt", _sc_claro)                              # percentil alto, destaca
        for ridx, (_, row) in enumerate(df_page.iterrows()):
            is_top = row["id"] in top10
            tags   = "".join([
                '<span class="top-badge">★ TOP</span>'               if is_top                    else "",
                '<span class="tag-novo">NOVO</span>'                 if row.get("_novo")          else "",
                '<span class="tag-upd">ATUALIZADO</span>'           if row.get("_atualizado")    else "",
                '<span class="tag-nova-cob">+ Nova cobrança</span>' if row.get("_nova_cobranca") else "",
                '<span style="background:var(--azul-2);color:var(--txt-inv);font-size:9px;font-weight:700;white-space:nowrap;padding:2px 5px;border-radius:4px;margin-right:3px">ACORDO</span>'  if row.get("_tem_acordo") else "",
                '<span style="background:var(--txt-3);color:var(--txt-inv);font-size:9px;font-weight:700;white-space:nowrap;padding:2px 5px;border-radius:4px;margin-right:3px">INATIVO</span>' if row.get("_inativo")    else "",
                '<span style="background:rgba(var(--rosa-v),calc(.18 * var(--tint-k)));color:var(--rosa);border:1px solid rgba(var(--rosa-v),.4);font-size:9px;font-weight:700;white-space:nowrap;padding:2px 5px;border-radius:4px;margin-right:3px">FIXO</span>' if row.get("_tel_fixo") else "",
            ])
            obs_icon  = ' <span style="color:var(--info);font-size:12px;font-weight:700">●</span>' if str(row["_notes"] or "") else ""
            row_bl    = "border-left:4px solid rgba(var(--erro-v),.6);" if is_top else ""
            row_bg    = "background:rgba(var(--erro-v),calc(.04 * var(--tint-k)));"           if is_top else ""

            rcols = st.columns(col_w, vertical_alignment="center")
            with rcols[0]:
                # A tag de atendente NAO e' redundante com a coluna Grupo:
                # get_effective_atendente tem 3 niveis (marcacao manual >
                # splgc-grupo > atendente atual no lote) e a coluna mostra so'
                # o do meio. Cliente sem grupo aparece como "—" na coluna mas
                # tem dono aqui. Entao so' mostra quando DIFERE — no caso
                # comum (grupo = atendente) nao gasta linha nenhuma.
                _at = str(row["_atendente"] or "")
                _gr = str(row.get("_grupo") or "")
                atend_tag = (
                    f'<span style="font-size:11px;color:var(--txt-2);margin-left:6px;'
                    f'font-weight:500">· {_at}</span>'
                ) if _at and _at != _gr else ""
                st.markdown(
                    f'<div style="padding:12px 12px;{row_bg}{row_bl}">'
                    f'<div style="margin-bottom:3px">{tags}</div>'
                    f'<div style="font-weight:600;font-size:clamp(15px,0.95vw,18px);color:var(--txt);line-height:1.3">{row["nome"]}{obs_icon}</div>'
                    f'<div style="color:var(--txt-2);font-size:15px;margin-top:2px;font-weight:500">{row.get("cnpj","")}{atend_tag}</div>'
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
                    cor_sc = "var(--alerta)"  # top 10% — laranja
                    # No claro a cor sozinha nao basta pro top 10% saltar: a
                    # coluna inteira e texto escuro sobre branco, e laranja
                    # escuro nao le como destaque. Entao ele ganha um chip —
                    # vira a unica coisa com preenchimento na coluna, e
                    # destaca por FORMA, nao so por cor. No escuro o laranja
                    # claro ja salta contra o fundo, e o chip so poluiria.
                    _chip = ("background:rgba(var(--alerta-v),calc(.18 * var(--tint-k)));"
                             "padding:2px 8px;border-radius:6px;" if _sc_claro else "")
                else:
                    _chip = ""
                    _ratio = _pct / 0.90  # 0..1 dentro dos 90% inferiores
                    _r1, _g1, _b1 = (int(_sc_lo[i:i + 2], 16) for i in (1, 3, 5))
                    _r2, _g2, _b2 = (int(_sc_hi[i:i + 2], 16) for i in (1, 3, 5))
                    _r = int(_r1 + (_r2 - _r1) * _ratio)
                    _g = int(_g1 + (_g2 - _g1) * _ratio)
                    _b = int(_b1 + (_b2 - _b1) * _ratio)
                    cor_sc = f"#{_r:02x}{_g:02x}{_b:02x}"
                st.markdown(
                    f'<div style="padding:12px 6px;text-align:center;white-space:nowrap">'
                    f'<span style="{_chip}color:{cor_sc};font-weight:800;font-size:15px">{_sc}</span>'
                    f'<span style="color:var(--txt-3);font-size:10px;margin-left:3px">pts</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with rcols[2]:
                st.markdown(f'<div style="padding:12px 12px;font-size:clamp(13px,0.92vw,17px);font-weight:600;white-space:nowrap">{fmt_moeda(row["valor"])}</div>', unsafe_allow_html=True)
            with rcols[3]:
                st.markdown(f'<div style="padding:12px 12px;font-size:14px">{dias_html(row.get("dias_atraso"))}</div>', unsafe_allow_html=True)
            with rcols[4]:
                m = int(row.get("_meses_atraso") or 0)
                cor_m = "var(--erro)" if m >= 9 else ("var(--laranja-3)" if m >= 5 else "var(--alerta)")
                st.markdown(
                    f'<div style="padding:12px 12px">'
                    f'<span style="color:{cor_m};font-weight:700;font-size:16px">{m}</span>'
                    f'<span style="color:var(--txt-2);font-size:14px">/12</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with rcols[5]:
                # Telefones: um por linha, todos do mesmo tamanho.
                # telefones_cliente descarta o que nao chega a ser telefone,
                # junta o mesmo numero escrito de formas diferentes nos 4
                # campos do cadastro e marca o que nao da pra discar.
                _raw_tels = row.get("telefones") or ([row.get("telefone")] if row.get("telefone") else [])
                _itens = telefones_cliente(_raw_tels)
                _pairs = [(_b, _f) for _b, _f, _p in _itens if not _p]
                _ruins = [(_f, _p) for _b, _f, _p in _itens if _p]
                if not _pairs and not _ruins:
                    tel_display = "—"
                else:
                    # Sem icone: um numero por linha, todos do mesmo tamanho.
                    # O numero inteiro e' o link (wa.me pra celular, tel: pra
                    # fixo), entao o clique continua funcionando sem gastar
                    # ~35px de coluna com dois SVGs por linha.
                    def _linha_tel(t: str, fmt: str) -> str:
                        if _eh_fixo(t):
                            _d = _tel_only_digits(t)
                            href = f"tel:+{_d}" if _d else ""
                            alvo = ""
                        else:
                            _wa = telefone_wa_link(t)
                            href = f"https://wa.me/{_wa}" if _wa else ""
                            alvo = ' target="_blank"'
                        _css = "white-space:nowrap"
                        if not href:
                            return f'<div style="{_css}">{fmt}</div>'
                        return (
                            f'<div style="{_css}">'
                            f'<a href="{href}"{alvo} style="color:inherit;text-decoration:none">'
                            f'{fmt}</a></div>'
                        )
                    # numero errado no cadastro: vermelho, sem link. Nao da
                    # pra discar, mas precisa aparecer pra ser corrigido.
                    tel_display = "".join(_linha_tel(t, f) for t, f in _pairs)
                    tel_display += "".join(
                        f'<div style="white-space:nowrap;color:var(--erro)" '
                        f'title="cadastro incompleto — {p}">{f}</div>'
                        for f, p in _ruins
                    )
                st.markdown(f'<div style="padding:12px 12px;font-size:14px;color:var(--txt-2);line-height:1.6">{tel_display}</div>', unsafe_allow_html=True)
            with rcols[6]:
                _g_row = row.get("_grupo") or ""
                # Celula vazia vira "—", nao "Sem especialista": o rotulo longo
                # quebrava em duas linhas e competia com o nome do especialista
                # de verdade. O filtro continua se chamando "Sem especialista".
                _g_row_display = _g_row if _g_row and str(_g_row) not in ("nan", "NaN", "—") else "—"
                # Quebra explicita no primeiro espaco: nome numa linha,
                # sobrenome na outra (so' em tela estreita, via CSS). Deixar a
                # cargo do navegador era o que produzia "Ana / Carolin / a".
                _g_p = str(_g_row_display).split(" ", 1)
                _g_row_display = (
                    f'<span class="g-nome">{_g_p[0]}</span>'
                    f'<span class="g-sobre">{_g_p[1]}</span>'
                ) if len(_g_p) == 2 else f'<span class="g-nome">{_g_row_display}</span>' 
                st.markdown(f'<div style="padding:12px 12px;font-size:14px;color:var(--txt-2);'
                            f'line-height:1.35;overflow:hidden">{_g_row_display}</div>', unsafe_allow_html=True)
            with rcols[7]:
                st.markdown(f'<div style="padding:12px 12px;font-size:14px;color:var(--txt-2);white-space:nowrap">{row["_lastContact"] or "—"}</div>', unsafe_allow_html=True)
            with rcols[8]:
                # Mesma escala do badge de Atraso (.da-30/60/90/max), pra
                # "180d" significar a mesma temperatura nas duas colunas.
                # Antes era binario em 90 dias, o que pintava "+853d" (o pior
                # caso possivel) do mesmo ambar de quem sumiu ha 3 meses.
                _lg = row.get("_ultimoLogin") or "—"
                _lg_ord = row.get("_ultimoLoginOrdem")
                if _lg_ord != _lg_ord or _lg_ord is None:   # NaN = sem vinculo
                    _lg_cor = "var(--txt-3)"
                elif _lg_ord <= 30:
                    _lg_cor = "var(--txt-2)"
                elif _lg_ord <= 90:
                    _lg_cor = "var(--laranja-2)"
                elif _lg_ord <= 180:
                    _lg_cor = "var(--laranja)"
                else:
                    _lg_cor = "var(--erro-2)"
                st.markdown(
                    f'<div style="padding:12px 12px;font-size:16px;font-weight:700;color:{_lg_cor}">{_lg}</div>',
                    unsafe_allow_html=True,
                )
            with rcols[9]:
                if st.button("✏", key=f"edit_{row['id']}_{ridx}", width="stretch", help=f"Editar {row['nome']}"):
                    dialog_editar(row["id"])

            if ridx < n_rows - 1:
                st.markdown('<div style="height:0.5px;background:var(--border);margin:0"></div>', unsafe_allow_html=True)

        st.markdown(
            f'<div style="background:var(--faixa);border:1px solid var(--border);border-top:none;'
            f'border-radius:0 0 12px 12px;padding:12px 16px;display:flex;'
            f'justify-content:space-between;font-size:13px;color:var(--txt-2);font-weight:500;box-shadow:var(--sombra-tabela)">'
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
            st.markdown(f'<div style="text-align:center;color:var(--txt-3);font-size:12px;padding-top:6px">Página {page} de {total_pg}</div>', unsafe_allow_html=True)
        with pc3:
            if st.button("Próxima →", disabled=(page >= total_pg), width="stretch"):
                st.session_state["page_num"] = page + 1
                st.rerun()

