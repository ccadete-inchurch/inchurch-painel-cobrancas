from datetime import datetime, date
import streamlit as st

from config import STATUS_OPTS
from auth import get_store, current_nome, current_email, current_role
from helpers import get_hist, get_hist_unificado, save_hist, fmt_moeda_plain, dias_html


@st.dialog("✏ Editar Registro", width="large")
def dialog_editar(eid):
    store   = get_store()
    cliente = next((c for c in store["clientes"] if c["id"] == eid), None)
    if not cliente:
        st.error("Cliente não encontrado.")
        return

    # Admin/gestor vê o registro como está salvo no histórico das atendentes
    # (modo read-only). Atendente vê o próprio histórico (modo edição).
    role = current_role()
    somente_leitura = role in ("admin", "gestor")
    h = get_hist_unificado(eid) if somente_leitura else get_hist(eid)
    if somente_leitura:
        st.info("👁 Modo visualização")

    # Cabeçalho informativo
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-left:6px;vertical-align:middle">INATIVO</span>' if cliente.get("_inativo") else ""
        st.markdown(f'<div class="dialog-info"><div class="dialog-info-label">Cliente</div><div class="dialog-info-value" style="font-size:16px">{cliente["nome"]}{inativo_badge}</div><div style="font-size:12px;color:#8b94a5;margin-top:3px">{cliente.get("cnpj","—")}</div></div>', unsafe_allow_html=True)
    with c2:
        parcelas = cliente.get("parcelas", len(cliente.get("_cobracas", [])))
        st.markdown(f'<div class="dialog-info"><div class="dialog-info-label">Saldo em aberto</div><div class="dialog-info-value" style="font-size:16px;color:#7cc243">{fmt_moeda_plain(cliente["valor"])}</div><div style="font-size:12px;color:#8b94a5;margin-top:3px">{parcelas} parcela{"s" if parcelas != 1 else ""} em atraso</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="dialog-info"><div class="dialog-info-label">Vencimento</div><div class="dialog-info-value" style="font-size:16px">{cliente.get("vencimento","—")}</div><div style="font-size:12px;color:#8b94a5;margin-top:3px">{dias_html(cliente.get("dias_atraso"))}</div></div>', unsafe_allow_html=True)
    with c4:
        # Todos os telefones do cliente — primeiro destacado, demais inline
        # em fonte menor (igual aos cards). Todos selecionáveis/copiáveis.
        tels = cliente.get("telefones") or ([cliente.get("telefone")] if cliente.get("telefone") else [])
        tels = [t for t in tels if t]
        if not tels:
            tel_principal_html = "—"
            tel_extras_html    = "&nbsp;"
        elif len(tels) == 1:
            tel_principal_html = tels[0]
            tel_extras_html    = "&nbsp;"
        else:
            tel_principal_html = tels[0]
            tel_extras_html    = " · ".join(tels[1:])
        st.markdown(
            f'<div class="dialog-info">'
            f'<div class="dialog-info-label">Telefone{"s" if len(tels) > 1 else ""}</div>'
            f'<div class="dialog-info-value" style="font-size:16px">{tel_principal_html}</div>'
            f'<div style="font-size:12px;color:#8b94a5;margin-top:3px">{tel_extras_html}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # Cobranças inadimplentes
    st.markdown(
        '<div style="font-size:13px;font-weight:700;color:#8b94a5;letter-spacing:1.2px;'
        'text-transform:uppercase;margin:14px 0 10px 0">Cobranças Inadimplentes</div>',
        unsafe_allow_html=True,
    )
    cobracas_inad = sorted(
        [c for c in cliente.get("_cobracas", []) if c["dias_atraso"] and c["dias_atraso"] > 0],
        key=lambda c: c["dias_atraso"],
        reverse=True,
    )

    def _render_cobranca_row(cob):
        return (
            f'<div style="background:#1e2333;border:1px solid #2a2f42;border-radius:8px;'
            f'padding:12px 16px;margin-bottom:6px;display:flex;align-items:center;'
            f'justify-content:space-between;gap:16px">'
            f'<div style="display:flex;flex-direction:column;min-width:0">'
            f'<div style="font-size:17px;font-weight:700;color:#e8eaf0;'
            f'font-variant-numeric:tabular-nums">{fmt_moeda_plain(cob["valor"])}</div>'
            f'<div style="font-size:12px;color:#8b94a5;margin-top:2px">Vence {cob["vencimento"]}</div>'
            f'</div>'
            f'<div style="display:flex;align-items:center;gap:10px;flex-shrink:0">'
            f'<span style="color:#ef4444;font-weight:700;font-size:14px;'
            f'font-variant-numeric:tabular-nums">{cob["dias_atraso"]}d</span>'
            f'<span style="background:#ff5555;color:#fff;padding:4px 8px;'
            f'border-radius:4px;font-size:12px;font-weight:600">INADIMPLENTE</span>'
            f'</div>'
            f'</div>'
        )

    if cobracas_inad:
        visiveis = cobracas_inad[:3]
        extras   = cobracas_inad[3:]
        st.markdown("".join(_render_cobranca_row(c) for c in visiveis), unsafe_allow_html=True)
        if extras:
            with st.expander(f"Ver mais {len(extras)} parcela{'s' if len(extras) > 1 else ''}"):
                st.markdown("".join(_render_cobranca_row(c) for c in extras), unsafe_allow_html=True)
    else:
        st.info("Nenhuma cobrança em atraso")

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # Campos (desabilitados se admin/gestor — modo só leitura)
    status_sel = st.selectbox(
        "Status de Cobrança",
        list(STATUS_OPTS.keys()),
        index=list(STATUS_OPTS.values()).index(h.get("status", "pending")),
        disabled=somente_leitura,
    )

    d1, d2 = st.columns(2)
    with d1:
        last_contact = st.date_input(
            "Último Contato",
            value=datetime.strptime(h["lastContact"], "%d/%m/%Y").date() if h.get("lastContact") else date.today(),
            disabled=somente_leitura,
        )
    with d2:
        tem_retorno = st.checkbox("Agendar retorno", value=bool(h.get("retorno")), disabled=somente_leitura)
        retorno = None
        if tem_retorno:
            retorno = st.date_input(
                "Data de retorno",
                value=datetime.strptime(h["retorno"], "%d/%m/%Y").date() if h.get("retorno") else date.today(),
                label_visibility="collapsed",
                disabled=somente_leitura,
            )

    promise_date = None
    if STATUS_OPTS[status_sel] == "promise":
        promise_date = st.date_input(
            "Data que prometeu pagar",
            value=datetime.strptime(h["promiseDate"], "%d/%m/%Y").date() if h.get("promiseDate") else date.today(),
            disabled=somente_leitura,
        )

    notes = st.text_area("Observações", value=h.get("notes", ""), placeholder="Ex: Cliente pediu prazo até sexta...", height=100, disabled=somente_leitura)
    # Linha "Editado por" só faz sentido em modo edição
    if not somente_leitura:
        st.markdown(f'<div style="font-size:12px;color:#8b94a5;margin-top:6px;font-weight:500">Editado por: <span style="color:#e8eaf0;font-weight:700">{current_nome()}</span></div>', unsafe_allow_html=True)
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # Detecta se cliente está fixado (promise vencida OU retorno vencido)
    # pra exibir o botão Concluir junto com Salvar/Cancelar.
    from datetime import date as _d
    from helpers import parse_date_br
    hoje = _d.today()
    eh_fixado = False
    if h.get("status") == "promise" and h.get("promiseDate"):
        d = parse_date_br(h["promiseDate"])
        eh_fixado = bool(d and d <= hoje)
    if not eh_fixado and h.get("retorno"):
        d = parse_date_br(h["retorno"])
        eh_fixado = bool(d and d <= hoje)

    # Monta lista de botões dinamicamente baseado em role + se é fixado.
    botoes = []
    if not somente_leitura:
        botoes.append("salvar")
    if eh_fixado:
        botoes.append("concluir")
    botoes.append("cancelar")

    cols = st.columns(len(botoes))
    for col, acao in zip(cols, botoes):
        with col:
            if acao == "salvar":
                if st.button("💾 Salvar alterações", width="stretch"):
                    new = STATUS_OPTS[status_sel]
                    from data import _EMAIL_GRUPO
                    payload = {
                        "status":      new,
                        "lastContact": last_contact.strftime("%d/%m/%Y"),
                        "retorno":     retorno.strftime("%d/%m/%Y") if retorno else "",
                        "promiseDate": promise_date.strftime("%d/%m/%Y") if promise_date else "",
                        "notes":       notes,
                    }
                    if current_email() in _EMAIL_GRUPO:
                        payload["atendente"] = current_nome()
                    save_hist(eid, payload)
                    st.toast(f"✅ {cliente['nome']} salvo!", icon="✅")
                    st.rerun()
            elif acao == "concluir":
                if st.button("✅ Concluir fixado", width="stretch", type="primary",
                             help="Apaga promessa/retorno; status 'promise' → 'contacted'"):
                    from data import concluir_pendencia
                    concluir_pendencia(eid)
                    st.toast(f"✅ {cliente['nome']} concluído", icon="✅")
                    st.rerun()
            elif acao == "cancelar":
                rotulo = "✕ Fechar" if somente_leitura else "✕ Cancelar"
                if st.button(rotulo, width="stretch"):
                    st.rerun()
