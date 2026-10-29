from datetime import datetime, date, timedelta
import streamlit as st

import re as _re_acordo

from acordo import (PARCELAS_MAX, montar as montar_acordo,
                    _pct as pct_acordo)
from acordo_pdf import gerar as gerar_pdf_acordo
from data import fetch_encargos_superlogica
from config import STATUS_OPTS
from auth import get_store, current_nome, current_email, current_role
from helpers import get_hist, get_hist_unificado, save_hist, fmt_moeda_plain, dias_html, get_effective_lastContact, get_ultimo_login, parse_date_br, telefones_cliente, aceita_whatsapp



def _slug(nome: str) -> str:
    """Nome do cliente virando nome de arquivo: sem acento, sem espaco."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(nome or "Cliente"))
    s = s.encode("ascii", "ignore").decode()
    s = _re_acordo.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return (s or "Cliente")[:60]



def _render_acordo(eid, cliente, itens):
    """A proposta de acordo, no formato do documento que o financeiro envia.

    O modelo tem SEMPRE duas opcoes: A a vista, onde entra o desconto, e B
    parcelada. Por isso a tela mostra as duas lado a lado em vez de uma por
    vez — o seletor escolhe so quantas parcelas tem a B.

    Os valores vem calculados do Superlogica; aqui so soma e divide.
    """
    _m = fmt_moeda_plain
    base = montar_acordo(itens, 1, 0.0)

    # Sem linha de resumo aqui. A contagem de cobrancas e os dias de atraso
    # ja estao nos cards do topo do dialog, que continuam na tela no modo
    # proposta, e o total atualizado aparece dentro dos dois quadros de
    # opcao logo abaixo — repetir no topo era so ruido.

    # O card mostra o saldo do BigQuery, que pra 1.143 clientes e MENOR que a
    # divida real — o painel le so a competencia-all e ignora a -hist. Mostrar
    # os dois evita a atendente achar que a proposta esta errada.
    if abs(base.principal - float(cliente.get("valor") or 0)) >= 0.01:
        st.info(
            f"O card mostra {_m(cliente.get('valor') or 0)} e o Superlógica "
            f"cobra {_m(base.principal)} de principal. A diferença são cobranças "
            f"antigas que não chegam ao painel. **A proposta usa o valor do "
            f"Superlógica.**"
        )

    # ── controles ────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns([1.5, 1, 1, 1], vertical_alignment="bottom")
    with c1:
        # 2x a 12x: a opcao A (a vista) existe sempre no documento e nao
        # precisa ser escolhida. Antes o seletor incluia 1x e, quando a
        # especialista escolhia "a vista", a opcao B do PDF saia 2x fixo.
        #
        # O rotulo traz o valor da parcela E o total, no formato que o Caio
        # pediu. O total e IGUAL em todas as opcoes — parcelar nao acrescenta
        # nada — por isso escrevi "total" e nao "com juros": os juros estao
        # dentro do valor, mas sao os do ATRASO, e "com juros" daria a
        # entender juros de financiamento, que aqui nao existem.
        parc = st.selectbox(
            "Parcelamento", list(range(2, PARCELAS_MAX + 1)), index=0,
            key=f"acordo_parc_{eid}",
            # So entra no rotulo o que MUDA entre as opcoes, que e o valor
            # da parcela. O total e o juros sao iguais nas onze — juros aqui
            # e de ATRASO, nao de parcelamento — e repetir o mesmo numero em
            # toda linha e ruido. A composicao fica nos quadros abaixo.
            format_func=lambda n: f"Em {n}x de {_m(base.atualizado / n)}")
    # Um desconto por opcao: a negociacao acontece como "a vista dou 10%,
    # parcelado dou 5%". Antes havia um campo so, que valia pra opcao A — o
    # Caio pediu os dois.
    with c2:
        desc_a = st.number_input(
            "Desconto à vista", min_value=0.0, step=10.0, value=0.0,
            format="%.2f", key=f"acordo_desc_a_{eid}",
            help="Em reais. Opcional. Abate da opção A.")
    with c3:
        desc_b = st.number_input(
            "Desconto parcelado", min_value=0.0, step=10.0, value=0.0,
            format="%.2f", key=f"acordo_desc_b_{eid}",
            help="Em reais. Opcional. Abate da opção B.")

    with c4:
        # Campo, nao calculo fixo: o prazo e parte da negociacao. O padrao de
        # 7 dias veio do modelo que o financeiro ja envia, mas quem fecha o
        # acordo pode dar mais ou menos conforme o caso.
        validade = st.date_input(
            "Validade", value=date.today() + timedelta(days=7),
            min_value=date.today(), format="DD/MM/YYYY",
            key=f"acordo_val_ate_{eid}",
            help="Até quando a proposta vale. Sai no PDF.")

    prop_a = montar_acordo(itens, 1, desc_a)        # opcao A, a vista
    prop_b = montar_acordo(itens, parc, desc_b)     # opcao B, parcelada

    # ── o calculo aberto ─────────────────────────────────────────────────
    with st.expander(f"Ver o cálculo das {len(prop_a.detalhe)} cobranças"):
        cab = ('<table style="width:100%;font-size:12px;border-collapse:collapse;color:var(--txt);border:1px solid var(--border);border-radius:8px">'
               '<tr style="color:var(--txt-2);text-align:right">'
               '<th style="text-align:left;padding:4px 0">Cobrança</th>'
               '<th>Vencimento</th><th>Atraso</th><th>Valor original</th>'
               '<th>Multa</th><th>Juros</th><th>Atualização</th><th>Atualizado</th></tr>')
        corpo = "".join(
            '<tr style="text-align:right;border-top:1px solid var(--surface-2)">'
            '<td style="text-align:left;padding:4px 0;color:var(--txt-2)">'
            + str(d.get("id_recebimento") or "—") + '</td>'
            '<td style="color:var(--txt-2)">' + str(d.get("vencimento") or "—") + '</td>'
            '<td style="color:var(--txt-2)">' + str(d.get("dias", 0)) + 'd</td>'
            '<td>' + _m(d.get("principal", 0)) + '</td>'
            '<td style="color:var(--txt-2)">' + _m(d.get("multa", 0)) + '</td>'
            '<td style="color:var(--txt-2)">' + _m(d.get("juros", 0)) + '</td>'
            '<td style="color:var(--txt-2)">' + _m(d.get("correcao", 0)) + '</td>'
            '<td style="font-weight:700">' + _m(d.get("total", 0)) + '</td></tr>'
            for d in prop_a.detalhe)
        st.markdown(cab + corpo + "</table>", unsafe_allow_html=True)

    # ── as duas opcoes, como no documento ────────────────────────────────
    def _caixa(titulo, linhas, destaque_rot, destaque_val, verde):
        corpo = "".join(
            '<div style="display:flex;justify-content:space-between;padding:2px 0;'
            'font-size:12.5px;color:' + cor + '"><span>' + rot + '</span>'
            '<span style="font-variant-numeric:tabular-nums">' + val + '</span></div>'
            for rot, val, cor in linhas)
        # margin-bottom na propria caixa, e nao so um spacer depois das
        # colunas: a caixa tem height:100% e estica ate o fim da linha, entao
        # o respiro precisa sair de DENTRO dela pra sobrar espaco antes do
        # Exportar. Com spacer solto a Opcao A continuava encostando no botao.
        return (
            '<div style="border:1px solid ' + ("var(--brand)" if verde else "var(--border)") + ';'
            'border-radius:8px;padding:12px 14px;background:var(--surface-3);'
            'height:calc(100% - 14px);margin-bottom:14px">'
            '<div style="font-size:11px;font-weight:700;letter-spacing:1px;'
            'text-transform:uppercase;color:' + ("var(--brand)" if verde else "var(--txt-2)")
            + ';margin-bottom:8px">' + titulo + '</div>' + corpo
            + '<div style="border-top:1px solid var(--surface-2);margin-top:8px;padding-top:8px;'
              'display:flex;justify-content:space-between;align-items:baseline">'
              '<span style="color:var(--txt-2);font-size:11px;text-transform:uppercase;'
              'letter-spacing:1px">' + destaque_rot + '</span>'
              '<span style="color:' + ("var(--brand)" if verde else "var(--txt)") + ';'
              'font-weight:800;font-size:18px;font-variant-numeric:tabular-nums">'
            + destaque_val + '</span></div></div>')

    linhas_a = [("Valor original", _m(prop_a.principal), "var(--txt-2)"),
                ("Multa (2%)", _m(prop_a.multa), "var(--txt-2)"),
                ("Juros (1% ao mês)", _m(prop_a.juros), "var(--txt-2)")]
    if prop_a.correcao > 0:
        linhas_a.append(("Atualização", _m(prop_a.correcao), "var(--txt-2)"))
    linhas_a.append(("Total atualizado", _m(prop_a.atualizado), "var(--txt)"))
    if prop_a.desconto > 0:
        linhas_a.append((f"Desconto ({pct_acordo(prop_a.pct_desconto)}%)",
                         "- " + _m(prop_a.desconto), "var(--brand)"))

    # "Sem acrescimo por parcelar" respondia a pergunta errada. A que a
    # igreja faz e "esse valor ja tem os juros?" — e tem: os do atraso.
    linhas_b = [("Valor original", _m(prop_b.principal), "var(--txt-2)"),
                ("Multa e juros do atraso", _m(prop_b.encargos), "var(--txt-2)"),
                ("Total atualizado", _m(prop_b.atualizado), "var(--txt)")]
    if prop_b.desconto > 0:
        linhas_b.append((f"Desconto ({pct_acordo(prop_b.pct_desconto)}%)",
                         "- " + _m(prop_b.desconto), "var(--brand)"))
    linhas_b.append((f"Dividido em {parc} parcelas iguais", "", "var(--txt-2)"))

    o1, o2 = st.columns(2)
    with o1:
        st.markdown(_caixa("Opção A · à vista", linhas_a,
                           "À vista", _m(prop_a.total), True),
                    unsafe_allow_html=True)
    with o2:
        st.markdown(_caixa(f"Opção B · {parc}x", linhas_b,
                           f"{parc}x de", _m(prop_b.valor_parcela), False),
                    unsafe_allow_html=True)

    # As duas caixas encostavam no Exportar. 22px separa a leitura das
    # opcoes da acao de gerar o documento.
    st.markdown('<div style="height:22px"></div>', unsafe_allow_html=True)
    st.download_button(
        "Exportar",
        data=gerar_pdf_acordo(cliente.get("nome", ""), prop_a, prop_b,
                              current_nome(), current_email(),
                              validade=validade),
        file_name="Proposta_Acordo_" + _slug(cliente.get("nome", "")) + ".pdf",
        mime="application/pdf", width="stretch", type="primary",
        icon=":material/picture_as_pdf:",
        help=f"PDF com as duas opções, assinado por {current_nome()}.",
        key=(f"acordo_pdf_{eid}_{parc}_{int(round(desc_a * 100))}"
             f"_{int(round(desc_b * 100))}_{validade:%Y%m%d}"))


def dialog_editar(eid, from_fixados: bool = False):
    """Abre o dialog do cliente, sempre pelo modo cobranca.

    O modo proposta vive no session_state e sobreviveria ao fechar: sem
    zerar aqui, reabrir o mesmo cliente dias depois cairia direto na
    proposta, sem as cobrancas, o status e as observacoes na tela. Este
    wrapper so limpa e chama — o dialog de verdade e o _dialog_editar.
    """
    st.session_state.pop(f"acordo_on_{eid}", None)
    st.session_state.pop(f"_notes_guard_{eid}", None)
    _dialog_editar(eid, from_fixados)


@st.dialog("Editar Registro", width="large")
def _dialog_editar(eid, from_fixados: bool = False):
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
    /* Os quatro filtros da proposta dividem a largura do dialog. O que nao
       cabia era "DESCONTO PARCELADO (R$)"; sem o "(R$)" o rotulo encurtou o
       bastante pra voltar a um corpo legivel. O nowrap fica como rede: se
       um dia nao couber, encolhe com reticencias em vez de quebrar em duas
       linhas e desalinhar a fileira inteira — o vizinho de uma linha so
       subiria. */
    [data-testid="stDialog"] [data-testid="stWidgetLabel"] p,
    [data-testid="stDialog"] [data-testid="stWidgetLabel"] label{
        font-size:12.5px !important;
        letter-spacing:0.5px !important;
        white-space:nowrap !important;
        overflow:hidden !important;
        text-overflow:ellipsis !important;
    }
    [data-testid="stDialog"] button[kind="primary"]{
        background-color:var(--brand) !important;
        border:1px solid var(--brand) !important;
        color:var(--txt-inv) !important;
    }
    [data-testid="stDialog"] button[kind="primary"]:hover{
        background-color:var(--brand) !important;
        border-color:var(--brand) !important;
    }
    [data-testid="stDialog"] [data-testid="stExpander"] details{
        border:none !important;
        background:transparent !important;
    }
    [data-testid="stDialog"] [data-testid="stExpander"] details summary{
        color:var(--txt-2) !important;
        font-size:13px !important;
        padding:6px 0 !important;
        background:transparent !important;
    }
    [data-testid="stDialog"] [data-testid="stExpander"] details summary:hover{
        color:var(--txt) !important;
    }
    [data-testid="stDialog"] [data-testid="stExpander"] details > div{
        padding:6px 0 0 0 !important;
        background:transparent !important;
        border:none !important;
    }
    /* O gatilho da proposta de acordo imita o summary do expander acima:
       texto puro, sem moldura, mesma cor e tamanho. Sao a mesma classe de
       acao — abrir detalhe das cobrancas — e precisam parecer irmas. */
    /* font-family:inherit porque <button> herda a fonte do user-agent, nao a
       do app — sem isso o rotulo sai numa fonte diferente do expander logo
       acima. Mas NAO pode cair no icone: o Material Symbols depende da fonte
       propria pra transformar a ligadura "expand_more" em simbolo, e quando
       eu usei `button *` o nome vazou como texto cru na tela. Por isso os
       seletores miram o botao e o container do rotulo, nunca "todos os
       filhos". */
    /* O "Voltar à cobrança" do modo proposta usa a mesma regra: e a mesma
       classe de acao, so no sentido contrario. */
    [data-testid="stDialog"] [class*="st-key-btn_acordo_on_"] button,
    [data-testid="stDialog"] [class*="st-key-btn_acordo_on_"] button [data-testid="stMarkdownContainer"],
    [data-testid="stDialog"] [class*="st-key-btn_acordo_on_"] button p,
    [data-testid="stDialog"] [class*="st-key-btn_voltar_"] button,
    [data-testid="stDialog"] [class*="st-key-btn_voltar_"] button [data-testid="stMarkdownContainer"],
    [data-testid="stDialog"] [class*="st-key-btn_voltar_"] button p{
        font-family:inherit !important;
        /* Maior e mais claro que o cinza do expander: no topo do dialog ele
           e o unico caminho pra proposta, e no cinza de rotulo auxiliar
           passava despercebido. */
        font-size:14.5px !important;
        font-weight:500 !important;
        color:var(--txt-claro) !important;
        line-height:1.2 !important;
    }
    [data-testid="stDialog"] [class*="st-key-btn_acordo_on_"] button,
    [data-testid="stDialog"] [class*="st-key-btn_voltar_"] button{
        border:none !important;
        background:transparent !important;
        box-shadow:none !important;
        padding:6px 0 !important;
        min-height:auto !important;
        height:auto !important;
        justify-content:flex-start !important;
    }
    [data-testid="stDialog"] [class*="st-key-btn_acordo_on_"] button:hover,
    [data-testid="stDialog"] [class*="st-key-btn_acordo_on_"] button:hover p,
    [data-testid="stDialog"] [class*="st-key-btn_acordo_on_"] button:hover [data-testid="stIconMaterial"],
    [data-testid="stDialog"] [class*="st-key-btn_voltar_"] button:hover,
    [data-testid="stDialog"] [class*="st-key-btn_voltar_"] button:hover p,
    [data-testid="stDialog"] [class*="st-key-btn_voltar_"] button:hover [data-testid="stIconMaterial"]{
        color:var(--txt) !important;
        background:transparent !important;
    }
    /* o icone do Material vem com tamanho proprio e destoava da setinha do
       expander */
    [data-testid="stDialog"] [class*="st-key-btn_acordo_on_"] button [data-testid="stIconMaterial"],
    [data-testid="stDialog"] [class*="st-key-btn_voltar_"] button [data-testid="stIconMaterial"]{
        font-size:18px !important;
        margin-right:2px !important;
    }
    [data-testid="stDialog"] [class*="st-key-btn_acordo_on_"] [data-testid="stMarkdownContainer"] p,
    [data-testid="stDialog"] [class*="st-key-btn_voltar_"] [data-testid="stMarkdownContainer"] p{
        margin:0 !important;
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
    /* Altura igual nos 5 cards do topo. O align-items:stretch iguala as
       COLUNAS — isso ja funcionava — mas entre a coluna e o .dialog-info ha
       uma pilha de containers do Streamlit (stVerticalBlock,
       stElementContainer, stMarkdownContainer) que nao herdam altura. Sem
       height:100% em CADA um, o card para na altura do proprio texto e o
       stretch da coluna nunca chega nele.
       Da primeira vez eu usei ">" entre eles e nao pegou: a pilha tem
       wrapper que nao e filho direto. Aqui vai por descendencia, escopado
       pela linha que CONTEM os cards, pra nao esticar container de outras
       partes do dialog. */
    [data-testid="stDialog"] [data-testid="stHorizontalBlock"]{
        align-items:stretch !important;
    }
    [data-testid="stDialog"] [data-testid="stHorizontalBlock"]:has(.dialog-info) [data-testid="stColumn"],
    [data-testid="stDialog"] [data-testid="stHorizontalBlock"]:has(.dialog-info) [data-testid="stVerticalBlock"],
    [data-testid="stDialog"] [data-testid="stHorizontalBlock"]:has(.dialog-info) [data-testid="stElementContainer"],
    [data-testid="stDialog"] [data-testid="stHorizontalBlock"]:has(.dialog-info) [data-testid="stMarkdownContainer"]{
        height:100% !important;
    }
    /* min-height e cinto e suspensorio: se o :has() falhar, os cards ainda
       saem iguais. 100px e a altura do mais alto hoje (rotulo em duas
       linhas + valor + complemento em duas), entao nao sobra espaco morto.
       space-between distribui rotulo / valor / complemento pela altura toda
       em vez de amontoar no topo. */
    [data-testid="stDialog"] .dialog-info{
        padding:10px 13px !important;
        display:flex !important;
        flex-direction:column !important;
        justify-content:space-between !important;
        height:100% !important;
        min-height:100px !important;
        box-sizing:border-box !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Admin vê o registro como está salvo no histórico das atendentes
    # (modo read-only). Atendente vê o próprio histórico (modo edição).
    role = current_role()
    somente_leitura = role == "admin"
    h = get_hist_unificado(eid) if somente_leitura else get_hist(eid)

    # Cobranças inadimplentes — precisa vir antes do botão, que só existe
    # quando há o que negociar.
    cobracas_inad = sorted(
        [c for c in cliente.get("_cobracas", []) if c["dias_atraso"] and c["dias_atraso"] > 0],
        key=lambda c: c["dias_atraso"],
    )

    _k_acordo = f"acordo_on_{eid}"
    _k_notes = f"dlg_notes_{eid}"
    _k_guard = f"_notes_guard_{eid}"
    _modo_proposta = bool(cobracas_inad) and st.session_state.get(_k_acordo)

    # ── O gatilho dos dois modos, logo abaixo do titulo do dialog ───────
    # Fica no topo porque nao e detalhe das cobrancas: e navegacao. O
    # "Voltar" ja estava aqui em cima por natureza, e o "Gerar proposta"
    # morava la embaixo, depois do "Ver mais N parcelas" — os dois lados da
    # mesma troca apareciam em lugares diferentes da tela.
    if cobracas_inad:
        if _modo_proposta:
            def _voltar(_k=_k_acordo):
                st.session_state[_k] = False

            st.button("Voltar à cobrança", key=f"btn_voltar_{eid}",
                      on_click=_voltar, icon=":material/arrow_back:")
        else:
            def _para_proposta(_k=_k_acordo, _kn=_k_notes, _kg=_k_guard):
                # O campo de Observacoes sai da tela no modo proposta, e o
                # Streamlit descarta o estado de widget que nao e
                # renderizado. Sem guardar aqui, quem digitou e clicou direto
                # no botao perdia o texto — o auto-save la embaixo nem chega
                # a rodar nesse ciclo.
                if _kn in st.session_state:
                    st.session_state[_kg] = st.session_state[_kn]
                st.session_state[_k] = True

            st.button("Gerar proposta de acordo", key=f"btn_{_k_acordo}",
                      on_click=_para_proposta,
                      icon=":material/arrow_forward:")

    if somente_leitura:
        # Texto puro em azul — sem retângulo de fundo (econômico em espaço
        # vertical e visualmente discreto). Só aparece pra admin.
        st.markdown(
            '<div style="color:var(--info);font-size:13px;font-weight:500;'
            'margin:0 0 10px 0">👁 Modo visualização</div>',
            unsafe_allow_html=True,
        )

    # Cabeçalho informativo
    c1, c2, c3, c4, c5 = st.columns([1.9, 1.05, 1.0, 1.1, 1.25])
    with c1:
        inativo_badge = '<span style="background:var(--txt-3);color:var(--txt-inv);font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-left:6px;vertical-align:middle">INATIVO</span>' if cliente.get("_inativo") else ""
        st.markdown(f'<div class="dialog-info"><div class="dialog-info-label">Cliente</div><div class="dialog-info-value" style="font-size:16px">{cliente["nome"]}{inativo_badge}</div><div style="font-size:12px;color:var(--txt-2);margin-top:3px">{cliente.get("cnpj","—")}</div></div>', unsafe_allow_html=True)
    with c2:
        parcelas = cliente.get("parcelas", len(cliente.get("_cobracas", [])))
        st.markdown(f'<div class="dialog-info"><div class="dialog-info-label">Saldo em aberto</div><div class="dialog-info-value" style="font-size:16px;color:var(--brand)">{fmt_moeda_plain(cliente["valor"])}</div><div style="font-size:12px;color:var(--txt-2);margin-top:3px">{parcelas} parcela{"s" if parcelas != 1 else ""} em atraso</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="dialog-info"><div class="dialog-info-label">Vencimento</div><div class="dialog-info-value" style="font-size:16px">{cliente.get("vencimento","—")}</div><div style="font-size:12px;color:var(--txt-2);margin-top:3px">{dias_html(cliente.get("dias_atraso"))}</div></div>', unsafe_allow_html=True)
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
            f'<div style="font-size:12px;color:var(--txt-2);margin-top:3px">{_ul_sub}</div></div>',
            unsafe_allow_html=True,
        )
    with c5:
        # Todos os telefones do cliente — primeiro destacado, demais inline
        # em fonte menor (igual aos cards). Todos selecionáveis/copiáveis.
        # Aqui saia o valor CRU do cadastro ("351968173332"). Passa por
        # telefones_cliente, que formata, junta o repetido e separa o que
        # nao da pra discar — este ultimo em vermelho, igual aos cards.
        _raw = cliente.get("telefones") or ([cliente.get("telefone")] if cliente.get("telefone") else [])
        _itens = telefones_cliente(_raw)
        # bons antes: o destaque nunca pode ser um numero furado
        tels = [f for _b, f, p in _itens if not p]
        tels += [f'<span style="color:var(--erro)" title="cadastro incompleto — {p}">{f}</span>'
                 for _b, f, p in _itens if p]
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
            f'<div style="font-size:12px;color:var(--txt-2);margin-top:3px">{tel_extras_html}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── MODO PROPOSTA ───────────────────────────────────────────────────
    # O dialog TROCA de conteudo em vez de empilhar a proposta embaixo de
    # tudo. Nao da pra abrir um segundo dialog: o Streamlit so mantem um
    # aberto por vez, e chamar outro fecha este. A troca de modo e o que
    # mais se parece com "abriu outra tela" sem ser outra tela.
    #
    # Some daqui: a lista de cobrancas, o status, o ultimo contato e as
    # observacoes. Nenhum deles entra na proposta, e os tres ultimos ficam
    # tao longe, no fim de um dialog que ja rola, que ninguem via as duas
    # opcoes lado a lado sem rolar de volta. Voltam intactos no "Voltar".
    if _modo_proposta:
        st.markdown(
            '<div style="font-size:13px;font-weight:700;color:var(--txt-2);'
            'letter-spacing:1.2px;text-transform:uppercase;'
            'margin:14px 0 22px 0">Proposta de Acordo</div>',
            unsafe_allow_html=True)

        # Os valores NAO sao calculados aqui. Vem do Superlogica ja com
        # multa, juros e correcao monetaria aplicados — ver
        # data.fetch_encargos_superlogica pro porque. Isso tambem resolve a
        # divida que o painel nao enxerga: a API traz as cobrancas da
        # competencia-hist, que o SQL do painel ignora.
        _itens, _erro = fetch_encargos_superlogica(str(eid))
        if _erro:
            st.error(
                f"Não consegui consultar o Superlógica ({_erro}). A proposta "
                f"precisa do valor atualizado de lá — sem isso ela sairia "
                f"errada, então não vou gerar. Tente de novo em alguns minutos."
            )
        elif not _itens:
            st.info(
                "O Superlógica não retornou cobrança em aberto para este "
                "cliente, embora o painel mostre atraso. Confira lá antes de "
                "negociar."
            )
        else:
            _render_acordo(eid, cliente, _itens)
        return

    # O acesso a proposta mora AQUI, na linha do titulo, e nao solto no meio
    # do dialog: ela trata destas cobrancas. E botao, nao expander, porque o
    # Streamlit executa o conteudo de um expander em toda renderizacao —
    # com a consulta a API la dentro, abrir qualquer cliente custava 1s.
    st.markdown(
        '<div style="font-size:13px;font-weight:700;color:var(--txt-2);letter-spacing:1.2px;'
        'text-transform:uppercase;margin:14px 0 10px 0">Cobranças Inadimplentes</div>',
        unsafe_allow_html=True,
    )

    def _render_cobranca_row(cob):
        # Linha compacta single-row: economiza ~50% de altura comparado ao
        # card de 2 linhas. Cliente com 18 parcelas (caso real visto) cabe
        # sem dialog gigante. min-width fixo no "Atraso" e badge garante
        # que valores diferentes (23d vs 112d) não desalinhem visualmente.
        # Fundo var(--surface-3) (mesmo do .dialog-info) — antes estava var(--surface-2)
        # mais claro, destoava do resto do dialog.
        return (
            f'<div style="background:var(--surface-3);border:1px solid var(--border-card);border-radius:8px;'
            f'padding:10px 14px;margin-bottom:6px;display:flex;align-items:center;'
            f'justify-content:space-between;gap:12px;font-size:14px">'
            f'<div style="display:flex;align-items:baseline;gap:10px;min-width:0">'
            f'<span style="font-weight:700;color:var(--txt);font-variant-numeric:tabular-nums">'
            f'{fmt_moeda_plain(cob["valor"])}</span>'
            f'<span style="color:var(--txt-2);font-size:12px">Vence {cob["vencimento"]}</span>'
            f'</div>'
            f'<div style="display:flex;align-items:center;gap:12px;flex-shrink:0">'
            f'<span style="color:var(--txt);font-variant-numeric:tabular-nums;'
            f'min-width:85px;text-align:right">'
            f'<span style="color:var(--txt-2)">Atraso:</span> <strong>{cob["dias_atraso"]}d</strong></span>'
            f'<span style="background:var(--erro-2);color:var(--txt-inv);padding:3px 8px;'
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

    # O cadastro tem celular e mesmo assim esta marcado como fixo? Mostra a
    # contradicao em vez de escondê-la. Nao desmarca nada: a marcacao pode
    # querer dizer "mandei mensagem e nao respondeu", que e' conhecimento
    # que o cadastro nao tem. Quem decide e' quem ligou.
    if tel_fixo:
        _tels_cli = (cliente.get("telefones")
                     or ([cliente.get("telefone")] if cliente.get("telefone") else []))
        _cels = [f for b, f, p in telefones_cliente(_tels_cli)
                 if not p and aceita_whatsapp(b)]
        if _cels:
            st.markdown(
                f'<div style="background:rgba(var(--amarelo-v),calc(.12 * var(--tint-k)));'
                f'border:1px solid rgba(var(--amarelo-v),.35);border-radius:6px;'
                f'padding:8px 12px;margin:-6px 0 10px 0;font-size:12px;'
                f'color:var(--alerta);line-height:1.5">'
                f'Este cliente tem celular no cadastro: '
                f'<b>{" · ".join(_cels)}</b>. Ainda é só telefone fixo?'
                f'</div>', unsafe_allow_html=True)


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
            background-color: var(--erro-2) !important;
            border-color: var(--erro-2) !important;
            color: var(--txt-inv) !important;
        }
        [data-testid="stDialog"] div[data-testid="stColumn"]:has(div[data-naoatend]) button:hover {
            background-color: var(--erro-2) !important;
            border-color: var(--erro-2) !important;
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

    # O valor guardado por _para_proposta volta aqui. Enquanto o modo
    # proposta estava na tela este widget nao existia, entao o Streamlit
    # limpou o estado dele e o 'value' abaixo volta a valer — que e
    # exatamente onde o texto nao salvo precisa reaparecer.
    _notes_guardada = st.session_state.pop(_k_guard, None)
    notes = st.text_area(
        "Observações",
        value=_notes_guardada if _notes_guardada is not None else h.get("notes", ""),
        placeholder="Ex: Cliente pediu prazo até sexta...",
        height=68, disabled=somente_leitura, key=_k_notes)

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
            _atd_nome = cliente.get("_grupo") or ""
            if _atd_nome and bool(tel_fixo) != _expected_tel_fixo:
                if bool(tel_fixo):
                    from data import corrigir_bucket_tel_fixo
                    corrigir_bucket_tel_fixo(eid, _atd_nome)
                else:
                    # Desmarcou: devolve o cliente pra coluna de mensagem,
                    # senao ele fica preso em ligacao o resto do dia sem os
                    # botoes de registro manual. Quem decide se pode e o
                    # deve_voltar_pra_mensagem — ver os sete casos la.
                    from data import (deve_voltar_pra_mensagem,
                                      corrigir_bucket_tel_fixo_removido)
                    from helpers import get_painel_acoes_hoje
                    if deve_voltar_pra_mensagem(cliente, get_painel_acoes_hoje(eid)):
                        corrigir_bucket_tel_fixo_removido(eid, _atd_nome)
            st.toast("Alterações salvas")

    # Linha "Editado por" só faz sentido em modo edição
    if not somente_leitura:
        st.markdown(f'<div style="font-size:12px;color:var(--txt-2);margin-top:6px;font-weight:500">Editado por: <span style="color:var(--txt);font-weight:700">{current_nome()}</span></div>', unsafe_allow_html=True)

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
