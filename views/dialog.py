from datetime import datetime, date
import streamlit as st

from config import STATUS_OPTS
from auth import get_store, current_nome
from helpers import get_hist, save_hist, fmt_moeda_plain, dias_html


@st.dialog("📝 Anotar", width="large")
def dialog_anotar(eid):
    store   = get_store()
    cliente = next((c for c in store["clientes"] if c["id"] == eid), None)
    if not cliente:
        st.error("Cliente não encontrado.")
        return

    h = get_hist(eid)

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
        st.markdown(f'<div class="dialog-info"><div class="dialog-info-label">Telefone</div><div class="dialog-info-value" style="font-size:16px">{cliente.get("telefone","—")}</div><div style="font-size:12px;color:#8b94a5;margin-top:3px">&nbsp;</div></div>', unsafe_allow_html=True)

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # Cobranças inadimplentes
    st.markdown("### 📋 Cobranças Inadimplentes")
    cobracas_inad = sorted([c for c in cliente.get("_cobracas", []) if c["dias_atraso"] and c["dias_atraso"] > 0], key=lambda c: c["dias_atraso"])
    if cobracas_inad:
        visiveis = cobracas_inad[:3]
        extras   = cobracas_inad[3:]
        for cob in visiveis:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns(4)
                with c1: st.markdown(f"**Valor:** {fmt_moeda_plain(cob['valor'])}")
                with c2: st.markdown(f"**Vencimento:** {cob['vencimento']}")
                with c3: st.markdown(f"**Atraso:** {cob['dias_atraso']}d")
                with c4: st.markdown('<span style="background:#ff5555;color:#fff;padding:4px 8px;border-radius:4px;font-size:12px;font-weight:600">INADIMPLENTE</span>', unsafe_allow_html=True)
        if extras:
            with st.expander(f"Ver mais {len(extras)} parcela{'s' if len(extras) > 1 else ''}"):
                for cob in extras:
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns(4)
                        with c1: st.markdown(f"**Valor:** {fmt_moeda_plain(cob['valor'])}")
                        with c2: st.markdown(f"**Vencimento:** {cob['vencimento']}")
                        with c3: st.markdown(f"**Atraso:** {cob['dias_atraso']}d")
                        with c4: st.markdown('<span style="background:#ff5555;color:#fff;padding:4px 8px;border-radius:4px;font-size:12px;font-weight:600">INADIMPLENTE</span>', unsafe_allow_html=True)
    else:
        st.info("Nenhuma cobrança em atraso")

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # Só observação e retorno — não altera status nem lastContact
    notes = st.text_area("Observações", value=h.get("notes", ""), placeholder="Ex: Cliente pediu prazo até sexta...", height=100)

    tem_retorno = st.checkbox("Agendar retorno", value=bool(h.get("retorno")))
    retorno = None
    if tem_retorno:
        retorno = st.date_input(
            "Data de retorno",
            value=datetime.strptime(h["retorno"], "%d/%m/%Y").date() if h.get("retorno") else date.today(),
            label_visibility="collapsed",
        )

    st.markdown(f'<div style="font-size:12px;color:#8b94a5;margin-top:6px;font-weight:500">Atendente: <span style="color:#e8eaf0;font-weight:700">{current_nome()}</span></div>', unsafe_allow_html=True)
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    b1, b2 = st.columns(2)
    with b1:
        if st.button("💾 Salvar nota", width="stretch"):
            save_hist(eid, {
                **h,
                "notes":   notes,
                "retorno": retorno.strftime("%d/%m/%Y") if retorno else "",
            })
            st.toast(f"✅ Nota salva!", icon="✅")
            st.rerun()
    with b2:
        if st.button("✕ Cancelar", width="stretch"):
            st.rerun()


@st.dialog("✏ Editar Registro", width="large")
def dialog_editar(eid):
    store   = get_store()
    cliente = next((c for c in store["clientes"] if c["id"] == eid), None)
    if not cliente:
        st.error("Cliente não encontrado.")
        return

    h = get_hist(eid)

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
        st.markdown(f'<div class="dialog-info"><div class="dialog-info-label">Telefone</div><div class="dialog-info-value" style="font-size:16px">{cliente.get("telefone","—")}</div><div style="font-size:12px;color:#8b94a5;margin-top:3px">&nbsp;</div></div>', unsafe_allow_html=True)

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # Cobranças inadimplentes
    st.markdown("### 📋 Cobranças Inadimplentes")
    cobracas_inad = sorted([c for c in cliente.get("_cobracas", []) if c["dias_atraso"] and c["dias_atraso"] > 0], key=lambda c: c["dias_atraso"])
    if cobracas_inad:
        visiveis = cobracas_inad[:3]
        extras   = cobracas_inad[3:]
        for cob in visiveis:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns(4)
                with c1: st.markdown(f"**Valor:** {fmt_moeda_plain(cob['valor'])}")
                with c2: st.markdown(f"**Vencimento:** {cob['vencimento']}")
                with c3: st.markdown(f"**Atraso:** {cob['dias_atraso']}d")
                with c4: st.markdown('<span style="background:#ff5555;color:#fff;padding:4px 8px;border-radius:4px;font-size:12px;font-weight:600">INADIMPLENTE</span>', unsafe_allow_html=True)
        if extras:
            with st.expander(f"Ver mais {len(extras)} parcela{'s' if len(extras) > 1 else ''}"):
                for cob in extras:
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns(4)
                        with c1: st.markdown(f"**Valor:** {fmt_moeda_plain(cob['valor'])}")
                        with c2: st.markdown(f"**Vencimento:** {cob['vencimento']}")
                        with c3: st.markdown(f"**Atraso:** {cob['dias_atraso']}d")
                        with c4: st.markdown('<span style="background:#ff5555;color:#fff;padding:4px 8px;border-radius:4px;font-size:12px;font-weight:600">INADIMPLENTE</span>', unsafe_allow_html=True)
    else:
        st.info("Nenhuma cobrança em atraso")

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # Campos editáveis
    status_sel = st.selectbox(
        "Status de Cobrança",
        list(STATUS_OPTS.keys()),
        index=list(STATUS_OPTS.values()).index(h.get("status", "pending")),
    )

    d1, d2 = st.columns(2)
    with d1:
        last_contact = st.date_input(
            "Último Contato",
            value=datetime.strptime(h["lastContact"], "%d/%m/%Y").date() if h.get("lastContact") else date.today(),
        )
    with d2:
        tem_retorno = st.checkbox("Agendar retorno", value=bool(h.get("retorno")))
        retorno = None
        if tem_retorno:
            retorno = st.date_input(
                "Data de retorno",
                value=datetime.strptime(h["retorno"], "%d/%m/%Y").date() if h.get("retorno") else date.today(),
                label_visibility="collapsed",
            )

    promise_date = None
    if STATUS_OPTS[status_sel] == "promise":
        promise_date = st.date_input(
            "Data que prometeu pagar",
            value=datetime.strptime(h["promiseDate"], "%d/%m/%Y").date() if h.get("promiseDate") else date.today(),
        )

    notes = st.text_area("Observações", value=h.get("notes", ""), placeholder="Ex: Cliente pediu prazo até sexta...", height=100)
    st.markdown(f'<div style="font-size:12px;color:#8b94a5;margin-top:6px;font-weight:500">Atendente: <span style="color:#e8eaf0;font-weight:700">{current_nome()}</span></div>', unsafe_allow_html=True)
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    b1, b2 = st.columns(2)
    with b1:
        if st.button("💾 Salvar alterações", width="stretch"):
            new = STATUS_OPTS[status_sel]
            save_hist(eid, {
                "status":      new,
                "lastContact": last_contact.strftime("%d/%m/%Y"),
                "retorno":     retorno.strftime("%d/%m/%Y") if retorno else "",
                "promiseDate": promise_date.strftime("%d/%m/%Y") if promise_date else "",
                "notes":       notes,
                "atendente":   current_nome(),
            })
            st.toast(f"✅ {cliente['nome']} salvo!", icon="✅")
            st.rerun()
    with b2:
        if st.button("✕ Cancelar", width="stretch"):
            st.rerun()
