from datetime import date, timedelta

import pandas as pd
import streamlit as st

from data import fetch_eventos_regularizacao
from helpers import fmt_moeda_plain, fmt_moeda, get_effective_atendente, hoje_lote


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

    # Helper: calcula intervalo de datas baseado no preset selecionado.
    hoje_br_pre = date.fromisoformat(hoje_lote())
    def _intervalo_periodo(p: str) -> tuple[date, date] | None:
        if p == "Hoje":
            return (hoje_br_pre, hoje_br_pre)
        if p == "Esta semana":
            return (hoje_br_pre - timedelta(days=hoje_br_pre.weekday()), hoje_br_pre)
        if p == "Este mês":
            return (hoje_br_pre.replace(day=1), hoje_br_pre)
        if p == "Mês anterior":
            primeiro = hoje_br_pre.replace(day=1)
            ultimo_mes_passado = primeiro - timedelta(days=1)
            return (ultimo_mes_passado.replace(day=1), ultimo_mes_passado)
        if p == "Últimos 30 dias":
            return (hoje_br_pre - timedelta(days=30), hoje_br_pre)
        if p == "Últimos 90 dias":
            return (hoje_br_pre - timedelta(days=90), hoje_br_pre)
        return None  # 'Tudo'

    fb, fp, fs, fa = st.columns([3, 1.6, 1.4, 1.6])
    with fb:
        busca = st.text_input("Buscar", placeholder="Nome, CNPJ ou ID sacado...", key="reg_busca")
    with fp:
        periodo = st.selectbox(
            "Período",
            ["Hoje", "Esta semana", "Este mês", "Mês anterior",
             "Últimos 30 dias", "Últimos 90 dias", "Tudo"],
            index=2,  # 'Este mês' como default
            key="reg_periodo",
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

    # Filtro temporal — orquestra cards + tabela.
    intervalo = _intervalo_periodo(periodo)
    if intervalo and not df.empty:
        dt_ini, dt_fim = intervalo
        df = df.copy()
        df["_dt_temp"] = pd.to_datetime(df["data"], format="%d/%m/%Y", errors="coerce")
        df = df[(df["_dt_temp"].dt.date >= dt_ini) & (df["_dt_temp"].dt.date <= dt_fim)]
        df = df.drop(columns=["_dt_temp"])

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
    eventos_reg_historico = fetch_eventos_regularizacao()

    if not df.empty:
        def _eh_reg(r):
            _rid = str(r.get("id") or "")
            _rdt = str(r.get("data") or "")
            return (
                (_rid in ids_reg_hoje_all and _rdt == hoje_str)
                or (_rid, _rdt) in eventos_reg_historico
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
        (m3, "Taxa de Regularização",       f"{taxa_reg:.0f}%",         _sub_taxa, _tooltip_taxa, "#5fa3ff"),
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
    col_w = [1.2, 3, 1.8, 1.5, 1.5]
    hdrs  = ["Data de Pag.", "Cliente", "CNPJ", "Valor", "Especialista"]

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

    # Eventos históricos de regularização — set de (id, data) detectados
    # via diff entre snapshots consecutivos. Pra HOJE usa o overlay
    # (ids_reg_hoje) que é real-time; pra dias passados usa esse set.
    eventos_reg_historico = fetch_eventos_regularizacao()

    # Lookup do cliente atual em store["clientes"] pra puxar saldo e acordo.
    # Se cliente não está mais inadimplente (saiu da carteira), retorna None.
    _clientes_lookup = {
        str(c.get("id") or ""): c for c in store.get("clientes", []) or []
    }

    PAGE_SIZE = 100
    total_f   = len(df)
    total_pg  = max(1, -(-total_f // PAGE_SIZE))
    page      = max(1, min(st.session_state.get("reg_page", 1), total_pg))
    rows      = df.iloc[(page - 1) * PAGE_SIZE : page * PAGE_SIZE].to_dict("records")
    n = len(rows)
    for i, row in enumerate(rows):
        inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:4px">INATIVO</span>' if row.get("inativo") else ""
        # Badge "REGULARIZADO" — combina 2 fontes:
        # 1) HOJE: overlay API (flag _regularizado_hoje em store["clientes"])
        # 2) HISTÓRICO: detecção via diff de snapshots consecutivos
        _rid = str(row.get("id") or "")
        _rdt = str(row.get("data") or "")
        eh_reg_hoje = _rid in ids_reg_hoje and _rdt == hoje_str
        eh_reg_historico = (_rid, _rdt) in eventos_reg_historico
        eh_regularizado = eh_reg_hoje or eh_reg_historico
        reg_badge = (
            '<span style="background:rgba(45,211,111,.18);color:#2dd36f;'
            'font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;'
            'margin-right:4px">✓ REGULARIZADO</span>' if eh_regularizado else ""
        )
        # Badge ACORDO (azul, mesmo padrão da tela Inadimplência) e saldo
        # a pagar — só pra clientes que AINDA estão inadimplentes (estão em
        # store["clientes"]). Se regularizou, esses badges não aparecem.
        _cli_atual = _clientes_lookup.get(_rid)
        acordo_badge = ""
        saldo_html = ""
        if _cli_atual and not eh_regularizado:
            if _cli_atual.get("_tem_acordo"):
                acordo_badge = (
                    '<span style="background:#4f7cff;color:#fff;font-size:10px;'
                    'font-weight:700;padding:2px 7px;border-radius:4px;'
                    'margin-right:4px">ACORDO</span>'
                )
            _saldo = float(_cli_atual.get("valor") or 0)
            if _saldo > 0:
                saldo_html = (
                    f'<div style="font-size:11px;color:#f59e0b;margin-top:3px;font-weight:600">'
                    f'Saldo: {fmt_moeda_plain(_saldo)}</div>'
                )
        rcols = st.columns(col_w)
        with rcols[0]:
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;color:#8b94a5">{row.get("data","—")}</div>', unsafe_allow_html=True)
        with rcols[1]:
            badges_html = f'{reg_badge}{acordo_badge}{inativo_badge}'
            badges_line = f'<div style="margin-bottom:2px">{badges_html}</div>' if badges_html else ''
            st.markdown(
                f'<div style="padding:12px 14px">'
                f'{badges_line}'
                f'<div style="font-size:14px;font-weight:600;color:#e8eaf0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{row.get("nome","—")}</div>'
                f'{saldo_html}'
                f'</div>',
                unsafe_allow_html=True,
            )
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
