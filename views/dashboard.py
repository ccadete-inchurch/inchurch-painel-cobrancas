import hashlib
from datetime import date

import pandas as pd
import streamlit as st

from config import SORT_MAP, STATUS_FILTER_MAP, PAGE_SIZE
from auth import get_store, hash_senha, current_role
from helpers import get_hist, fmt_moeda, fmt_moeda_plain, dias_html, get_effective_status, get_effective_lastContact, get_effective_atendente, parse_date_br
from data import calcular_pendencias, fetch_regularizados_mes_atual, fetch_snapshot_inicio_mes, concluir_pendencia
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

    if ids_inicio:
        # Snapshot disponível — matemática exata
        novos_mes = len(ids_atuais - ids_inicio)  # ID em hoje, não em snapshot inicial
        reg_mes   = len(ids_inicio - ids_atuais)  # ID em snapshot inicial, não em hoje
        snapshot_dt = st.session_state.get("_snapshot_inicio_mes_data", "")
        # Se snapshot começou depois do dia 1 (ex: implementação no meio do mês),
        # exibe a data de referência no card pra ficar claro o que está medindo.
        variacao_sub = f"desde {snapshot_dt}" if snapshot_dt and not snapshot_dt.startswith("01/") else "no mês"
    else:
        # Fallback heurístico — usado enquanto o snapshot não foi populado
        ids_pagaram_em_atraso = fetch_regularizados_mes_atual()
        reg_mes               = len(ids_pagaram_em_atraso - ids_atuais)
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
                f'<div class="metric-card" style="min-height:150px;padding:20px 18px">'
                f'<div class="metric-label" style="font-size:12px">{label}</div>'
                f'<div class="metric-value" style="color:{cor};font-size:38px">{val:,}</div>'
                f'<div class="metric-sub" style="font-size:13px">{sub}</div></div>',
                unsafe_allow_html=True,
            )
    # 6º card: variação no mês
    with s6:
        sinal = "+" if saldo_mes >= 0 else ""
        cor_saldo = "#ef4444" if saldo_mes > 0 else ("#22c55e" if saldo_mes < 0 else "#e8eaf0")
        st.markdown(
            f'<div class="metric-card" style="min-height:150px;padding:20px 18px">'
            f'<div class="metric-label" style="font-size:12px">Variação {variacao_sub}</div>'
            f'<div class="metric-value" style="color:{cor_saldo};font-size:38px">{sinal}{saldo_mes:,}</div>'
            f'<div class="metric-sub" style="font-size:12px;margin-top:6px">'
            f'<span style="color:#ef4444;font-weight:700">↑ {novos_mes}</span> novos · '
            f'<span style="color:#22c55e;font-weight:700">↓ {reg_mes}</span> regularizados'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    # ── Clientes fixados ──────────────────────────────────────────────────────
    # Lista ordenada por dias_atraso DESC. Cor da borda reflete urgência.
    # Concluir agora vive dentro do dialog (botão Ver abre, ✅ Concluir fica lá).
    pendencias = calcular_pendencias(clientes)
    if pendencias:
        im = {"promise": "🟠", "retorno": "📞", "semcontato": "⚠️"}
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

        # Header — caixa alta com peso 800. Toggle pequeno (▴/▾) pra ocultar
        # a seção. Filtro 'Grupo' (atendente) ao lado pra admin/gestor.
        hcol, fcol, tcol = st.columns([3.4, 1.2, 0.35])
        with hcol:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:14px;margin-bottom:6px">'
                f'<span style="font-weight:800;font-size:24px;color:#e8eaf0;'
                f'text-transform:uppercase;letter-spacing:1.5px">'
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
        mostrar_fixados = st.session_state.setdefault("_fix_mostrar", True)
        with tcol:
            icone_toggle = "▴" if mostrar_fixados else "▾"
            help_toggle  = "Ocultar fixados" if mostrar_fixados else "Mostrar fixados"
            if st.button(icone_toggle, key="_btn_toggle_fixados",
                         width="stretch", help=help_toggle):
                st.session_state["_fix_mostrar"] = not mostrar_fixados
                st.rerun()

        # Aplica filtro de atendente nas pendências
        if filtro_atend != "Todos":
            pendencias = [
                p for p in pendencias
                if filtro_atend in (p[1].get("_atendentes_origem") or [])
            ]

        if not mostrar_fixados:
            pass  # seção colapsada, pula renderização e divisor
        elif not pendencias:
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
            # Ícone do botão adapta por role: atendente → ✏ (ação/edição),
            # admin/gestor → 👁 (observação, dialog é read-only)
            icone_btn = "✏" if role not in ("admin", "gestor") else "👁"
            help_btn  = "Atender" if role not in ("admin", "gestor") else "Ver detalhes"
            for i, (c, _h, tipo, msg, dias_atraso) in enumerate(pend_pag):
                if dias_atraso >= 7:
                    cor_borda = "#ef4444"
                elif dias_atraso >= 3:
                    cor_borda = "#f97316"
                elif dias_atraso >= 1:
                    cor_borda = "#eab308"
                else:
                    cor_borda = "#22c55e"
                sufixo = "hoje" if dias_atraso == 0 else f"há {dias_atraso}d"
                origens = _h.get("_atendentes_origem") or []
                origem_tag = ""
                if origens and role in ("admin", "gestor"):
                    origem_tag = (
                        f'<div style="font-size:11px;color:#8b94a5;margin-top:4px;font-weight:500">'
                        f'• {" / ".join(origens)}'
                        f'</div>'
                    )
                with cols_p[i % CARDS_POR_LINHA]:
                    st.markdown(
                        f'<div class="pend-card" style="border-left:4px solid {cor_borda}">'
                        f'<div style="font-weight:700;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{im[tipo]} {c["nome"]}</div>'
                        f'<div style="font-size:11px;color:#8b94a5;margin-top:4px">{msg} · <span style="color:{cor_borda};font-weight:700">{sufixo}</span></div>'
                        f'<div style="font-size:12px;color:#7cc243;margin-top:6px;font-weight:700">{fmt_moeda_plain(c["valor"])}</div>'
                        f'{origem_tag}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    # Ícone do botão adapta por role (✏ atendente, 👁 admin/gestor)
                    if st.button(icone_btn, key=f"pend_atend_{i}_{c['id']}", width="stretch", help=help_btn):
                        dialog_editar(c["id"])
            st.markdown('</div>', unsafe_allow_html=True)

            # Paginação minimalista: só setas + indicador 'X / Y'
            if total_pg_fix > 1:
                pc1, pc2, pc3 = st.columns([0.4, 1, 0.4])
                with pc1:
                    if st.button("←", disabled=(page_fix <= 1),
                                 key="_fix_prev", help="Página anterior"):
                        st.session_state["_fix_page"] = page_fix - 1
                        st.rerun()
                with pc2:
                    st.markdown(
                        f'<div style="text-align:center;color:#6b7280;font-size:12px;padding-top:8px">'
                        f'{page_fix} / {total_pg_fix}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                with pc3:
                    if st.button("→", disabled=(page_fix >= total_pg_fix),
                                 key="_fix_next", help="Próxima página"):
                        st.session_state["_fix_page"] = page_fix + 1
                        st.rerun()
        st.markdown("---")

    # ── Barra de ações ────────────────────────────────────────────────────────
    _, ta, tb = st.columns([6, 1, 1])
    with ta:
        if st.button("↑ Atualizar", width="stretch", help="Recarregar dados do BigQuery"):
            st.session_state["tela"] = "importar"
            st.rerun()
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
        st.info("Nenhum dado. Use ↑ Atualizar para importar as planilhas.")
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

    # ── Gerenciar usuários (admin) ─────────────────────────────────────────────
    if role == "admin":
        st.markdown("---")
        with st.expander("⚙️ Gerenciar Usuários"):
            store2 = get_store()
            c1, c2, c3, c4 = st.columns(4)
            with c1: u_nome  = st.text_input("Nome",   key="u_nome")
            with c2: u_email = st.text_input("E-mail", key="u_email")
            with c3: u_senha = st.text_input("Senha",  type="password", key="u_senha")
            with c4: u_role  = st.selectbox("Perfil",  ["atendente", "gestor", "admin"], key="u_role")
            if st.button("➕ Criar usuário"):
                if u_nome and u_email and u_senha:
                    uid = hashlib.md5(u_email.encode()).hexdigest()
                    store2["usuarios"][uid] = {
                        "nome": u_nome, "email": u_email,
                        "senha_hash": hash_senha(u_senha), "role": u_role,
                    }
                    st.toast(f"✅ Usuário {u_nome} criado!", icon="✅")
                else:
                    st.error("Preencha todos os campos.")
            st.markdown("**Usuários cadastrados:**")
            for u in store2["usuarios"].values():
                st.markdown(f'• **{u["nome"]}** ({u["email"]}) — `{u["role"]}`')
