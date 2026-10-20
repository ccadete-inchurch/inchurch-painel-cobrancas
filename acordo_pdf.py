# -*- coding: utf-8 -*-
"""Gera o PDF da proposta de acordo, no layout que o financeiro ja usa.

O modelo veio de uma proposta real enviada pela Priscila (Igreja Evangelica
Vinho Novo, 15/10/2026). Os numeros batem com ela EXATAMENTE — R$ 770,74 nas
cinco cobrancas, zero de diferenca — porque nao sao calculados aqui: vem
prontos do Superlogica (ver data.fetch_encargos_superlogica).

O LAYOUT tambem nao e invencao. O PDF do financeiro foi aberto, o content
stream decodificado, e cada cor, fonte, tamanho e medida abaixo saiu de la —
nao de um "verde parecido". Por isso as constantes tem numeros quebrados
como 62.69291: e o que estava no arquivo. O teste tests/teste_acordo_pdf.py
compara os dois PDFs elemento a elemento e quebra se algo divergir.

Duas coisas sao deliberadamente DIFERENTES do modelo, porque o Caio pediu:
a nota de rodape cita o IGP-M/FGV e linka a clausula 5.3.2 do termo, e a
validade deixou de ser fixa em 7 dias pra virar campo preenchido no painel.

So monta o arquivo. Quem soma e divide e o acordo.py, quem entrega e o
dialog.
"""
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, Image, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

# ---------------------------------------------------------------- paleta
# Extraida do PDF do financeiro (operadores rg/RG do content stream). Sao
# cinco verdes diferentes, e cada um tem lugar certo — trocar um pelo outro
# e a diferenca entre "igual" e "parecido".
VERDE_LINHA = colors.HexColor("#8cc63f")   # reguas e a borda da opcao A
VERDE_ESCURO = colors.HexColor("#155724")  # titulo e valor final da opcao A
VERDE_DESCONTO = colors.HexColor("#28a745")  # a linha do desconto concedido
VERDE_ASSINATURA = colors.HexColor("#6a9c27")  # "FINANCEIRO" e o site
VERMELHO = colors.HexColor("#d9534f")      # a validade, pra puxar o olho

TITULO = colors.HexColor("#222222")
TEXTO = colors.HexColor("#333333")
SUBTITULO = colors.HexColor("#777777")
NOTA = colors.HexColor("#666666")
ENDERECO_COR = colors.HexColor("#999999")

# Os dois cinzas da tabela sao proximos e NAO sao intercambiaveis: o
# cabecalho leva o mais claro e azulado, a linha do total o mais escuro.
BG_CABECALHO = colors.HexColor("#f4f7f9")
BG_TOTAL = colors.HexColor("#e9ecef")
BG_CAIXA_A = colors.HexColor("#fcfdfa")    # fundo quase branco da opcao A
BG_PIX = colors.HexColor("#f9f9f9")
GRID = colors.HexColor("#dddddd")
BORDA_B = colors.HexColor("#ced4da")       # borda da caixa da opcao B
SEP_B = colors.HexColor("#cccccc")         # regua interna da opcao B

# -------------------------------------------------------------- geometria
# O conteudo do modelo comeca em x=62.69pt, que parece numero quebrado mas
# nao e: sao 20mm de margem mais os 6pt de padding que o Frame do
# SimpleDocTemplate poe por conta propria. Mexer na margem sem lembrar dos
# 6pt desalinha a pagina inteira.
MARGEM = 20*mm
LARGURA_UTIL = 469.8898  # A4 menos as margens e o padding do Frame
COLS_TABELA = [32*mm, 32*mm, 32*mm, 32*mm, 37*mm]  # a ultima e mais larga
ALTURA_LINHA = 18
LARGURA_CAIXA = 80*mm    # cada opcao, dentro de uma celula de 82mm
LARGURA_PIX = 164*mm
LOGO_L, LOGO_A = 136.063, 32.31496

LOGO = Path(__file__).resolve().parent / "inchurch_logo_proposta.png"

# Dados da empresa, iguais aos do modelo enviado.
PIX_FAVORECIDO = "Inradar App Ltda (INRADAR)"
PIX_CNPJ = "18.538.489/0001-15"
PIX_BANCO = "Santander"
SITE = "inchurch.com.br"
# A clausula 5.3.2 do termo de adesao e o que fundamenta os encargos: multa
# de 2%, juros de mora de 1% ao mes e correcao monetaria ate a data do
# efetivo pagamento. Citar a clausula tira a proposta do campo "a Inchurch
# resolveu cobrar isso" e a coloca no que a igreja assinou.
#
# O LINK do termo saiu a pedido do Caio (20/10/2026). A URL continua aqui
# porque o teste confere que ela nao voltou pro documento por descuido.
TERMO_URL = "https://inchurch.com.br/termo-de-adesao-inchurch/"
TERMO_CLAUSULA = "cláusula 5.3.2 do Termo de Adesão"
# O indice da correcao monetaria, como sai escrito no documento.
INDICE_CORRECAO = "IPCA"
VALIDADE_DIAS = 7
ENDERECO = ("Av. Alm. Júlio de Sá Bierrenbach, 65 · sala 717 · "
            "Barra da Tijuca · Rio de Janeiro/RJ · 22775-040")

# Telefone de cada atendente, pro bloco de assinatura. O painel sabe nome e
# e-mail de quem esta logado, mas nao o telefone. O da Priscila veio do
# modelo; sem o da pessoa, a linha simplesmente nao sai.
TELEFONE_ATENDENTE = {
    "priscila.oliveira@inchurch.com.br": "(21) 97524-0411",
}

_m = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _p(txt, size=9, cor=TEXTO, bold=False, align=None, leading=12,
       italic=False):
    nome = ("Helvetica-BoldOblique" if italic and bold else
            "Helvetica-Bold" if bold else "Helvetica")
    st = ParagraphStyle("x", fontName=nome, fontSize=size, textColor=cor,
                        leading=leading)
    if align is not None:
        st.alignment = align
    return Paragraph(txt, st)


def _regua(cor, espessura, largura="100%"):
    return HRFlowable(width=largura, thickness=espessura, color=cor,
                      spaceBefore=0, spaceAfter=0)


def _tabela_cobrancas(proposta):
    cab = ["Nº COBRANÇA", "VENC. ORIGINAL", "PRINCIPAL (R$)",
           "ENCARGOS* (R$)", "ATUALIZADO (R$)"]
    linhas = [[_p(c, 8.5, TEXTO, bold=True, align=TA_CENTER) for c in cab]]
    for d in proposta.detalhe:
        linhas.append([
            _p(str(d.get("id_recebimento") or "—"), 8.5, colors.black,
               align=TA_CENTER),
            _p(d.get("vencimento") or "—", 8.5, colors.black, align=TA_CENTER),
            _p(_m(d["principal"]), 8.5, colors.black, align=TA_CENTER),
            # "Encargos" junta os tres, como no modelo do financeiro: a
            # correcao monetaria entra aqui e nao em coluna propria.
            _p(_m(d["multa"] + d["juros"] + d.get("correcao", 0.0)),
               8.5, colors.black, align=TA_CENTER),
            _p(_m(d["total"]), 8.5, colors.black, align=TA_CENTER),
        ])
    # A linha do total e PRETA no modelo, nao no cinza do cabecalho.
    linhas.append([
        _p("Total Acumulado (Sem Desconto):", 8.5, colors.black, bold=True,
           align=TA_RIGHT),
        "", "", "",
        _p(f"R$ {_m(proposta.atualizado)}", 8.5, colors.black, bold=True,
           align=TA_CENTER),
    ])
    n = len(linhas)
    t = Table(linhas, colWidths=COLS_TABELA,
              rowHeights=[ALTURA_LINHA] * n)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BG_CABECALHO),
        ("BACKGROUND", (0, n-1), (-1, n-1), BG_TOTAL),
        ("SPAN", (0, n-1), (3, n-1)),
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _caixa(itens, borda, fundo):
    t = Table([[itens]], colWidths=[LARGURA_CAIXA])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fundo),
        ("BOX", (0, 0), (-1, -1), 1, borda),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _caixa_opcoes(proposta, proposta_parcelada):
    """As duas opcoes lado a lado: a vista (com desconto) e parcelada.

    A opcao A vem destacada — borda verde, fundo levemente esverdeado e os
    valores em verde escuro — porque e a que o financeiro quer que a igreja
    escolha. A B fica neutra, em cinza.
    """
    a = [_p("OPÇÃO A: PAGAMENTO À VISTA", 9.5, VERDE_ESCURO, bold=True),
         Spacer(1, 6),
         _p(f"Total Atualizado: R$ {_m(proposta.atualizado)}", 9, TEXTO)]
    if proposta.desconto > 0:
        a += [Spacer(1, 6),
              _p(f"Desconto Concedido: - R$ {_m(proposta.desconto)}",
                 8.5, VERDE_DESCONTO)]
    a += [Spacer(1, 6), _regua(VERDE_LINHA, 0.5), Spacer(1, 6),
          _p(f"Valor Final à Vista: R$ {_m(proposta.total)}", 10.5,
             VERDE_ESCURO, bold=True)]

    pp = proposta_parcelada
    b = [_p(f"OPÇÃO B: PAGAMENTO PARCELADO ({pp.parcelas}X)", 9.5, TEXTO,
            bold=True),
         Spacer(1, 6),
         _p(f"Entrada (1ª parcela): R$ {_m(pp.valor_parcela)}", 9, TEXTO),
         Spacer(1, 6),
         _p(f"Demais Parcelas: {pp.parcelas - 1}x de R$ {_m(pp.valor_parcela)}",
            9, TEXTO)]
    if pp.desconto > 0:
        b += [Spacer(1, 6),
              _p(f"Desconto Concedido: - R$ {_m(pp.desconto)}",
                 8.5, VERDE_DESCONTO)]
    b += [Spacer(1, 6), _regua(SEP_B, 0.5), Spacer(1, 6),
          _p(f"Total Parcelado ({pp.parcelas}x): R$ {_m(pp.total)}", 10.5,
             TEXTO, bold=True)]

    t = Table([[_caixa(a, VERDE_LINHA, BG_CAIXA_A),
                _caixa(b, BORDA_B, colors.white)]],
              colWidths=[82*mm, 82*mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1*mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1*mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _bloco_pix():
    corpo = [_p("DADOS PARA PAGAMENTO (PIX)", 9.5, TEXTO, bold=True),
             Spacer(1, 6),
             _p(f"<b>Favorecido:</b> {PIX_FAVORECIDO}<br/>"
                f"<b>Chave PIX (CNPJ):</b> {PIX_CNPJ}<br/>"
                f"<b>Banco:</b> {PIX_BANCO}", 9, TEXTO)]
    t = Table([[corpo]], colWidths=[LARGURA_PIX])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_PIX),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _assinatura(nome, email, telefone):
    """Assinatura e logo, alinhados 2,5pt a direita da margem.

    No modelo esse bloco nao encosta na margem: fica recuado como o quadro
    do PIX, porque os dois estao dentro de um container de 164mm centrado.
    Sem o container, a assinatura e o logo sobem 2,5pt pra esquerda e o
    rodape deixa de alinhar com o resto da pagina.
    """
    linhas = [f"<b>{nome or '—'}</b>",
              f'<font color="#6a9c27"><b>FINANCEIRO</b></font>']
    if telefone:
        linhas.append(telefone)
    if email:
        linhas.append(email)
    linhas.append(f'<font color="#6a9c27"><b>{SITE}</b></font>')
    corpo = [_p("<br/>".join(linhas), 9, TEXTO),
             Spacer(1, 2),
             _p(ENDERECO, 7, ENDERECO_COR)]
    if LOGO.exists():
        corpo += [Spacer(1, 6),
                  Image(str(LOGO), width=LOGO_L, height=LOGO_A, hAlign="LEFT")]
    t = Table([[corpo]], colWidths=[LARGURA_PIX])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def gerar(cliente_nome, proposta, proposta_parcelada,
          atendente_nome="", atendente_email="", telefone=None,
          validade=None) -> bytes:
    """Devolve o PDF em bytes, pronto pro st.download_button."""
    if validade is None:
        validade = date.today() + timedelta(days=VALIDADE_DIAS)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM,
        topMargin=MARGEM, bottomMargin=MARGEM,
        title=f"Proposta de Acordo - {cliente_nome}", author="Inchurch")

    if telefone is None:
        telefone = TELEFONE_ATENDENTE.get((atendente_email or "").lower(), "")

    # A faixa escura e um Paragraph com fundo e borderPadding, nao uma
    # tabela: por isso ela sangra 5pt pra fora da margem nos dois lados,
    # exatamente como no modelo.
    faixa = ParagraphStyle(
        "faixa", fontName="Helvetica-BoldOblique", fontSize=10, leading=14,
        textColor=colors.white, backColor=TEXTO, borderPadding=5)

    el = [
        _p("PROPOSTA DE ACORDO DE REGULARIZAÇÃO FINANCEIRA", 16, TITULO,
           bold=True, align=TA_CENTER, leading=22),
        Spacer(1, 4),
        _p("Inchurch · Gestão Financeira", 10, SUBTITULO, align=TA_CENTER),
        Spacer(1, 9),
        _regua(VERDE_LINHA, 1.5),
        Spacer(1, 12),
        _p(f"CLIENTE: {(cliente_nome or '').upper()}", 12, TITULO, bold=True,
           leading=18),
        Spacer(1, 2),
        # Proposta sem prazo vira negociacao eterna: a igreja volta dois meses
        # depois cobrando o mesmo desconto, com os juros ja outros.
        _p(f"VALIDADE DA PROPOSTA: Até {validade:%d/%m/%Y}", 10, VERMELHO,
           bold=True),
        Spacer(1, 8),
        _tabela_cobrancas(proposta),
        Spacer(1, 4),
        _p("* Encargos incluem: Multa (2%), Juros (1% a.m.) e Atualização "
           f"Monetária ({INDICE_CORRECAO}). Honorários: R$ 0,00.", 7.5, NOTA),
        Spacer(1, 12),
        Paragraph("CONDIÇÕES ESPECIAIS DE PAGAMENTO", faixa),
        Spacer(1, 8),
        _caixa_opcoes(proposta, proposta_parcelada),
        Spacer(1, 12),
        _bloco_pix(),
        Spacer(1, 15),
        _assinatura(atendente_nome, atendente_email, telefone),
    ]
    doc.build(el)
    return buf.getvalue()
