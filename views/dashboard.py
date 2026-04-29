import hashlib
from datetime import date

import pandas as pd
import streamlit as st

from config import SORT_MAP, STATUS_FILTER_MAP, PAGE_SIZE
from auth import get_store, hash_senha, current_role
from helpers import get_hist, fmt_moeda, fmt_moeda_plain, dias_html
from data import calcular_pendencias
from views.dialog import dialog_editar


def _render_dashboard(store, clientes, role):
    from auth import current_nome
    nome = current_nome() or "usuário"
    st.markdown(
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:52px;font-weight:800;color:#e8eaf0;margin-top:32px;margin-bottom:48px;letter-spacing:-1.5px;line-height:1.1">Bem-vindo(a), {nome}!</div>',
        unsafe_allow_html=True,
    )

    # ── Métricas ──────────────────────────────────────────────────────────────
    total = len(clientes)
    pending = contacted = promise = 0
    for c in clientes:
        s = get_hist(c["id"]).get("status", "pending")
        if s == "pending":         pending   += 1
        elif s == "contacted":     contacted += 1
        elif s in ("promise", "negotiating"): promise += 1

    hoje_str = date.today().strftime("%d/%m/%Y")
    reg_hoje = len([r for r in store["regularizados"] if r.get("data") == hoje_str])

    s1, s2, s3, s4, s5 = st.columns(5)
    for col, label, val, cor, sub in [
        (s1, "Total Inadimplentes", total,     "#e8eaf0", "clientes ativos"),
        (s2, "Não Contactados",     pending,   "#ef4444", "aguardando contato"),
        (s3, "Contactados",         contacted, "#f59e0b", "em acompanhamento"),
        (s4, "Promessas",           promise,   "#f97316", "aguardando pagamento"),
        (s5, "Regularizados Hoje",  reg_hoje,  "#22c55e", "ver histórico"),
    ]:
        with col:
            st.markdown(
                f'<div class="metric-card"><div class="metric-label">{label}</div>'
                f'<div class="metric-value" style="color:{cor};font-size:32px">{val:,}</div>'
                f'<div class="metric-sub">{sub}</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown("")

    # ── Pendências ────────────────────────────────────────────────────────────
    pendencias = calcular_pendencias(clientes)
    if pendencias:
        cm = {"promise": "#f97316", "retorno": "#4f7cff", "semcontato": "#f59e0b"}
        im = {"promise": "🟠",      "retorno": "📞",       "semcontato": "⚠️"}
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">'
            f'<span style="font-family:Syne,sans-serif;font-weight:700;font-size:16px">🔔 Pendências do Dia</span>'
            f'<span style="background:#ef4444;color:white;font-size:12px;padding:3px 10px;border-radius:20px;font-weight:700">{len(pendencias)}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        cols_p = st.columns(min(3, len(pendencias)))
        for i, (c, _h, tipo, msg) in enumerate(pendencias[:9]):
            with cols_p[i % 3]:
                st.markdown(
                    f'<div class="pend-card" style="border-left:4px solid {cm[tipo]}">'
                    f'<div style="font-weight:700;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{im[tipo]} {c["nome"]}</div>'
                    f'<div style="font-size:12px;color:#8b94a5;margin-top:4px">{msg}</div>'
                    f'<div style="font-size:13px;color:#7cc243;margin-top:6px;font-weight:700">{fmt_moeda_plain(c["valor"])}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if role != "gestor":
                    if st.button("✏ Atender", key=f"pend_{i}_{c['id']}", width="stretch"):
                        dialog_editar(c["id"])
        st.markdown("---")

    # ── Barra de ações ────────────────────────────────────────────────────────
    _, ta, tb = st.columns([6, 1, 1])
    with ta:
        if st.button("↑ Atualizar", width="stretch", help="Recarregar dados do BigQuery"):
            st.session_state["tela"] = "importar"
            st.rerun()
    with tb:
        if clientes:
            sl   = {"pending": "Sem contato", "contacted": "Contactado", "promise": "Prometeu pagar", "negotiating": "Negociando", "paid": "Regularizado"}
            rows = []
            for c in clientes:
                h = get_hist(c["id"])
                rows.append([
                    h.get("atendente", ""), c["nome"], c.get("cnpj", ""), c["valor"],
                    c.get("parcelas", ""), c.get("vencimento", ""), c.get("dias_atraso", ""),
                    sl.get(h.get("status", "pending"), ""), h.get("lastContact", ""), h.get("notes", ""),
                    "Sim" if c.get("_tem_acordo") else "Não",
                ])
            df_exp = pd.DataFrame(rows, columns=["Atendente","Nome","CNPJ","Saldo","Competências","Vencimento","Dias Atraso","Status","Último Contato","Observações","Acordo"])
            st.download_button(
                "⬇ CSV",
                df_exp.to_csv(index=False).encode("utf-8-sig"),
                f"cobrancas_{date.today()}.csv",
                "text/csv",
                width="stretch",
                help="Exportar lista",
            )

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # ── Filtros ───────────────────────────────────────────────────────────────
    pill_status = st.pills("Status", ["Todos", "Sem contato", "Contactado", "Prometeu pagar", "Negociando"], default="Todos", key="fpills")

    grupos_disp = sorted({c.get("_grupo", "—") for c in clientes if c.get("_grupo") and c.get("_grupo") not in ("—", "")})
    fc1, fc2, fc3, fc4, fc5, fc6 = st.columns([1.6, 1.3, 1.1, 1.2, 1.4, 1.3])
    with fc1:
        ordenar = st.selectbox("Ordenar por", list(SORT_MAP.keys()), key="fordenar")
    with fc2:
        filtro_grupo = st.selectbox("Grupo", ["Todos"] + grupos_disp, key="fgrupo")
    with fc3:
        filtro_situacao = st.selectbox("Situação", ["Todos", "Ativos", "Inativos"], key="fsituacao")
    with fc4:
        filtro_atraso = st.selectbox("Dias de atraso", ["Todos", "1-30 dias", "31-60 dias", "61-90 dias", "+90 dias"], key="fatraso")
    with fc5:
        filtro_valor = st.selectbox("Valor em aberto", ["Todos", "Até R$500", "R$500-R$2k", "R$2k-R$5k", "Acima R$5k"], key="fvalor")
    with fc6:
        filtro_acordo = st.selectbox("Acordo", ["Todos", "Com acordo", "Sem acordo"], key="facordo")

    busca = st.text_input("Buscar", placeholder="Buscar por nome ou CNPJ...", label_visibility="collapsed", key="busca")

    filtro_status = pill_status or "Todos"

    if not clientes:
        st.info("Nenhum dado. Use ↑ Atualizar para importar as planilhas.")
        return

    # ── Aplicar filtros ───────────────────────────────────────────────────────
    df = pd.DataFrame(clientes)
    df["_status"]      = df["id"].apply(lambda i: get_hist(i).get("status",      "pending"))
    df["_lastContact"] = df["id"].apply(lambda i: get_hist(i).get("lastContact", ""))
    df["_atendente"]   = df["id"].apply(lambda i: get_hist(i).get("atendente",   ""))
    df["_notes"]       = df["id"].apply(lambda i: get_hist(i).get("notes",       ""))
    df = df[df["_status"] != "paid"]

    if busca:
        mask = df.apply(lambda r: busca.lower() in str(r.get("nome", "")).lower() or busca.lower() in str(r.get("cnpj", "")).lower(), axis=1)
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
    if filtro_valor == "Até R$500":
        df = df[df["valor"] <= 500]
    elif filtro_valor == "R$500-R$2k":
        df = df[(df["valor"] > 500) & (df["valor"] <= 2000)]
    elif filtro_valor == "R$2k-R$5k":
        df = df[(df["valor"] > 2000) & (df["valor"] <= 5000)]
    elif filtro_valor == "Acima R$5k":
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

    sort_icons     = {"dias_atraso": "Atraso", "valor": "Saldo", "nome": "Cliente"}
    sort_active    = f'{sort_icons.get(sort_col_name, "")} {"↑" if sort_asc else "↓"}'
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
        f'<span style="font-size:14px;color:#6b7280"><b style="color:#e8eaf0;font-size:15px">{total_f}</b> clientes encontrados</span>'
        f'<span style="font-size:11px;color:#4b5563;background:#181c26;border:1px solid #1e2333;padding:4px 10px;border-radius:6px">Ordenado por: <b style="color:#8b94a5">{sort_active}</b></span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Tabela ────────────────────────────────────────────────────────────────
    has_edit = (role != "gestor")
    col_w    = [3, 1.5, 1, 1, 1.5, 1.5, 1.5] + ([0.8] if has_edit else [])
    hdrs_t   = ["Cliente", "Saldo devedor", "Atraso", "Histórico", "Telefone", "Grupo", "Último Contato"] + ([""] if has_edit else [])

    hdr_cells = "".join(
        f'<div style="flex:{w};padding:14px 14px;font-size:12px;text-transform:uppercase;'
        f'letter-spacing:1.2px;color:#8b94a5;font-weight:700;white-space:nowrap;min-width:0">{h}</div>'
        for w, h in zip(col_w, hdrs_t)
    )
    st.markdown(
        f'<div style="display:flex;gap:1rem;background:#1e2333;border:1px solid #2a2f42;'
        f'border-radius:12px 12px 0 0;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)">{hdr_cells}</div>',
        unsafe_allow_html=True,
    )

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

            rcols = st.columns(col_w)
            with rcols[0]:
                atend_tag = f'<span style="font-size:11px;color:#8b94a5;margin-left:4px;font-weight:500">· {row["_atendente"]}</span>' if row["_atendente"] else ""
                st.markdown(
                    f'<div style="padding:12px 12px;{row_bg}{row_bl}">'
                    f'<div style="margin-bottom:3px">{tags}</div>'
                    f'<div style="font-weight:600;font-size:16px;color:#e8eaf0;line-height:1.3">{row["nome"]}{obs_icon}</div>'
                    f'<div style="color:#8b94a5;font-size:13px;margin-top:2px;font-weight:500">{row.get("cnpj","")}{atend_tag}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with rcols[1]:
                st.markdown(f'<div style="padding:12px 12px;font-size:15px;font-weight:600">{fmt_moeda(row["valor"])}</div>', unsafe_allow_html=True)
            with rcols[2]:
                st.markdown(f'<div style="padding:12px 12px;font-size:12px">{dias_html(row.get("dias_atraso"))}</div>', unsafe_allow_html=True)
            with rcols[3]:
                m = int(row.get("_meses_atraso") or 0)
                cor_m = "#ef4444" if m >= 9 else ("#f97316" if m >= 5 else "#f59e0b")
                st.markdown(
                    f'<div style="padding:12px 12px">'
                    f'<span style="color:{cor_m};font-weight:700;font-size:14px">{m}</span>'
                    f'<span style="color:#8b94a5;font-size:13px">/12</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with rcols[4]:
                st.markdown(f'<div style="padding:12px 12px;font-size:14px;color:#8b94a5">{row.get("telefone","—")}</div>', unsafe_allow_html=True)
            with rcols[5]:
                st.markdown(f'<div style="padding:12px 12px;font-size:14px;color:#8b94a5">{row.get("_grupo","—")}</div>', unsafe_allow_html=True)
            with rcols[6]:
                st.markdown(f'<div style="padding:12px 12px;font-size:14px;color:#8b94a5">{row["_lastContact"] or "—"}</div>', unsafe_allow_html=True)
            if has_edit:
                with rcols[7]:
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
