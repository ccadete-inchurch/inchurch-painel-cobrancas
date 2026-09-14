from datetime import datetime, date
import streamlit as st

from config import STATUS_OPTS
from auth import get_store, current_nome, current_email, current_role
from helpers import get_hist, get_hist_unificado, save_hist, fmt_moeda_plain, dias_html, get_effective_lastContact, get_ultimo_login, parse_date_br


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
    /* Streamlit 1.59: o dialog e' <section role="dialog"> dentro de
       [data-testid="stDialog"]. O seletor antigo era div[role="dialog"], que
       nao casa com NADA — por isso o cap de largura, o titulo menor e o
       min-height dos cards nunca pegaram e o dialog abria com 1300px.
       O wrapper vem com align-items:flex-start (cola no topo) e a section
       sem max-width/max-height: os dois precisam ser sobrescritos. */
    [data-testid="stDialog"]{
        align-items:center !important;   /* centraliza na vertical */
        padding:12px 0 !important;
    }
    /* O cap TEM que ir no div filho direto, nao so' na section: e' ele que
       pinta o fundo do painel e ancora o botao de fechar. Limitando so' a
       section, sobra um retangulo de 1300px atras dela e o X vai pro canto. */
    [data-testid="stDialog"] > div{
        max-width:900px !important;
        width:94vw !important;
        max-height:95vh !important;      /* nunca estoura a tela do notebook */
    }
    [data-testid="stDialog"] section[role="dialog"]{
        max-width:100% !important;
        width:100% !important;
        max-height:95vh !important;
        overflow-y:auto !important;      /* rolagem interna, nao da pagina */
    }
    /* Título "Editar Registro" menor + reset agressivo de spacing.
       Streamlit injeta margin/padding em vários níveis (header, h1/h2,
       body container, primeiro filho do body). Reset todos pra eliminar
       o gap grande entre título e o conteúdo. */
    [data-testid="stDialog"] h1,
    [data-testid="stDialog"] h2,
    [data-testid="stDialog"] h3{
        font-size:20px !important;
        font-weight:700 !important;
        margin:0 !important;
        padding:0 !important;
        line-height:1.3 !important;
    }
    /* O titulo e' um <h2> filho DIRETO da section — nao existe wrapper
       [data-testid="stDialogHeader"] nem <header> no 1.59, entao a regra
       seguinte tambem e' morta (fica so' por seguranca). Com o padding:0 da
       regra generica de h1/h2/h3 o titulo encostava na borda e o "E" de
       "Editar" ficava cortado; o padding-right abre espaco pro botao X. */
    [data-testid="stDialog"] section[role="dialog"] > h2{
        padding:14px 52px 2px 22px !important;
    }
    [data-testid="stDialog"] header,
    [data-testid="stDialog"] [data-testid="stDialogHeader"]{
        padding:12px 16px 6px 16px !important;
        margin:0 !important;
        min-height:auto !important;
    }
    /* stDialogBody TAMBEM nao existe no DOM do 1.59 (como div[role=dialog]
       nao existia): as duas regras abaixo miravam nele e eram codigo morto —
       era por isso que o espacamento entre blocos ficava enorme e o dialog
       exigia rolagem. Ancoradas direto no stDialog agora. */
    [data-testid="stDialog"] [data-testid="stVerticalBlock"]{
        gap:0.5rem !important;
    }
    /* Labels dos widgets (STATUS, OBSERVAÇÕES...) com respiro menor: o
       global usa margem de paragrafo e, somada em 4 widgets, custa ~60px. */
    [data-testid="stDialog"] [data-testid="stWidgetLabel"]{
        margin-bottom:2px !important;
    }
    [data-testid="stDialog"] [data-testid="stWidgetLabel"] p{
        margin-bottom:0 !important;
        line-height:1.2 !important;
    }
    [data-testid="stDialog"] button[kind="primary"]{
        background-color:#4a8a2c !important;
        border:1px solid #4a8a2c !important;
        color:#ffffff !important;
    }
    [data-testid="stDialog"] button[kind="primary"]:hover{
        background-color:#3d731f !important;
        border-color:#3d731f !important;
    }
    [data-testid="stDialog"] [data-testid="stExpander"] details{
        border:none !important;
        background:transparent !important;
    }
    [data-testid="stDialog"] [data-testid="stExpander"] details summary{
        color:#8b94a5 !important;
        font-size:13px !important;
        padding:6px 0 !important;
        background:transparent !important;
    }
    [data-testid="stDialog"] [data-testid="stExpander"] details summary:hover{
        color:#e8eaf0 !important;
    }
    [data-testid="stDialog"] [data-testid="stExpander"] details > div{
        padding:6px 0 0 0 !important;
        background:transparent !important;
        border:none !important;
    }
    /* Com 5 cards em 900px a coluna fica estreita e o label de 13px quebrava
       no meio da palavra ("VENCIMENT/O"). 11px + keep-all resolve; label de
       duas palavras ainda quebra, mas no espaco. */
    [data-testid="stDialog"] .dialog-info-label{
        font-size:11px !important;
        letter-spacing:0.8px !important;
        word-break:keep-all !important;
        overflow-wrap:normal !important;
    }
    /* Min-height força os 4 cards do header a terem altura igual.
       Cascata via align-items:stretch é flaky no DOM do streamlit. */
    /* Sem min-height: com 5 cards estreitos o conteudo cabe em ~80px e o
       104px virava espaco morto no topo — caro num dialog que ja' rola.
       align-items:stretch no bloco das colunas iguala a altura sem reservar
       espaco fixo. Padding tambem mais justo que o .dialog-info global. */
    [data-testid="stDialog"] .dialog-info{
        padding:10px 13px !important;
        display:flex !important;
        flex-direction:column !important;
        justify-content:flex-start !important;
        height:100% !important;
    }
    [data-testid="stDialog"] [data-testid="stHorizontalBlock"]{
        align-items:stretch !important;
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
    c1, c2, c3, c4, c5 = st.columns([1.9, 1.05, 1.0, 1.1, 1.25])
    with c1:
        inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-left:6px;vertical-align:middle">INATIVO</span>' if cliente.get("_inativo") else ""
        st.markdown(f'<div class="dialog-info"><div class="dialog-info-label">Cliente</div><div class="dialog-info-value" style="font-size:16px">{cliente["nome"]}{inativo_badge}</div><div style="font-size:12px;color:#8b94a5;margin-top:3px">{cliente.get("cnpj","—")}</div></div>', unsafe_allow_html=True)
    with c2:
        parcelas = cliente.get("parcelas", len(cliente.get("_cobracas", [])))
        st.markdown(f'<div class="dialog-info"><div class="dialog-info-label">Saldo em aberto</div><div class="dialog-info-value" style="font-size:16px;color:#7cc243">{fmt_moeda_plain(cliente["valor"])}</div><div style="font-size:12px;color:#8b94a5;margin-top:3px">{parcelas} parcela{"s" if parcelas != 1 else ""} em atraso</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="dialog-info"><div class="dialog-info-label">Vencimento</div><div class="dialog-info-value" style="font-size:16px">{cliente.get("vencimento","—")}</div><div style="font-size:12px;color:#8b94a5;margin-top:3px">{dias_html(cliente.get("dias_atraso"))}</div></div>', unsafe_allow_html=True)
    with c4:
        # Ultimo login da igreja no PAINEL DE CONTROLE. Nao e' acesso de membro
        # no app/site — esse e' consumo de conteudo e misturaria os vieses.
        _ul = get_ultimo_login(eid)
        if _ul["estado"] == "com_login":
            _ul_valor = _ul["data"]
            _n = _ul["dias"]
            _ul_sub = "hoje" if _n == 0 else f'há {_n} dia{"s" if _n != 1 else ""}'
        elif _ul["estado"] == "sem_login":
            _ul_valor = _ul["curto"]
            _ul_sub = "nunca acessou o painel"
        else:
            # "Nao vinculado" e nao "nao existe no produto": das 8 da carteira,
            # 4 SAO igrejas reais cujo st_sincro_sac foi preenchido com id de
            # deal do CRM ("Deal ID:3507") em vez do tertiarygroup_id. O campo
            # nao diz que a igreja nao usa o produto — diz que nao achamos ela.
            _ul_valor = "—"
            _ul_sub = "não vinculado ao produto"
        st.markdown(
            f'<div class="dialog-info"><div class="dialog-info-label">Último login painel</div>'
            f'<div class="dialog-info-value" style="font-size:16px">{_ul_valor}</div>'
            f'<div style="font-size:12px;color:#8b94a5;margin-top:3px">{_ul_sub}</div></div>',
            unsafe_allow_html=True,
        )
    with c5:
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
        # So' a mais atrasada fica visivel; o resto entra no expander. Cada
        # linha custa ~27px e cliente com muitas parcelas empurrava o dialog
        # pra fora da tela em notebook.
        visiveis = cobracas_inad[:1]
        extras   = cobracas_inad[1:]
        st.markdown("".join(_render_cobranca_row(c) for c in visiveis), unsafe_allow_html=True)
        if extras:
            with st.expander(f"Ver mais {len(extras)} parcela{'s' if len(extras) > 1 else ''}"):
                st.markdown("".join(_render_cobranca_row(c) for c in extras), unsafe_allow_html=True)
    else:
        st.info("Nenhuma cobrança em atraso")

    # Respiro antes do STATUS. Sem expander (1 parcela so') o campo colava na
    # linha da cobranca; com expander o proprio bloco ja' separava. Compensa a
    # diferenca pra os dois casos ficarem iguais.
    _tem_expander = bool(cobracas_inad) and len(cobracas_inad) > 1
    st.markdown(f'<div style="height:{4 if _tem_expander else 26}px"></div>',
                unsafe_allow_html=True)

    # Campos (desabilitados se admin — modo só leitura).
    # Dropdown de status: so DECISOES INTENCIONAIS (promise, negotiating,
    # telefone_errado, igreja_fechada). Os automaticos (pending / contacted)
    # ficam fora do dropdown — placeholder mostra que esta no modo automatico.
    _status_atual = h.get("status", "")
    _status_values = list(STATUS_OPTS.values())
    if _status_atual in _status_values:
        _status_index = _status_values.index(_status_atual)
    else:
        # pending / contacted / vazio → placeholder, nada selecionado
        _status_index = None
    # X nativo do selectbox (limpar selecao) so aparece quando 'placeholder'
    # e' passado. Restringimos ele SO pros casos onde 'limpar' faz sentido:
    #   - telefone_errado → problema resolvido no SL
    #   - igreja_fechada  → igreja reabriu
    #   - vazio/pending/contacted → estado automatico
    # Para promise/negotiating, o fluxo correto e' 'Concluir fixado' (em
    # Inadimplencia > Fixados), que tambem apaga promiseDate/retorno.
    # Se atendente clicasse X aqui pra promise, o status limparia mas
    # promiseDate ficaria orfao — cliente continuaria como fixado.
    _permite_limpar = _status_atual not in ("promise", "negotiating")
    _selectbox_kwargs = {
        "index": _status_index,
        "disabled": somente_leitura,
    }
    if _permite_limpar:
        _selectbox_kwargs["placeholder"] = "Apenas para decisões manuais"
    status_sel = st.selectbox(
        "Status de Cobrança",
        list(STATUS_OPTS.keys()),
        **_selectbox_kwargs,
    )

    # Linha 1: Ultimo Contato + Agendar retorno (2 colunas, alinhamento bottom
    # pra date pickers ficarem na mesma altura). Keys explicitas por eid pra
    # evitar reset de estado quando dialog re-renderiza no auto-save.
    d1, d2 = st.columns(2, vertical_alignment="bottom")
    with d1:
        # Ultimo Contato: exibicao read-only da data efetiva (bot + manual, o mais
        # recente entre os dois). Antes era editavel, mas nao alterava cooldown do
        # lote (fonte de confusao). Se cliente nunca foi contatado, valor=None
        # deixa o campo vazio (evita fake "hoje" que aparecia antes).
        _lc_efetivo_str = get_effective_lastContact(eid)
        _lc_efetivo_date = parse_date_br(_lc_efetivo_str) if _lc_efetivo_str else None
        st.date_input(
            "Último Contato",
            value=_lc_efetivo_date,
            disabled=True,
            format="DD/MM/YYYY",
            key=f"dlg_lc_{eid}",
        )
        # last_contact preserva o valor manual antigo do historico (ou None se
        # nunca teve). Usado abaixo pra manter o payload de salvamento intacto
        # sem sobrescrever o manual com o efetivo do bot.
        _lc_manual_str = h.get("lastContact") or ""
        last_contact = parse_date_br(_lc_manual_str) if _lc_manual_str else None
    with d2:
        tem_retorno = st.checkbox(
            "Agendar retorno",
            value=bool(h.get("retorno")),
            disabled=somente_leitura,
            key=f"dlg_chkret_{eid}",
        )
        retorno = None
        if tem_retorno:
            retorno = st.date_input(
                "Data de retorno",
                value=datetime.strptime(h["retorno"], "%d/%m/%Y").date() if h.get("retorno") else date.today(),
                disabled=somente_leitura,
                format="DD/MM/YYYY",
                key=f"dlg_ret_{eid}",
            )

    # Linha 2: Telefone fixo (linha separada — checkbox curto nao precisa de
    # coluna, evita layout squeeze na linha das datas)
    # Caracteristica do canal de contato (independente do status de cobranca).
    # Quando marcado, lote forca bucket=ligacao (sem msg) e botoes
    # 'Atendeu' / 'Nao atendeu' aparecem abaixo pra registro manual da
    # ligacao (N8N nao detecta atividade em telefone fixo).
    tel_fixo = st.checkbox(
        "Telefone fixo",
        value=bool(h.get("tel_fixo", False)),
        disabled=somente_leitura,
        key=f"dlg_telfixo_{eid}",
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
        [data-testid="stDialog"] div[data-testid="stElementContainer"]:has(div[data-naoatend]) {
            display: none !important;
        }
        [data-testid="stDialog"] div[data-testid="stColumn"]:has(div[data-naoatend]) button {
            background-color: #ff5555 !important;
            border-color: #ff5555 !important;
            color: #ffffff !important;
        }
        [data-testid="stDialog"] div[data-testid="stColumn"]:has(div[data-naoatend]) button:hover {
            background-color: #d94040 !important;
            border-color: #d94040 !important;
        }
        </style>
        """, unsafe_allow_html=True)

    # Promise date so aparece se 'Prometeu pagar' selecionado no dropdown.
    # status_sel pode ser None (modo automatico) — protege contra KeyError.
    promise_date = None
    if status_sel and STATUS_OPTS[status_sel] == "promise":
        promise_date = st.date_input(
            "Data que prometeu pagar",
            value=datetime.strptime(h["promiseDate"], "%d/%m/%Y").date() if h.get("promiseDate") else date.today(),
            disabled=somente_leitura,
            format="DD/MM/YYYY",
        )

    notes = st.text_area("Observações", value=h.get("notes", ""), placeholder="Ex: Cliente pediu prazo até sexta...", height=68, disabled=somente_leitura)

    # ── AUTO-SAVE de TODOS os campos (incluindo notes) ───────────────────
    # Status, datas, checkboxes e notes salvam automaticamente quando
    # atendente MUDA o valor (vs o EXPECTED DEFAULT que o widget renderiza
    # ao abrir). Notes salva no blur do textarea (Streamlit rerun apos
    # perder foco) — nao a cada keystroke.
    #
    # lastContact virou readonly (widget nao editavel, so exibe efetivo).
    # last_contact aqui reflete o manual antigo (h.get) — nunca diverge do
    # expected, entao nunca dispara auto-save por lastContact.
    if not somente_leitura:
        _expected_last_contact = h.get("lastContact") or ""
        _expected_retorno = h.get("retorno") or ""
        _expected_promise = h.get("promiseDate") or ""
        _expected_tel_fixo = bool(h.get("tel_fixo", False))
        # Status 'pending' e '' sao equivalentes (ambos = automatico).
        # Normaliza pra evitar auto-save falso no abrir dialog.
        _expected_status_raw = h.get("status", "")
        _expected_status = "" if _expected_status_raw in ("pending", "") else _expected_status_raw
        _expected_notes = h.get("notes", "")

        _curr_last_contact = last_contact.strftime("%d/%m/%Y") if last_contact else ""
        _curr_retorno = retorno.strftime("%d/%m/%Y") if retorno else ""
        _curr_promise = promise_date.strftime("%d/%m/%Y") if promise_date else ""
        # Se nada selecionado no dropdown → mantem status atual (vazio = automatico).
        # Se atendente selecionou opcao intencional → usa o valor mapeado.
        _curr_status = STATUS_OPTS[status_sel] if status_sel else ""

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
                # Salvar '' (vazio) em vez de 'pending' quando atendente
                # nao tem decisao manual — fica claro que e' automatico.
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
            # Telefone fixo virou True agora: se esse cliente já está no lote
            # de hoje como bucket='mensagem' (gerado antes dessa marcação),
            # corrige pra 'ligacao' na hora — senão a ligação real feita via
            # Atendeu/Não atendeu não conta em lugar nenhum nas métricas
            # (bucket diz mensagem, bools dizem ligação, nada bate).
            if bool(tel_fixo) and not _expected_tel_fixo:
                from data import corrigir_bucket_tel_fixo
                _atd_nome = cliente.get("_grupo") or ""
                if _atd_nome:
                    corrigir_bucket_tel_fixo(eid, _atd_nome)
            st.toast("Alterações salvas")

    # Linha "Editado por" só faz sentido em modo edição
    if not somente_leitura:
        st.markdown(f'<div style="font-size:12px;color:#8b94a5;margin-top:6px;font-weight:500">Editado por: <span style="color:#e8eaf0;font-weight:700">{current_nome()}</span></div>', unsafe_allow_html=True)

    # Detecta se cliente está fixado (promise vencida OU retorno vencido)
    # pra exibir o botão Concluir junto com Salvar/Cancelar.
    from datetime import date as _d
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
                            "status":      STATUS_OPTS[status_sel] if status_sel else h.get("status", ""),
                            "lastContact": last_contact.strftime("%d/%m/%Y") if last_contact else "",
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
                            "status":      STATUS_OPTS[status_sel] if status_sel else h.get("status", ""),
                            "lastContact": last_contact.strftime("%d/%m/%Y") if last_contact else "",
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
