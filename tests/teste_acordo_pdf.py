# -*- coding: utf-8 -*-
"""Trava o VISUAL do PDF da proposta.

O tests/teste_acordo.py cuida dos numeros. Este cuida da aparencia, que e
o outro jeito de a proposta sair errada: um verde trocado por outro, o
cinza do cabecalho no lugar do cinza do total, uma margem diferente, e o
documento deixa de parecer o que o financeiro ja manda.

Os valores esperados abaixo NAO foram escolhidos — foram extraidos do PDF
real que a Priscila enviou (Igreja Evangelica Vinho Novo, 15/10/2026),
decodificando o content stream dele. Quando este teste quebra, ou o layout
regrediu ou o modelo mudou de proposito; nos dois casos alguem precisa
olhar, nao so atualizar o numero esperado.

Le o PDF so com a biblioteca padrao (zlib + base64), de proposito: o
pypdf/pymupdf que usei pra investigar nao estao no requirements.txt e o
teste nao pode depender de algo que o CI nao instala.

    .venv/Scripts/python.exe tests/teste_acordo_pdf.py
"""
import base64
import os
import re
import sys
import zlib
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import acordo_pdf
from acordo import montar
from acordo_pdf import gerar

falhas = []


def diz(nome, ok, detalhe=""):
    print(f"  {'ok  ' if ok else 'FALHA'} {nome}{(' — ' + detalhe) if detalhe else ''}")
    if not ok:
        falhas.append(nome)


def igual(nome, obtido, esperado):
    ok = obtido == esperado
    print(f"  {'ok  ' if ok else 'FALHA'} {nome}")
    if not ok:
        print(f"         esperado: {esperado}")
        print(f"         obtido  : {obtido}")
        falhas.append(nome)


def conteudo(pdf: bytes) -> str:
    """O content stream da pagina, ja desembrulhado do ASCII85 + Flate."""
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        d = m.group(1)
        for passo in (lambda x: base64.a85decode(x, adobe=True), zlib.decompress):
            try:
                d = passo(d)
            except Exception:
                pass
        if b" Tj" in d and b"BT" in d:
            return d.decode("latin-1")
    return ""


def cores(s):
    return sorted({"%s #%02x%02x%02x" % (m.group(4),
                   *[round(float(m.group(j)) * 255) for j in (1, 2, 3)])
                   for m in re.finditer(r"([\d.]+) ([\d.]+) ([\d.]+) (rg|RG)\b", s)})


def fontes(s):
    return sorted({(m.group(1), float(m.group(2)))
                   for m in re.finditer(r"/(F\d+) ([\d.]+) Tf", s)})


def retangulos(s):
    return [tuple(round(float(m.group(j)), 4) for j in (1, 2, 3, 4))
            for m in re.finditer(r"n ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) re f\*", s)]


def texto(s):
    """O texto do stream, com os parenteses desescapados.

    Dentro de uma string PDF o parentese vem como \\( — sem desfazer isso,
    procurar por "DADOS PARA PAGAMENTO (PIX)" nunca acha nada.
    """
    partes = []
    for m in re.finditer(r"\(((?:[^()\\]|\\.)*)\) Tj", s):
        partes.append(m.group(1).replace("\\(", "(").replace("\\)", ")")
                      .replace("\\\\", "\\"))
    return " ".join(partes)


# Uma cobranca so: o teste e de layout, nao de conta, e uma linha basta pra
# tabela existir. Cliente ficticio de proposito — o repositorio e publico.
UMA = [{"id_recebimento": "100", "vencimento": "17/08/2026", "dias": 59,
        "principal": 178.32, "multa": 3.57, "juros": 3.54, "correcao": 0.0,
        "total": 185.43}]

pdf = gerar("Cliente Exemplo", montar(UMA, 1, 10.0), montar(UMA, 2),
            "Fulana de Tal", "fulana@inchurch.com.br",
            validade=date(2026, 10, 20))
s = conteudo(pdf)

print("=== o arquivo ===")
diz("comeca com %PDF", pdf[:4] == b"%PDF")
diz("o content stream foi lido", bool(s), f"{len(s)} caracteres")

print()
print("=== a paleta, como no PDF do financeiro ===")
# Cinco verdes, e cada um tem lugar: a regua e a borda da opcao A (#8cc63f),
# o titulo e o valor final da opcao A (#155724), o desconto (#28a745), o
# "FINANCEIRO" e o site (#6a9c27) e o link do termo (#6a9c27 tambem).
igual("as 19 cores do documento", cores(s), [
    "RG #8cc63f", "RG #cccccc", "RG #ced4da", "RG #dddddd",
    "rg #000000", "rg #155724", "rg #222222", "rg #28a745", "rg #333333",
    "rg #666666", "rg #6a9c27", "rg #777777", "rg #999999", "rg #d9534f",
    "rg #e9ecef", "rg #f4f7f9", "rg #f9f9f9", "rg #fcfdfa", "rg #ffffff",
])
# Os dois cinzas da tabela sao parecidos e vivem sendo trocados. O
# cabecalho leva o mais claro; a linha do total, o mais escuro.
diz("cabecalho da tabela em #f4f7f9",
    acordo_pdf.BG_CABECALHO.hexval() == "0xf4f7f9")
diz("linha do total em #e9ecef",
    acordo_pdf.BG_TOTAL.hexval() == "0xe9ecef")
diz("validade em vermelho #d9534f",
    acordo_pdf.VERMELHO.hexval() == "0xd9534f")

print()
print("=== fontes e corpos ===")
igual("Helvetica, Helvetica-Bold e Helvetica-BoldOblique", fontes(s), [
    ("F1", 7.0), ("F1", 7.5), ("F1", 8.5), ("F1", 9.0), ("F1", 10.0),
    ("F1", 12.0), ("F2", 8.5), ("F2", 9.0), ("F2", 9.5), ("F2", 10.0),
    ("F2", 10.5), ("F2", 12.0), ("F2", 16.0), ("F3", 10.0)])
diz("a faixa de condicoes e italica (F3 = BoldOblique)",
    b"/BaseFont /Helvetica-BoldOblique" in pdf)

print()
print("=== geometria ===")
r = retangulos(s)
diz("cabecalho e total tem 467,7165pt de largura e 18 de altura",
    r[0][2:] == (467.7165, -18.0) and r[1][2:] == (467.7165, -18.0), str(r[:2]))
diz("a faixa escura sangra 5pt pra fora da margem nos dois lados",
    (-5.0, -5.0, 479.8898, 24.0) in r, str([x for x in r if x[0] == -5.0]))
diz("as duas caixas tem 226,7717pt (80mm) de largura",
    [x for x in r if x[2] == 226.7717] == [(0.0, 78.5, 226.7717, -78.5)] * 2)
diz("o quadro do PIX tem 464,8819pt (164mm)",
    (0.0, 60.0, 464.8819, -60.0) in r)
igual("espessuras de linha: regua 1.5, bordas 1.0, grade 0.5",
      sorted({float(m.group(1)) for m in re.finditer(r"^([\d.]+) w$", s, re.M)}),
      [0.5, 1.0, 1.5])
diz("o logo sai em 136,063 x 32,315pt",
    ("136.063", "32.31496") in re.findall(r"([\d.]+) 0 0 ([\d.]+) 0 0 cm", s))
diz("o logo da proposta existe no repositorio", acordo_pdf.LOGO.exists(),
    acordo_pdf.LOGO.name)
diz("margem de 20mm (56,69pt) nos quatro lados",
    abs(acordo_pdf.MARGEM - 56.69291338582677) < 0.001,
    f"{acordo_pdf.MARGEM:.5f}pt")

print()
print("=== o que o documento diz ===")
t = texto(s)
for trecho in ("PROPOSTA DE ACORDO DE REGULARIZA", "CLIENTE: CLIENTE EXEMPLO",
               "VALIDADE DA PROPOSTA: At", "20/10/2026",
               "CONDI", "ESPECIAIS DE PAGAMENTO",
               "OP", "O A: PAGAMENTO", "DADOS PARA PAGAMENTO (PIX)",
               "Inradar App Ltda (INRADAR)", "18.538.489/0001-15",
               "Santander", "FINANCEIRO", "inchurch.com.br"):
    diz(f"traz {trecho!r}", trecho in t)
diz("o numero da cobranca aparece na tabela", "100" in t)
# A clausula 5.3.2 e o link sao o que sustenta os encargos. Sem eles a
# proposta vira "a Inchurch resolveu cobrar isso".
diz("cita a clausula 5.3.2", "5.3.2" in t)
diz("o link do termo esta no PDF",
    acordo_pdf.TERMO_URL.encode() in pdf)
diz("o link e clicavel (anotacao /URI)", b"/S /URI" in pdf)

print()
print("=== a validade e um campo, nao uma conta fixa ===")
# O Caio pediu que o prazo deixasse de ser sempre hoje+7: quem fecha o
# acordo decide. O default continua 7 dias pra nao mudar o que o
# financeiro ja fazia.
outra = gerar("Cliente Exemplo", montar(UMA, 1), montar(UMA, 2), "F", "f@x.com",
              validade=date(2027, 3, 9))
diz("a data passada e a que sai no PDF", "09/03/2027" in texto(conteudo(outra)))
padrao = gerar("Cliente Exemplo", montar(UMA, 1), montar(UMA, 2), "F", "f@x.com")
from datetime import timedelta
esperada = date.today() + timedelta(days=acordo_pdf.VALIDADE_DIAS)
diz(f"sem data, cai no padrao de {acordo_pdf.VALIDADE_DIAS} dias",
    f"{esperada:%d/%m/%Y}" in texto(conteudo(padrao)), f"{esperada:%d/%m/%Y}")

print()
print("=== bordas ===")
diz("sem desconto nao imprime a linha de desconto",
    "Desconto Concedido" not in texto(conteudo(
        gerar("X", montar(UMA, 1), montar(UMA, 2), "F", "f@x.com"))))
diz("com desconto nas duas opcoes, imprime nas duas",
    texto(conteudo(gerar("X", montar(UMA, 1, 5.0), montar(UMA, 2, 3.0),
                         "F", "f@x.com"))).count("Desconto Concedido") == 2)
diz("cliente sem cobranca nao quebra",
    gerar("", montar([]), montar([], 2), "", "")[:4] == b"%PDF")
diz("atendente sem telefone cadastrado nao quebra",
    gerar("X", montar(UMA, 1), montar(UMA, 2), "Ana", "ana@inchurch.com.br")[:4]
    == b"%PDF")
diz("12x cabe numa pagina so",
    gerar("X", montar(UMA, 1, 5.0), montar(UMA, 12, 3.0), "F", "f@x.com"
          ).count(b"/Type /Page\n") == 1)

print()
if falhas:
    print(f"FALHOU: {len(falhas)} verificacoes\n")
    for n in falhas:
        print(f"  {n}")
    sys.exit(1)
print("PASSOU: todas as verificacoes.")
sys.exit(0)
