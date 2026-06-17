from datetime import datetime, date
import streamlit as st

from config import STATUS_OPTS
from auth import get_store, current_nome, current_email, current_role
from helpers import get_hist, get_hist_unificado, save_hist, fmt_moeda_plain, dias_html


@st.dialog("Editar Registro", width="large")
def dialog_editar(eid):
    store   = get_store()
    cliente = next((c for c in store["clientes"] if c["id"] == eid), None)
    if not cliente:
        st.error("Cliente não encontrado.")
        return

    # CSS local do dialog:
    # - Limita o width a 760px (entre 'small' apertado e 'large' enorme em
    #   notebooks). 'large' nativo do streamlit ocupa quase tudo da tela.
    # - Reduz o tamanho do título "Editar Registro" pra subir o conteúdo.
    # - Estiliza o botão primário (Concluir fixado) verde escuro+branco.
    # - Remove o border padrão do st.expander dentro do dialog.
    # - Force min-height nos cards do header pra ficarem iguais (a
    #   cascata via stretch falhou em alguns DOMs do streamlit; min-height
    #   é a abordagem robusta).
    st.markdown("""
    <style>
    div[role="dialog"]{
        max-width:760px !important;
        width:90vw !important;
    }
    /* Título "Editar Registro" menor pra economizar espaço vertical */
    div[role="dialog"] h2,
    div[role="dialog"] h1,
    div[role="dialog"] [data-testid="stDialogHeader"] *{
        font-size:20px !important;
        font-weight:700 !important;
    }
    /* Reduz o gap entre o header do dialog (título + X) e o conteúdo —
       era ~40px de respiro, sobra muito espaço vazio. */
    div[role="dialog"] [data-testid="stDialogHeader"]{
        padding-bottom:8px !important;
        margin-bottom:0 !important;
    }
    div[role="dialog"] [data-testid="stDialogBody"]{
        padding-top:8px !important;
    }
    div[role="dialog"] button[kind="primary"]{
        background-color:#4a8a2c !important;
        border:1px solid #4a8a2c !important;
        color:#ffffff !important;
    }
    div[role="dialog"] button[kind="primary"]:hover{
        background-color:#3d731f !important;
        border-color:#3d731f !important;
    }
    div[role="dialog"] [data-testid="stExpander"] details{
        border:none !important;
        background:transparent !important;
    }
    div[role="dialog"] [data-testid="stExpander"] details summary{
        color:#8b94a5 !important;
        font-size:13px !important;
        padding:6px 0 !important;
        background:transparent !important;
    }
    div[role="dialog"] [data-testid="stExpander"] details summary:hover{
        color:#e8eaf0 !important;
    }
    div[role="dialog"] [data-testid="stExpander"] details > div{
        padding:6px 0 0 0 !important;
        background:transparent !important;
        border:none !important;
    }
    /* Min-height força os 4 cards do header a terem altura igual.
       Cascata via align-items:stretch é flaky no DOM do streamlit. */
    div[role="dialog"] .dialog-info{
        min-height:130px !important;
        display:flex !important;
        flex-direction:column !important;
        justify-content:flex-start !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Admin vê o registro como está salvo no histórico das atendentes
    # (modo read-only). Atendente vê o próprio histórico (modo edição).
    role = current_role()
    somente_leitura = role == "admin"
    h = get_hist_unificado(eid) if somente_leitura else get_hist(eid)
    if somente_leitura:
        # Texto puro em azul — sem retângulo de fundo (econômico em espaço
        # vertical e visualmente discreto). Só aparece pra admin.
        st.markdown(
            '<div style="color:#5fa3ff;font-size:13px;font-weight:500;'
            'margin:0 0 10px 0">👁 Modo visualização</div>',
            unsafe_allow_html=True,
        )

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
    )

    def _render_cobranca_row(cob):
        # Linha compacta single-row: economiza ~50% de altura comparado ao
        # card de 2 linhas. Cliente com 18 parcelas (caso real visto) cabe
        # sem dialog gigante. min-width fixo no "Atraso" e badge garante
        # que valores diferentes (23d vs 112d) não desalinhem visualmente.
        # Fundo #13161f (mesmo do .dialog-info) — antes estava #1e2333
        # mais claro, destoava do resto do dialog.
        return (
            f'<div style="background:#13161f;border:1px solid #1e2333;border-radius:8px;'
            f'padding:10px 14px;margin-bottom:6px;display:flex;align-items:center;'
            f'justify-content:space-between;gap:12px;font-size:14px">'
            f'<div style="display:flex;align-items:baseline;gap:10px;min-width:0">'
            f'<span style="font-weight:700;color:#e8eaf0;font-variant-numeric:tabular-nums">'
            f'{fmt_moeda_plain(cob["valor"])}</span>'
            f'<span style="color:#8b94a5;font-size:12px">Vence {cob["vencimento"]}</span>'
            f'</div>'
            f'<div style="display:flex;align-items:center;gap:12px;flex-shrink:0">'
            f'<span style="color:#e8eaf0;font-variant-numeric:tabular-nums;'
            f'min-width:85px;text-align:right">'
            f'<span style="color:#8b94a5">Atraso:</span> <strong>{cob["dias_atraso"]}d</strong></span>'
            f'<span style="background:#ff5555;color:#fff;padding:3px 8px;'
            f'border-radius:4px;font-size:11px;font-weight:600;'
            f'min-width:95px;text-align:center;display:inline-block">INADIMPLENTE</span>'
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

    # Campos (desabilitados se admin — modo só leitura)
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
                if st.button("Concluir fixado", width="stretch", type="primary",
                             help="Apaga promessa/retorno; status 'promise' → 'contacted'"):
                    from data import concluir_pendencia
                    concluir_pendencia(eid)
                    st.toast(f"{cliente['nome']} concluído", icon="✅")
                    st.rerun()
            elif acao == "cancelar":
                rotulo = "✕ Fechar" if somente_leitura else "✕ Cancelar"
                if st.button(rotulo, width="stretch"):
                    st.rerun()
