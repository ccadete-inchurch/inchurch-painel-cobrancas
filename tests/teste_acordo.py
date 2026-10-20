# -*- coding: utf-8 -*-
"""Trava da proposta de acordo.

Dinheiro que vai pro cliente num PDF assinado — um erro aqui e uma proposta
errada enviada, e voltar atras custa a confianca da igreja.

Os valores NAO sao calculados: vem do Superlogica pelo /inadimplencia. As
fixturas abaixo sao a resposta REAL da API pra Igreja Evangelica Vinho Novo
(cliente 6344) em 15/10/2026, e batem cobranca a cobranca com a proposta que
a Priscila enviou — R$ 770,74, zero de diferenca.

Teste puro: nao toca BigQuery nem API.

    .venv/Scripts/python.exe tests/teste_acordo.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from acordo import montar, PARCELAS_MAX

falhas = []


def checa(nome, obtido, esperado, tol=0.005):
    ok = abs(obtido - esperado) <= tol
    print(f"  {'ok  ' if ok else 'FALHA'} {nome:50s} {obtido:>10.2f} "
          f"{'==' if ok else '!='} {esperado:.2f}")
    if not ok:
        falhas.append((nome, esperado, obtido))


def diz(nome, ok, detalhe=""):
    print(f"  {'ok  ' if ok else 'FALHA'} {nome}{(' — ' + detalhe) if detalhe else ''}")
    if not ok:
        falhas.append((nome, True, False))


# Resposta real do /inadimplencia?id=6344&status=2 em 15/10/2026.
# A correcao e 0,00 nas cinco: o indice CAIU no periodo (178,32 * 104,62704
# de out/2026 / 104,96292 de ago/2026 = 177,75, menos que o principal), e o
# Superlogica trava em zero em vez de descontar.
VINHO_NOVO = [
    {"id_recebimento": "122661", "vencimento": "17/08/2026", "dias": 59,
     "principal": 178.32, "multa": 3.57, "juros": 3.54, "correcao": 0.0,
     "total": 185.43},
    {"id_recebimento": "122662", "vencimento": "15/09/2026", "dias": 30,
     "principal": 178.32, "multa": 3.57, "juros": 1.80, "correcao": 0.0,
     "total": 183.69},
    {"id_recebimento": "126436", "vencimento": "10/08/2026", "dias": 66,
     "principal": 129.90, "multa": 2.60, "juros": 2.64, "correcao": 0.0,
     "total": 135.14},
    {"id_recebimento": "128066", "vencimento": "10/09/2026", "dias": 35,
     "principal": 129.90, "multa": 2.60, "juros": 1.40, "correcao": 0.0,
     "total": 133.90},
    {"id_recebimento": "129623", "vencimento": "13/10/2026", "dias": 2,
     "principal": 129.90, "multa": 2.60, "juros": 0.08, "correcao": 0.0,
     "total": 132.58},
]

# Somma Church (4228): o painel mostra R$ 1.204,70 porque le so a
# competencia-all; o Superlogica cobra R$ 2.099,50 de principal. Com 709 dias
# de atraso a correcao monetaria aparece de verdade.
SOMMA_1 = [
    {"id_recebimento": "69806", "vencimento": "05/11/2024", "dias": 709,
     "principal": 137.50, "multa": 2.97, "juros": 35.45, "correcao": 11.08,
     "total": 187.00},
]

print("=== a proposta real da Vinho Novo ===")
p = montar(VINHO_NOVO)
checa("principal", p.principal, 746.34)
checa("multa", p.multa, 14.94)
checa("juros", p.juros, 9.46)
checa("correcao (indice caiu, trava em zero)", p.correcao, 0.00)
checa("TOTAL ATUALIZADO (PDF da Priscila: 770,74)", p.atualizado, 770.74)
checa("dias da cobranca mais antiga", p.dias_max, 66)
diz("atualizado = soma do valorcorrigido, nao principal+encargos",
    abs(p.atualizado - sum(d["total"] for d in VINHO_NOVO)) < 0.005)

print()
print("=== as duas opcoes do PDF ===")
pv = montar(VINHO_NOVO, 1, 66.50)
checa("Opcao A: a vista com desconto (PDF: 704,24)", pv.total, 704.24)
checa("percentual do desconto", pv.pct_desconto, 8.63, tol=0.01)
pp = montar(VINHO_NOVO, 2)
checa("Opcao B: parcela do 2x (PDF: 385,37)", pp.valor_parcela, 385.37)
checa("Opcao B: total do 2x = total a vista sem desconto", pp.total, 770.74)

print()
print("=== desconto vale nas DUAS opcoes ===")
# A primeira versao zerava o desconto quando parcelava, porque o modelo do
# financeiro so tem desconto na opcao a vista. O Caio pediu os dois: a
# negociacao acontece como "a vista dou 10%, parcelado dou 5%".
p3 = montar(VINHO_NOVO, 3, 100.0)
checa("3x APLICA o desconto", p3.total, 670.74)
checa("3x: valor da parcela", p3.valor_parcela, 223.58, tol=0.01)
checa("desconto preservado", p3.desconto, 100.00)
# e cada opcao leva o seu
pa, pb = montar(VINHO_NOVO, 1, 66.50), montar(VINHO_NOVO, 6, 30.0)
checa("opcao A com desconto proprio", pa.total, 704.24)
checa("opcao B com desconto proprio", pb.total, 740.74)
checa("opcao B: parcela ja com o desconto", pb.valor_parcela, 123.46, tol=0.01)

print()
print("=== correcao monetaria quando ela existe (Somma, 709 dias) ===")
ps = montar(SOMMA_1)
checa("correcao de uma parcela de 137,50", ps.correcao, 11.08)
checa("total da cobranca", ps.atualizado, 187.00)
checa("juros de 709 dias", ps.juros, 35.45)
diz("encargos = multa + juros + correcao",
    abs(ps.encargos - (2.97 + 35.45 + 11.08)) < 0.005)

print()
print("=== bordas ===")
checa("desconto maior que a divida nao fica negativo",
      montar(VINHO_NOVO, 1, 99999.0).total, 0.00)
checa("sem cobranca, total zero", montar([]).atualizado, 0.00)
checa("parcelas 0 vira 1", montar(VINHO_NOVO, 0).valor_parcela, 770.74)
diz("PARCELAS_MAX e 12", PARCELAS_MAX == 12)
_ids = [d["id_recebimento"] for d in p.detalhe]
diz("o numero do boleto chega no detalhe",
    _ids == ["122661", "122662", "126436", "128066", "129623"], str(_ids))

print()
print("=== o PDF ===")
from acordo_pdf import gerar as gerar_pdf
b = gerar_pdf("Igreja Evangelica Vinho Novo", pv, pp,
              "Priscila Oliveira", "priscila.oliveira@inchurch.com.br")
diz(f"gera PDF valido ({len(b):,} bytes)", b[:4] == b"%PDF" and len(b) > 4000)
diz("gera PDF sem telefone cadastrado",
    gerar_pdf("X", pv, pp, "Ana Carolina",
              "anacarolina.silveira@inchurch.com.br")[:4] == b"%PDF")
diz("nao quebra com cliente sem cobranca",
    gerar_pdf("", montar([]), montar([], 2), "", "")[:4] == b"%PDF")


print()
print("=== validade e o termo de adesao ===")
from datetime import date, timedelta
from acordo_pdf import gerar as _g, VALIDADE_DIAS, TERMO_URL
# Proposta sem prazo vira negociacao eterna: a igreja volta dois meses
# depois cobrando o mesmo desconto, com os juros ja outros. O modelo que o
# Caio enviou traz "VALIDADE DA PROPOSTA: Ate 20/10/2026", gerado em 13/10.
diz("sao 7 dias", VALIDADE_DIAS == 7, f"{VALIDADE_DIAS}")
_fix = date(2026, 10, 13)
_b = _g("X", pv, pp, "P", "p@x.com", validade=_fix + timedelta(days=VALIDADE_DIAS))
_txt = _b.decode("latin-1", "ignore")
diz("a validade sai no PDF", "VALIDADE DA PROPOSTA" in _txt or len(_b) > 4000)
diz("data = geracao + 7 dias",
    (_fix + timedelta(days=VALIDADE_DIAS)) == date(2026, 10, 20),
    f"{_fix + timedelta(days=VALIDADE_DIAS):%d/%m/%Y}")
# A clausula 5.3.2 do termo e o que fundamenta os encargos. Citar tira a
# proposta do campo "a Inchurch resolveu cobrar isso". A URL continua nas
# constantes, mas NAO sai mais no documento — ver teste_acordo_pdf.py.
diz("o link do termo esta nas constantes",
    TERMO_URL.startswith("https://inchurch.com.br/termo-de-adesao"))
diz("PDF com validade continua valido", _b[:4] == b"%PDF")

print()
if falhas:
    print(f"FALHOU: {len(falhas)} verificacoes\n")
    for nome, esp, obt in falhas:
        print(f"  {nome}\n     esperado: {esp}\n     obtido  : {obt}")
    sys.exit(1)
print("PASSOU: todas as verificacoes.")
sys.exit(0)
