# -*- coding: utf-8 -*-
"""Trava do calculo da proposta de acordo.

Dinheiro que vai pro cliente por WhatsApp — um erro aqui e uma proposta
errada enviada, e voltar atras custa a confianca da igreja. Teste puro, nao
toca no BigQuery nem na API.

    .venv/Scripts/python.exe tests/teste_acordo.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from acordo import calcular, texto_whatsapp, TAXA_JUROS, TAXA_MULTA

falhas = []


def checa(nome, obtido, esperado, tol=0.01):
    ok = abs(obtido - esperado) <= tol
    print(f"  {'ok  ' if ok else 'FALHA'} {nome:52s} {obtido:>10.2f} "
          f"{'==' if ok else '!='} {esperado:.2f}")
    if not ok:
        falhas.append((nome, esperado, obtido))


print("=== uma cobranca, 30 dias de atraso ===")
# 1000 + 2% multa + 1% de um mes = 1000 + 20 + 10
p = calcular([{"valor": 1000.0, "dias_atraso": 30}])
checa("principal", p.principal, 1000.00)
checa("multa 2%", p.multa, 20.00)
checa("juros 1% x 1 mes", p.juros, 10.00)
checa("total atualizado", p.atualizado, 1030.00)
checa("sem desconto, total = atualizado", p.total, 1030.00)

print("\n=== o caso que o Caio deu: 746,34 ===")
# 90 dias = 3 meses -> 3% de juros
p = calcular([{"valor": 746.34, "dias_atraso": 90}])
checa("principal", p.principal, 746.34)
checa("multa", p.multa, 14.93)
checa("juros 3 meses", p.juros, 22.39)
checa("a vista, sem desconto", p.total, 783.66)

print("\n=== juros contam por COBRANCA, nao pelo atraso da mais antiga ===")
# Se usasse 600 dias pras duas, os juros seriam (500+500)*0.01*20 = 200.
# Por cobranca: 500*0.01*20 + 500*0.01*1 = 100 + 5 = 105.
p = calcular([{"valor": 500.0, "dias_atraso": 600},
              {"valor": 500.0, "dias_atraso": 30}])
checa("principal somado", p.principal, 1000.00)
checa("juros por cobranca (nao 200)", p.juros, 105.00)
checa("multa sobre o total", p.multa, 20.00)
checa("dias_max guarda a mais antiga", p.dias_max, 600)

print("\n=== desconto so existe a vista ===")
p = calcular([{"valor": 1000.0, "dias_atraso": 30}], parcelas=1, desconto=100.0)
checa("1x com desconto de 100", p.total, 930.00)
checa("percentual do desconto", p.pct_desconto, 9.71)
p = calcular([{"valor": 1000.0, "dias_atraso": 30}], parcelas=3, desconto=100.0)
checa("3x IGNORA o desconto", p.total, 1030.00)
checa("3x: valor da parcela", p.valor_parcela, 343.33)

print("\n=== limites e bordas ===")
p = calcular([{"valor": 1000.0, "dias_atraso": 30}], desconto=99999.0)
checa("desconto maior que a divida nao fica negativo", p.total, 0.00)
p = calcular([])
checa("sem cobranca, principal zero", p.principal, 0.00)
checa("sem cobranca, total zero", p.total, 0.00)
p = calcular([{"valor": 1000.0, "dias_atraso": 0},
              {"valor": 500.0, "dias_atraso": None},
              {"valor": 0, "dias_atraso": 90},
              {"valor": None, "dias_atraso": 90},
              {"valor": 800.0, "dias_atraso": 60}])
checa("ignora em dia, nulo e valor zero", p.principal, 800.00)
checa("juros so da que vale", p.juros, 16.00)
p = calcular([{"valor": 1000.0, "dias_atraso": 30}], parcelas=0)
checa("parcelas 0 vira 1", p.valor_parcela, 1030.00)

print("\n=== as taxas sao as do cadastro do Superlogica ===")
checa("multa = 2%", TAXA_MULTA * 100, 2.0)
checa("juros = 1% ao mes", TAXA_JUROS * 100, 1.0)

print("\n=== o texto pro WhatsApp ===")
p = calcular([{"valor": 746.34, "dias_atraso": 90}], parcelas=1, desconto=50.0)
t = texto_whatsapp("Igreja Batista Central", p)
checa("tem o valor a vista com desconto", float(t.count("Desconto")), 1.0)
for trecho in ("746,34", "Multa (2%)", "Juros (1% ao mês)", "Igreja Batista Central"):
    ok = trecho in t
    print(f"  {'ok  ' if ok else 'FALHA'} texto contem {trecho!r}")
    if not ok:
        falhas.append((f"texto sem {trecho}", trecho, t))
p3 = calcular([{"valor": 900.0, "dias_atraso": 60}], parcelas=3)
t3 = texto_whatsapp("", p3)
ok = "3x de" in t3 and "Desconto" not in t3
print(f"  {'ok  ' if ok else 'FALHA'} parcelado mostra 3x e NAO mostra desconto")
if not ok:
    falhas.append(("texto parcelado", "3x sem desconto", t3))

print()
if falhas:
    print(f"FALHOU: {len(falhas)} verificacoes\n")
    for nome, esp, obt in falhas:
        print(f"  {nome}\n     esperado: {esp}\n     obtido  : {obt}")
    sys.exit(1)
print("PASSOU: todas as verificacoes.")
sys.exit(0)
