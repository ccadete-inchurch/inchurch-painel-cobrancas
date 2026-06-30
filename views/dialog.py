from datetime import datetime, date
import streamlit as st

from config import STATUS_OPTS
from auth import get_store, current_nome, current_email, current_role
from helpers import get_hist, get_hist_unificado, save_hist, fmt_moeda_plain, dias_html


@st.dialog("Editar Registro", width="large")
def dialog_editar(eid, from_fixados: bool = False):
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
    /* Título "Editar Registro" menor + reset agressivo de spacing.
       Streamlit injeta margin/padding em vários níveis (header, h1/h2,
       body container, primeiro filho do body). Reset todos pra eliminar
       o gap grande entre título e o conteúdo. */
    div[role="dialog"] h1,
    div[role="dialog"] h2,
    div[role="dialog"] h3{
        font-size:20px !important;
        font-weight:700 !important;
        margin:0 !important;
        padding:0 !important;
        line-height:1.3 !important;
    }
    div[role="dialog"] header,
    div[role="dialog"] [data-testid="stDialogHeader"]{
        padding:12px 16px 6px 16px !important;
        margin:0 !important;
        min-height:auto !important;
    }
    div[role="dialog"] [data-testid="stDialogBody"]{
        padding-top:6px !important;
        margin-top:0 !important;
    }
    div[role="dialog"] [data-testid="stDialogBody"] > div:first-child{
        margin-top:0 !important;
        padding-top:0 !important;
    }
    /* stVerticalBlock dentro do body — gap menor entre elementos */
    div[role="dialog"] [data-testid="stDialogBody"] [data-testid="stVerticalBlock"]{
        gap:0.5rem !important;
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
    # Admin pode ativar "Visualizar como atendente" na sidebar pra testar
    # a UX (interagir com checkboxes/botoes). Edicoes salvam no proprio
    # historico do admin, nao das atendentes.
    role = current_role()
    _admin_test_mode = bool(st.session_state.get("_admin_view_as_atendente", False))
    somente_leitura = role == "admin" and not _admin_test_mode
    h = get_hist_unificado(eid) if somente_leitura else get_hist(eid)
    if somente_leitura:
        # Texto puro em azul — sem retângulo de fundo (econômico em espaço
        # vertical e visualmente discreto). Só aparece pra admin.
        st.markdown(
            '<div style="color:#5fa3ff;font-size:13px;font-weight:500;'
            'margin:0 0 10px 0">👁 Modo visualização</div>',
            unsafe_allow_html=True,
        )
    elif role == "admin" and _admin_test_mode:
        # Admin em modo teste — banner amarelo de alerta. Avisa que
        # edicoes vao pro historico do admin, nao das atendentes.
        st.markdown(
            '<div style="background:rgba(245,158,11,.12);border:1px solid '
            'rgba(245,158,11,.35);color:#f59e0b;font-size:12px;font-weight:600;'
            'padding:8px 12px;border-radius:6px;margin:0 0 10px 0">'
            '🧪 <strong>MODO TESTE</strong> · Voce esta vendo o dialog como '
            'uma atendente. Mudancas salvam no historico do admin, nao das '
            'atendentes. Desative em "Teste" no sidebar pra voltar ao modo '
            'visualizacao.'
            '</div>',
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

    # vertical_alignment='bottom' faz Streamlit empurrar o conteudo de cada
    # coluna pro RODAPE da linha. Resultado: o date picker de Ultimo Contato
    # (d1) e o date picker de Data de retorno (d2, quando aparece) ficam
    # alinhados na mesma altura — o "label" / "checkbox" acima fica empurrado
    # pro topo da coluna.
    d1, d2, d3 = st.columns(3, vertical_alignment="bottom")
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
    with d3:
        # Caracteristica do canal de contato (independente do status de cobranca).
        # Quando marcado, lote forca bucket=ligacao (sem msg) e botoes
        # 'Atendeu' / 'Nao atendeu' aparecem abaixo pra registro manual da
        # ligacao (N8N nao detecta atividade em telefone fixo).
        tel_fixo = st.checkbox(
            "Telefone fixo",
            value=bool(h.get("tel_fixo", False)),
            disabled=somente_leitura,
            help="Cliente só atende em telefone fixo (sem WhatsApp). "
                 "Força o lote a colocar em LIGAÇÃO e habilita botões "
                 "manuais (Atendeu / Não atendeu) no rodapé.",
        )


    # CSS pra 'Nao atendeu' vermelho — coluna marcada com data-naoatend.
    # Botoes Atendeu/Nao atendeu agora estao no rodape do dialog,
    # nao mais numa box no meio (reduz poluicao visual).
    # IMPORTANTE: tambem esconde o stElementContainer do marker (que tem
    # padding/margin e desalinha o botao 'Nao atendeu' verticalmente
    # em relacao ao 'Atendeu' da coluna ao lado).
    if tel_fixo and not somente_leitura:
        st.markdown("""
        <style>
        /* Esconde o wrapper do marker pra nao tomar espaco vertical */
        div[role="dialog"] div[data-testid="stElementContainer"]:has(div[data-naoatend]) {
            display: none !important;
        }
        div[role="dialog"] div[data-testid="stColumn"]:has(div[data-naoatend]) button {
            background-color: #ff5555 !important;
            border-color: #ff5555 !important;
            color: #ffffff !important;
        }
        div[role="dialog"] div[data-testid="stColumn"]:has(div[data-naoatend]) button:hover {
            background-color: #d94040 !important;
            border-color: #d94040 !important;
        }
        </style>
        """, unsafe_allow_html=True)

    promise_date = None
    if STATUS_OPTS[status_sel] == "promise":
        promise_date = st.date_input(
            "Data que prometeu pagar",
            value=datetime.strptime(h["promiseDate"], "%d/%m/%Y").date() if h.get("promiseDate") else date.today(),
            disabled=somente_leitura,
        )

    notes = st.text_area("Observações", value=h.get("notes", ""), placeholder="Ex: Cliente pediu prazo até sexta...", height=100, disabled=somente_leitura)

    # ── AUTO-SAVE de TODOS os campos (incluindo notes) ───────────────────
    # Status, datas, checkboxes e notes salvam automaticamente quando
    # atendente MUDA o valor (vs o EXPECTED DEFAULT que o widget renderiza
    # ao abrir). Notes salva no blur do textarea (Streamlit rerun apos
    # perder foco) — nao a cada keystroke.
    #
    # Por que comparar com EXPECTED em vez de h: o widget de data defaulta
    # pra HOJE quando h.lastContact e' vazio. Sem essa normalizacao, abrir
    # o dialog ja disparava auto-save (curr=hoje != orig="") e o card
    # mudava de posicao no kanban por mudanca de score.
    if not somente_leitura:
        _today_str = date.today().strftime("%d/%m/%Y")
        _expected_last_contact = h.get("lastContact") or _today_str
        _expected_retorno = h.get("retorno") or ""
        _expected_promise = h.get("promiseDate") or ""
        _expected_tel_fixo = bool(h.get("tel_fixo", False))
        _expected_status = h.get("status", "pending")
        _expected_notes = h.get("notes", "")

        _curr_last_contact = last_contact.strftime("%d/%m/%Y") if last_contact else ""
        _curr_retorno = retorno.strftime("%d/%m/%Y") if retorno else ""
        _curr_promise = promise_date.strftime("%d/%m/%Y") if promise_date else ""
        _curr_status = STATUS_OPTS[status_sel]

        _mudou = (
            _curr_status != _expected_status
            or _curr_last_contact != _expected_last_contact
            or _curr_retorno != _expected_retorno
            or _curr_promise != _expected_promise
            or bool(tel_fixo) != _expected_tel_fixo
            or notes != _expected_notes
        )
        if _mudou:
            from data import _EMAIL_GRUPO as _EG
            _autosave_payload = {
                "status":      _curr_status,
                "lastContact": _curr_last_contact,
                "retorno":     _curr_retorno,
                "promiseDate": _curr_promise,
                "tel_fixo":    bool(tel_fixo),
                "notes":       notes,
            }
            if current_email() in _EG:
                _autosave_payload["atendente"] = current_nome()
            save_hist(eid, _autosave_payload)
            st.toast("Alterações salvas")

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

    # Botoes do rodape — minimalistas. Salvar/Fechar foram removidos:
    # - Salvar: auto-save acima cuida de tudo (incluindo notes)
    # - Fechar: usar o X nativo do dialog (top-right) — redundancia
    # Atendeu / Nao atendeu so aparecem quando tel_fixo=true (registro
    # manual da ligacao no painel_tarefas_diarias).
    # Concluir fixado so quando vier de Clientes Fixados (dashboard).
    def _atualiza_session_acao_local(cid: str, atendeu: bool):
        """Atualiza session_state pra card mover de coluna instantaneamente
        (sem esperar load_cooldowns_from_painel rodar daqui ~80s)."""
        cid_str = str(cid)
        st.session_state.setdefault("_painel_acoes_hoje", {})
        st.session_state.setdefault("_painel_ultimo_contato_dias", {})
        st.session_state.setdefault("_painel_dias_lig", {})
        st.session_state.setdefault("_painel_dias_lig_tentada", {})
        _prev = dict(st.session_state["_painel_acoes_hoje"].get(cid_str, {}))
        _prev["lig"] = True
        _prev["atend"] = bool(atendeu)
        st.session_state["_painel_acoes_hoje"][cid_str] = _prev
        st.session_state["_painel_ultimo_contato_dias"][cid_str] = 0
        st.session_state["_painel_dias_lig_tentada"][cid_str] = 0
        if atendeu:
            st.session_state["_painel_dias_lig"][cid_str] = 0

    botoes = []
    if tel_fixo and not somente_leitura:
        botoes.extend(["atendeu", "naoatendeu"])
    if eh_fixado and from_fixados:
        botoes.append("concluir")

    if botoes:
        cols = st.columns(len(botoes))
        for col, acao in zip(cols, botoes):
            with col:
                if acao == "atendeu":
                    if st.button("Atendeu", width="stretch", type="primary", key="btn_fixo_atendeu"):
                        from data import _EMAIL_GRUPO, registrar_acao_manual
                        payload = {
                            "status":      STATUS_OPTS[status_sel],
                            "lastContact": last_contact.strftime("%d/%m/%Y"),
                            "retorno":     retorno.strftime("%d/%m/%Y") if retorno else "",
                            "promiseDate": promise_date.strftime("%d/%m/%Y") if promise_date else "",
                            "notes":       notes,
                            "tel_fixo":    True,
                        }
                        if current_email() in _EMAIL_GRUPO:
                            payload["atendente"] = current_nome()
                        save_hist(eid, payload)
                        _atendente_nome = _EMAIL_GRUPO.get(current_email()) or payload.get("atendente", "")
                        ok = registrar_acao_manual(eid, _atendente_nome, atendeu=True)
                        if ok:
                            _atualiza_session_acao_local(eid, atendeu=True)
                            st.toast("Ligação atendida registrada")
                        else:
                            st.toast("Cliente não está no lote de hoje — só status foi salvo")
                        st.rerun()
                elif acao == "naoatendeu":
                    # Marcador pra CSS vermelho da coluna
                    st.markdown('<div data-naoatend></div>', unsafe_allow_html=True)
                    if st.button("Não atendeu", width="stretch", key="btn_fixo_naoatendeu"):
                        from data import _EMAIL_GRUPO, registrar_acao_manual
                        payload = {
                            "status":      STATUS_OPTS[status_sel],
                            "lastContact": last_contact.strftime("%d/%m/%Y"),
                            "retorno":     retorno.strftime("%d/%m/%Y") if retorno else "",
                            "promiseDate": promise_date.strftime("%d/%m/%Y") if promise_date else "",
                            "notes":       notes,
                            "tel_fixo":    True,
                        }
                        if current_email() in _EMAIL_GRUPO:
                            payload["atendente"] = current_nome()
                        save_hist(eid, payload)
                        _atendente_nome = _EMAIL_GRUPO.get(current_email()) or payload.get("atendente", "")
                        ok = registrar_acao_manual(eid, _atendente_nome, atendeu=False)
                        if ok:
                            _atualiza_session_acao_local(eid, atendeu=False)
                            st.toast("Tentativa registrada (não atendeu)")
                        else:
                            st.toast("Cliente não está no lote de hoje — só status foi salvo")
                        st.rerun()
                elif acao == "concluir":
                    if st.button("Concluir fixado", width="stretch", type="primary",
                                 help="Apaga promessa/retorno; status 'promise' → 'contacted'"):
                        from data import concluir_pendencia
                        concluir_pendencia(eid)
                        st.toast(f"{cliente['nome']} concluído")
                        st.rerun()
