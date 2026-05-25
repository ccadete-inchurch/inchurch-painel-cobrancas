from datetime import date

import pandas as pd
import streamlit as st

from helpers import fmt_moeda_plain, fmt_moeda, get_effective_atendente


def _render_historico(store):
    st.markdown(
        '<div style="font-family:Syne,sans-serif;font-size:20px;font-weight:700;margin-bottom:20px">Regularizados</div>',
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
    fb, fs, fa = st.columns([3, 2, 2])
    with fb:
        busca = st.text_input("Buscar", placeholder="Nome ou CNPJ...", key="reg_busca")
    with fs:
        filtro_sit = st.selectbox("Situação", ["Todos", "Apenas ativos", "Apenas inativos"], key="reg_sit")
    with fa:
        filtro_atd = st.selectbox(
            "Atendente",
            ["Todos"] + atendentes_disp + (["Sem atendente"] if (not df.empty and (df["atendente"] == "—").any()) else []),
            key="reg_atd",
        )

    if busca:
        b = busca.lower()
        df = df[df.apply(lambda r: b in str(r.get("nome","")).lower() or b in str(r.get("cnpj","")).lower(), axis=1)]
    if filtro_sit == "Apenas ativos" and "inativo" in df.columns:
        df = df[~df["inativo"].fillna(False).astype(bool)]
    elif filtro_sit == "Apenas inativos" and "inativo" in df.columns:
        df = df[df["inativo"].fillna(False).astype(bool)]
    if filtro_atd == "Sem atendente":
        df = df[df["atendente"] == "—"]
    elif filtro_atd != "Todos":
        df = df[df["atendente"] == filtro_atd]

    # ── Métricas ──────────────────────────────────────────────────────────────
    # Todos por CLIENTES ÚNICOS (não por faturas) — consistente com o badge
    # da Atividades. Cliente que paga vários boletos no mesmo dia/mês/ano
    # conta como 1. Valor é a soma real dos pagamentos (sem deduplicar).
    # Hoje usa FLAG do overlay (robusto contra falha de adicionar registro).
    hoje_br = date.today()
    sufixo_mes = hoje_br.strftime("/%m/%Y")  # "/MM/AAAA" — match endswith

    # Pagamentos Hoje (via flag — pode incluir parcial e total)
    clientes_hoje = [
        c for c in store.get("clientes", [])
        if c.get("_regularizado_hoje") or c.get("_pago_parcial_hoje")
    ]
    n_hoje = len(clientes_hoje)
    v_hoje = sum(float(c.get("_valor_pago_hoje") or 0) for c in clientes_hoje)

    # Mês / Histórico (clientes únicos via df)
    if df.empty:
        n_mes = n_total = 0
        v_mes = v_total = 0.0
    else:
        df_mes = df[df["data"].astype(str).str.endswith(sufixo_mes, na=False)]
        n_mes   = int(df_mes["id"].astype(str).nunique()) if not df_mes.empty else 0
        v_mes   = float(df_mes["valor"].sum()) if not df_mes.empty else 0.0
        n_total = int(df["id"].astype(str).nunique())
        v_total = float(df["valor"].sum())

    m1, m2, m3, _m4 = st.columns(4)
    _tooltip_dia = (
        "Inclui pagamentos parciais (cliente continua com cobranças vencidas) "
        "e regularizações totais. Difere do card 'regularizações' da Atividades, "
        "que conta só quem quitou TUDO."
    )
    for col, label, valor, qtd, tooltip in [
        (m1, "Pagamentos do Dia",   v_hoje,  n_hoje,  _tooltip_dia),
        (m2, "Pagamentos no Mês",   v_mes,   n_mes,   ""),
        (m3, "Total Histórico",     v_total, n_total, ""),
    ]:
        with col:
            sub = f'{qtd} {"cliente pagou" if qtd == 1 else "clientes pagaram"}'
            title_attr = f' title="{tooltip}"' if tooltip else ""
            cursor = "help" if tooltip else "default"
            st.markdown(
                f'<div class="metric-card" style="cursor:{cursor}"{title_attr}>'
                f'<div class="metric-label">{label}</div>'
                f'<div style="font-size:15px;font-weight:600;color:#2dd36f;margin-top:4px">{fmt_moeda_plain(valor)}</div>'
                f'<div class="metric-sub">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    # ── Tabela ────────────────────────────────────────────────────────────────
    col_w = [1.2, 3, 1.8, 1.5, 1.5]
    hdrs  = ["Data", "Cliente", "CNPJ", "Valor", "Atendente"]

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
    for i, row in enumerate(rows):
        inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-right:4px">INATIVO</span>' if row.get("inativo") else ""
        rcols = st.columns(col_w)
        with rcols[0]:
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;color:#8b94a5">{row.get("data","—")}</div>', unsafe_allow_html=True)
        with rcols[1]:
            st.markdown(
                f'<div style="padding:12px 14px">'
                f'<div style="margin-bottom:2px">{inativo_badge}</div>'
                f'<div style="font-size:14px;font-weight:600;color:#e8eaf0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{row.get("nome","—")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with rcols[2]:
            st.markdown(f'<div style="padding:12px 14px;font-size:13px;color:#8b94a5">{row.get("cnpj","—")}</div>', unsafe_allow_html=True)
        with rcols[3]:
            st.markdown(f'<div style="padding:12px 14px;font-size:14px;font-weight:600;color:#2dd36f">{fmt_moeda(row.get("valor",0))}</div>', unsafe_allow_html=True)
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
