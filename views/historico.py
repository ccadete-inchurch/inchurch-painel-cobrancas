from datetime import date

import pandas as pd
import streamlit as st

from helpers import fmt_moeda_plain, fmt_moeda, get_effective_atendente, hoje_lote
from data import fetch_ids_em_qualquer_lote_hoje


def _render_historico(store):
    st.markdown(
        '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:36px;'
        'font-weight:800;color:#e8eaf0;margin-top:24px;margin-bottom:24px;letter-spacing:-1px;line-height:1.1">'
        'Pagamentos</div>',
        unsafe_allow_html=True,
    )

    reg = store["regularizados"]
    if not reg:
        st.info("Nenhum cliente regularizado ainda.")
        return

    df = pd.DataFrame(reg)

    # Resolve atendente: grupo (splgc-grupo) primeiro, painel_tarefas_diarias
    # como fallback. get_effective_atendente já encapsula essa lógica.
    def _resolve_atendente(row):
        at = str(row.get("atendente") or "").strip()
        if at and "BigQuery" not in at:
            return at
        return get_effective_atendente(str(row.get("id") or "")) or "—"

    if not df.empty:
        df["atendente"] = df.apply(_resolve_atendente, axis=1)

    # Ordena por data desc (mais recentes primeiro). Pagamentos via overlay
    # da API entram com data de hoje — sem sort ficariam escondidos no fim
    # da lista, depois dos registros históricos do BQ.
    if not df.empty and "data" in df.columns:
        df["_data_dt"] = pd.to_datetime(df["data"], format="%d/%m/%Y", errors="coerce")
        df = df.sort_values("_data_dt", ascending=False, na_position="last").drop(columns=["_data_dt"])

    # ── Filtros ───────────────────────────────────────────────────────────────
    atendentes_disp = sorted({a for a in df["atendente"].unique() if a and a != "—"}) if not df.empty else []

    hoje_br_pre = date.fromisoformat(hoje_lote())
    # Default: mês corrente (1º dia → hoje)
    _ini_default = hoje_br_pre.replace(day=1)

    fb, fp, fs, fa = st.columns([2.4, 2.2, 1.3, 1.5])
    with fb:
        busca = st.text_input("Buscar", placeholder="Nome, CNPJ ou ID sacado...", key="reg_busca")
    with fp:
        # Date range picker — qualquer intervalo de datas
        intervalo_selecionado = st.date_input(
            "Período (de → até)",
            value=(_ini_default, hoje_br_pre),
            key="reg_periodo_range",
            format="DD/MM/YYYY",
        )
    with fs:
        filtro_sit = st.selectbox("Situação", ["Todos", "Apenas ativos", "Apenas inativos"], key="reg_sit")
    with fa:
        filtro_atd = st.selectbox(
            "Grupo",
            ["Todos"] + atendentes_disp + (["Sem especialista"] if (not df.empty and (df["atendente"] == "—").any()) else []),
            key="reg_atd",
        )

    if busca:
        b = busca.lower()
        df = df[df.apply(lambda r: b in str(r.get("nome","")).lower() or b in str(r.get("cnpj","")).lower(), axis=1)]
    if filtro_sit == "Apenas ativos" and "inativo" in df.columns:
        df = df[~df["inativo"].fillna(False).astype(bool)]
    elif filtro_sit == "Apenas inativos" and "inativo" in df.columns:
        df = df[df["inativo"].fillna(False).astype(bool)]
    if filtro_atd == "Sem especialista":
        df = df[df["atendente"] == "—"]
    elif filtro_atd != "Todos":
        df = df[df["atendente"] == filtro_atd]

    # Filtro temporal via date range picker — orquestra cards + tabela.
    # st.date_input com value tupla retorna tupla (dt_ini, dt_fim) quando
    # ambas datas escolhidas; tupla com 1 item enquanto user escolhe a 2ª.
    dt_ini, dt_fim = None, None
    if isinstance(intervalo_selecionado, tuple):
        if len(intervalo_selecionado) == 2:
            dt_ini, dt_fim = intervalo_selecionado
        elif len(intervalo_selecionado) == 1:
            dt_ini = dt_fim = intervalo_selecionado[0]
    elif intervalo_selecionado:  # date single
        dt_ini = dt_fim = intervalo_selecionado

    if dt_ini and dt_fim and not df.empty:
        df = df.copy()
        df["_dt_temp"] = pd.to_datetime(df["data"], format="%d/%m/%Y", errors="coerce")
        df = df[(df["_dt_temp"].dt.date >= dt_ini) & (df["_dt_temp"].dt.date <= dt_fim)]
        df = df.drop(columns=["_dt_temp"])

    # Label do período pra usar nos cards (texto curto). Ambas as datas
    # mostram o ano completo pra evitar ambiguidade entre anos diferentes.
    if dt_ini and dt_fim:
        if dt_ini == dt_fim:
            periodo = dt_ini.strftime("%d/%m/%Y")
        else:
            periodo = f"{dt_ini.strftime('%d/%m/%Y')} → {dt_fim.strftime('%d/%m/%Y')}"
    else:
        periodo = "Período"

    # ── Métricas ──────────────────────────────────────────────────────────────
    # Cards driven pelo período selecionado — df já está filtrado por período.
    hoje_br = date.fromisoformat(hoje_lote())
    hoje_str = hoje_br.strftime("%d/%m/%Y")

    # Pagamentos no Período = todos os pagamentos do df filtrado
    if not df.empty:
        n_periodo = int(df["id"].astype(str).nunique())
        v_periodo = float(df["valor"].sum())
    else:
        n_periodo = 0
        v_periodo = 0.0

    # Regularizações no Período = subset que efetivamente regularizou
    # Combina 2 fontes: overlay HOJE (real-time) + histórico (BQ cross-check)
    ids_reg_hoje_all = {
        str(c.get("id") or "") for c in store.get("clientes", [])
        if c.get("_regularizado_hoje")
    }
    # Lookup do cliente atual em store["clientes"] pra puxar saldo/acordo
    # e pra check de regularização operacional (sem saldo = regularizou).
    _clientes_lookup = {
        str(c.get("id") or ""): c for c in store.get("clientes", []) or []
    }

    if not df.empty:
        def _eh_reg(r):
            _rid = str(r.get("id") or "")
            # 2 fontes simples:
            # 1) Overlay marcou regularizado (janela 3d — não amarra a hoje_str)
            # 2) Cliente fora da carteira atual (sem saldo)
            return (
                _rid in ids_reg_hoje_all
                or _rid not in _clientes_lookup
            )
        df_reg_periodo = df[df.apply(_eh_reg, axis=1)]
        n_reg = int(df_reg_periodo["id"].astype(str).nunique()) if not df_reg_periodo.empty else 0
        v_reg = float(df_reg_periodo["valor"].sum()) if not df_reg_periodo.empty else 0.0
    else:
        n_reg = 0
        v_reg = 0.0

    # Taxa de regularização (% pagantes que zeraram tudo)
    taxa_reg = (n_reg / n_periodo * 100) if n_periodo > 0 else 0.0

    # IDs reg do dia (pra badge na tabela) — mantém compat com o restante
    ids_reg_hoje = ids_reg_hoje_all

    m1, m2, m3 = st.columns(3)
    _tooltip_pag = (
        f"Todos os pagamentos atrasados no período selecionado "
        f"({periodo}). Inclui parciais + regularizações."
    )
    _tooltip_reg = (
        f"Clientes que quitaram TODAS as cobranças vencidas no período "
        f"({periodo}). Subset de Pagamentos."
    )
    _tooltip_taxa = (
        "Percentual de pagamentos que resultaram em regularização total. "
        "Reflete quão 'completos' são os pagamentos no período."
    )
    # Cards adaptam label ao período. Tipo "moeda" formata R$, "pct" formata %.
    # Taxa de Regularização tem sub-texto diferente (X de Y, não 'X regularizaram').
    _sub_taxa = (
        f'{n_reg} de {n_periodo} {"regularizou" if n_periodo == 1 else "regularizaram"}'
    ) if n_periodo > 0 else "sem pagamentos no período"
    _sub_pag = (
        f'{n_periodo} {"cliente" if n_periodo == 1 else "clientes"} '
        f'{"pagou" if n_periodo == 1 else "pagaram"}'
    )
    _sub_reg = (
        f'{n_reg} {"cliente" if n_reg == 1 else "clientes"} '
        f'{"regularizou" if n_reg == 1 else "regularizaram"}'
    )
    cards = [
        (m1, f"Pagamentos · {periodo}",     fmt_moeda_plain(v_periodo), _sub_pag,  _tooltip_pag,  "#2dd36f"),
        (m2, f"Regularizações · {periodo}", fmt_moeda_plain(v_reg),     _sub_reg,  _tooltip_reg,  "#2dd36f"),
        (m3, "Taxa de Regularização",       f"{taxa_reg:.2f}%",         _sub_taxa, _tooltip_taxa, "#5fa3ff"),
    ]
    for col, label, valor_str, sub, tooltip, cor_valor in cards:
        with col:
            title_attr = f' title="{tooltip}"' if tooltip else ""
            cursor = "help" if tooltip else "default"
            st.markdown(
                f'<div class="metric-card" style="cursor:{cursor};padding:18px 20px"{title_attr}>'
                f'<div class="metric-label" style="font-size:14px;letter-spacing:1.3px">{label}</div>'
                f'<div style="font-size:30px;font-weight:800;color:{cor_valor};margin-top:6px;'
                f'line-height:1.1;font-variant-numeric:tabular-nums">{valor_str}</div>'
                f'<div class="metric-sub" style="font-size:14px;margin-top:8px">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ── Tabela ────────────────────────────────────────────────────────────────
    # Cliente primeiro pra receber o destaque visual do LOTE (faixa lateral)
    # de forma natural na lateral esquerda da tabela.
    col_w = [3, 1.2, 1.8, 1.5, 1.5]
    hdrs  = ["Cliente", "Data de Pag.", "CNPJ", "Valor", "Especialista"]

    hdr_cells = "".join(
        f'<div style="flex:{w};padding:14px 14px;font-size:12px;text-transform:uppercase;'
        f'letter-spacing:1.2px;color:#8b94a5;font-weight:700;white-space:nowrap">{h}</div>'
        for w, h in zip(col_w, hdrs)
    )
    st.markdown(
        f'<div style="display:flex;gap:1rem;background:#1e2333;border:1px solid #2a2f42;'
        f'border-radius:12px 12px 0 0;overflow:hidden">{hdr_cells}</div>',
        unsafe_allow_html=True,
    )

    if df.empty:
        st.markdown(
            '<div style="background:#181c26;border:1px solid #2a2f42;border-top:none;'
            'border-radius:0 0 12px 12px;padding:60px;text-align:center;color:#6b7280;font-size:14px">'
            'Nenhum resultado.</div>',
            unsafe_allow_html=True,
        )
        return

    PAGE_SIZE = 100
    total_f   = len(df)
    total_pg  = max(1, -(-total_f // PAGE_SIZE))
    page      = max(1, min(st.session_state.get("reg_page", 1), total_pg))
    rows      = df.iloc[(page - 1) * PAGE_SIZE : page * PAGE_SIZE].to_dict("records")
    n = len(rows)

    # IDs do lote de hoje (qualquer atendente). Marca linhas verde pra
    # destacar conversão: cliente foi trabalhado no lote E pagou hoje.
    ids_lote_hoje = fetch_ids_em_qualquer_lote_hoje()

    for i, row in enumerate(rows):
        inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:4px">INATIVO</span>' if row.get("inativo") else ""
        # Badge "REGULARIZADO" — 2 fontes simples:
        # 1) HOJE via overlay API (real-time)
        # 2) Cliente NÃO está na carteira atual (sem saldo pendente)
        # Trade-off aceito: re-inadimplência (cliente paga, volta a inad)
        # perde o badge na linha antiga. Acceito pra ganhar simplicidade.
        _rid = str(row.get("id") or "")
        _rdt = str(row.get("data") or "")
        _cli_atual = _clientes_lookup.get(_rid)
        # Overlay tem janela de 3 dias — se cliente foi marcado como
        # _regularizado_hoje, a liquidação que disparou isso pode ser de
        # ontem ou anteontem (creditada hoje). Não exigir _rdt==hoje_str.
        eh_reg_hoje = _rid in ids_reg_hoje
        eh_reg_sem_saldo = _cli_atual is None  # saiu da carteira → regularizou
        eh_regularizado = eh_reg_hoje or eh_reg_sem_saldo
        reg_badge = (
            '<span style="background:rgba(45,211,111,.18);color:#2dd36f;'
            'font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;'
            'margin-right:4px">✓ REGULARIZADO</span>' if eh_regularizado else ""
        )
        # Badge PAGAMENTO PARCIAL (azul) — pagou algo mas não zerou a dívida.
        # Mutuamente exclusivo com REGULARIZADO.
        parcial_badge = (
            '<span style="background:rgba(95,163,255,.18);color:#5fa3ff;'
            'font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;'
            'margin-right:4px">PAGAMENTO PARCIAL</span>' if not eh_regularizado else ""
        )
        # Badge ACORDO (amarelo) — só pra clientes AINDA na carteira.
        acordo_badge = ""
        if _cli_atual and not eh_regularizado:
            if _cli_atual.get("_tem_acordo"):
                acordo_badge = (
                    '<span style="background:rgba(245,158,11,.2);color:#f59e0b;'
                    'font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;'
                    'margin-right:4px">ACORDO</span>'
                )
        # Marca conversão: cliente do lote de hoje que pagou (parcial OU
        # regularização). Faixa verde lateral + tint sutil na célula
        # Cliente — espelha o TOP em Inadimplentes (.04 bg, .6 border).
        # Sem badge LOTE: tint verde já comunica "veio do lote", e badge
        # competia com REGULARIZADO/PARCIAL ali do lado.
        em_lote_hoje = _rid in ids_lote_hoje
        cli_bg = "background:rgba(45,211,111,.04);" if em_lote_hoje else ""
        cli_bl = "border-left:4px solid rgba(45,211,111,.6);" if em_lote_hoje else ""
        rcols = st.columns(col_w)
        with rcols[0]:
            badges_html = f'{reg_badge}{parcial_badge}{acordo_badge}{inativo_badge}'
            badges_line = f'<div style="margin-bottom:2px">{badges_html}</div>' if badges_html else ''
            st.markdown(
                f'<div style="padding:12px 14px;{cli_bg}{cli_bl}">'
                f'{badges_line}'
                f'<div style="font-size:14px;font-weight:600;color:#e8eaf0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{row.get("nome","—")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with rcols[1]:
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;color:#8b94a5">{row.get("data","—")}</div>', unsafe_allow_html=True)
        with rcols[2]:
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;color:#8b94a5">{row.get("cnpj","—")}</div>', unsafe_allow_html=True)
        with rcols[3]:
            # fmt_moeda_plain (não fmt_moeda) — fmt_moeda colore valores altos
            # em vermelho/âmbar como ALERTA (desenhado pra dívidas em
            # Inadimplência). Aqui é PAGAMENTO recebido → tudo verde.
            st.markdown(f'<div style="padding:12px 14px;font-size:14px;font-weight:600;color:#2dd36f">{fmt_moeda_plain(row.get("valor",0))}</div>', unsafe_allow_html=True)
        with rcols[4]:
            _at_txt = str(row.get("atendente") or "—")
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;color:#8b94a5">{_at_txt}</div>', unsafe_allow_html=True)

        if i < n - 1:
            st.markdown('<div style="height:0.5px;background:#2a2f42;margin:0"></div>', unsafe_allow_html=True)

    st.markdown(
        f'<div style="background:#1e2333;border:1px solid #2a2f42;border-top:none;'
        f'border-radius:0 0 12px 12px;padding:10px 16px;display:flex;justify-content:space-between;font-size:12px;color:#6b7280">'
        f'<span>Mostrando {(page-1)*PAGE_SIZE+1}–{min(page*PAGE_SIZE, total_f)} de {total_f} pagamentos</span>'
        f'<span>Página {page} de {total_pg}</span></div>',
        unsafe_allow_html=True,
    )

    if total_pg > 1:
        st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)
        pc1, pc2, pc3 = st.columns([1, 2, 1])
        with pc1:
            if st.button("← Anterior", key="reg_prev", disabled=(page <= 1), width="stretch"):
                st.session_state["reg_page"] = page - 1
                st.rerun()
        with pc2:
            st.markdown(f'<div style="text-align:center;color:#6b7280;font-size:12px;padding-top:6px">Página {page} de {total_pg}</div>', unsafe_allow_html=True)
        with pc3:
            if st.button("Próxima →", key="reg_next", disabled=(page >= total_pg), width="stretch"):
                st.session_state["reg_page"] = page + 1
                st.rerun()
