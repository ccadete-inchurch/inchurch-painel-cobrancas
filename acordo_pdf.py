# -*- coding: utf-8 -*-
"""Gera o PDF da proposta de acordo, no layout que o financeiro ja usa.

O modelo veio de uma proposta real enviada pela Priscila (Igreja Evangelica
Vinho Novo, 15/10/2026). O calculo foi conferido contra ela: principal bate
exato (746,34) e o total atualizado sai 771,02 contra 770,74 do documento —
28 centavos em 770 reais, 0,036%, que e arredondamento ou a atualizacao
monetaria que nao entra aqui (ver acordo.py).

So monta o arquivo. Quem calcula e o acordo.py, quem entrega e o dialog.
"""
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

VERDE = colors.HexColor("#7cc243")
GRAFITE = colors.HexColor("#3c3c3c")
CINZA = colors.HexColor("#808080")
CINZA_CLARO = colors.HexColor("#f2f2f2")
BORDA = colors.HexColor("#d9d9d9")

LOGO = Path(__file__).resolve().parent / "inchurch_logo.png"

# Dados da empresa, iguais aos do modelo enviado.
PIX_FAVORECIDO = "Inradar App Ltda (INRADAR)"
PIX_CNPJ = "18.538.489/0001-15"
PIX_BANCO = "Santander"
SITE = "inchurch.com.br"
ENDERECO = ("Av. Alm. Júlio de Sá Bierrenbach, 65 · sala 717 · "
            "Barra da Tijuca · Rio de Janeiro/RJ · 22775-040")

# Telefone de cada atendente, pro bloco de assinatura. O painel sabe nome e
# e-mail de quem esta logado, mas nao o telefone. O da Priscila veio do
# modelo; sem o da pessoa, a linha simplesmente nao sai.
TELEFONE_ATENDENTE = {
    "priscila.oliveira@inchurch.com.br": "(21) 97524-0411",
}

_m = lambda v: f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _p(txt, size=9, cor=GRAFITE, bold=False, align=None, leading=None):
    st = ParagraphStyle(
        "x", fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size, textColor=cor, leading=leading or size * 1.35)
    if align is not None:
        st.alignment = align
    return Paragraph(txt, st)


def _tabela_cobrancas(proposta):
    cab = ["Nº COBRANÇA", "VENC. ORIGINAL", "PRINCIPAL (R$)",
           "ENCARGOS* (R$)", "ATUALIZADO (R$)"]
    linhas = [[_p(c, 7.5, GRAFITE, bold=True, align=TA_CENTER) for c in cab]]
    for d in proposta.detalhe:
        linhas.append([
            _p(str(d.get("id_recebimento") or "—"), 8.5, align=TA_CENTER),
            _p(d.get("vencimento") or "—", 8.5, align=TA_CENTER),
            _p(_m(d["valor"]), 8.5, align=TA_CENTER),
            _p(_m(d["multa"] + d["juros"]), 8.5, align=TA_CENTER),
            _p(_m(d["total"]), 8.5, align=TA_CENTER),
        ])
    linhas.append([
        _p("Total Acumulado (Sem Desconto):", 8.5, bold=True, align=TA_RIGHT),
        "", "", "",
        _p(f"R$ {_m(proposta.atualizado)}", 8.5, bold=True, align=TA_CENTER),
    ])
    n = len(linhas)
    t = Table(linhas, colWidths=[34*mm, 34*mm, 34*mm, 34*mm, 34*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), CINZA_CLARO),
        ("BACKGROUND", (0, n-1), (-1, n-1), CINZA_CLARO),
        ("SPAN", (0, n-1), (3, n-1)),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, n-1), (3, n-1), 8),
    ]))
    return t


def _caixa_opcoes(proposta, proposta_parcelada):
    """As duas opcoes lado a lado: a vista (com desconto) e parcelado."""
    a = [_p("OPÇÃO A: PAGAMENTO À VISTA", 9.5, GRAFITE, bold=True),
         Spacer(1, 5),
         _p(f"Total Atualizado: R$ {_m(proposta.atualizado)}", 9)]
    if proposta.desconto > 0:
        a += [Spacer(1, 4),
              _p(f"Desconto Concedido: - R$ {_m(proposta.desconto)}", 9, VERDE)]
    a += [Spacer(1, 6),
          Table([[""]], colWidths=[80*mm], rowHeights=[0.5],
                style=TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.5, BORDA)])),
          Spacer(1, 5),
          _p(f"Valor Final à Vista: R$ {_m(proposta.total)}", 10.5, GRAFITE, bold=True)]

    pp = proposta_parcelada
    b = [_p(f"OPÇÃO B: PAGAMENTO PARCELADO ({pp.parcelas}X)", 9.5, GRAFITE, bold=True),
         Spacer(1, 5),
         _p(f"Entrada (1ª parcela): R$ {_m(pp.valor_parcela)}", 9),
         Spacer(1, 4),
         _p(f"Demais Parcelas: {pp.parcelas - 1}x de R$ {_m(pp.valor_parcela)}", 9),
         Spacer(1, 6),
         Table([[""]], colWidths=[80*mm], rowHeights=[0.5],
               style=TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.5, BORDA)])),
         Spacer(1, 5),
         _p(f"Total Parcelado ({pp.parcelas}x): R$ {_m(pp.total)}", 10.5, GRAFITE, bold=True)]

    t = Table([[a, b]], colWidths=[85*mm, 85*mm])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (0, 0), 1, VERDE),
        ("BOX", (1, 0), (1, 0), 0.5, BORDA),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def _bloco_pix():
    corpo = [_p("DADOS PARA PAGAMENTO (PIX)", 9, GRAFITE, bold=True),
             Spacer(1, 5),
             _p(f"<b>Favorecido:</b> {PIX_FAVORECIDO}", 8.5),
             _p(f"<b>Chave PIX (CNPJ):</b> {PIX_CNPJ}", 8.5),
             _p(f"<b>Banco:</b> {PIX_BANCO}", 8.5)]
    t = Table([[corpo]], colWidths=[170*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CINZA_CLARO),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def _assinatura(nome, email, telefone):
    linhas = [_p(nome or "—", 9, GRAFITE, bold=True),
              _p("FINANCEIRO", 8.5, VERDE, bold=True)]
    if telefone:
        linhas.append(_p(telefone, 8.5))
    if email:
        linhas.append(_p(email, 8.5))
    linhas += [_p(f"<b>{SITE}</b>", 8.5, VERDE),
               _p(ENDERECO, 6.5, CINZA)]
    return linhas


def gerar(cliente_nome, proposta, proposta_parcelada,
          atendente_nome="", atendente_email="", telefone=None) -> bytes:
    """Devolve o PDF em bytes, pronto pro st.download_button."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm, topMargin=18*mm, bottomMargin=15*mm,
        title=f"Proposta de Acordo - {cliente_nome}", author="Inchurch")

    if telefone is None:
        telefone = TELEFONE_ATENDENTE.get((atendente_email or "").lower(), "")

    el = [
        _p("PROPOSTA DE ACORDO DE REGULARIZAÇÃO FINANCEIRA", 15, GRAFITE,
           bold=True, align=TA_CENTER),
        Spacer(1, 4),
        _p("Inchurch · Gestão Financeira", 9, CINZA, align=TA_CENTER),
        Spacer(1, 8),
        Table([[""]], colWidths=[170*mm], rowHeights=[1.5],
              style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), VERDE)])),
        Spacer(1, 12),
        _p(f"CLIENTE: {(cliente_nome or '').upper()}", 11.5, GRAFITE, bold=True),
        Spacer(1, 8),
        _tabela_cobrancas(proposta),
        Spacer(1, 5),
        _p("* Encargos incluem: Multa (2%), Juros (1% a.m.) e Atualização "
           "Monetária. Honorários: R$ 0,00.", 7, CINZA),
        Spacer(1, 12),
        Table([[_p("CONDIÇÕES ESPECIAIS DE PAGAMENTO", 9.5, colors.white,
                   bold=True)]], colWidths=[170*mm],
              style=TableStyle([
                  ("BACKGROUND", (0, 0), (-1, -1), GRAFITE),
                  ("LEFTPADDING", (0, 0), (-1, -1), 10),
                  ("TOPPADDING", (0, 0), (-1, -1), 6),
                  ("BOTTOMPADDING", (0, 0), (-1, -1), 6)])),
        Spacer(1, 10),
        _caixa_opcoes(proposta, proposta_parcelada),
        Spacer(1, 12),
        _bloco_pix(),
        Spacer(1, 14),
    ]
    el += _assinatura(atendente_nome, atendente_email, telefone)
    if LOGO.exists():
        el += [Spacer(1, 8), Image(str(LOGO), width=38*mm, height=38*mm*0.32,
                                   kind="proportional", hAlign="LEFT")]
    doc.build(el)
    return buf.getvalue()
