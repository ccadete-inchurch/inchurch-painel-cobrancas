# -*- coding: utf-8 -*-
"""Trava do telefones_cliente, com os casos reais que custaram caro.

Cada linha aqui e um cliente de verdade e uma decisao que foi discutida,
errada pelo menos uma vez, e corrigida. O valor do cadastro esta congelado
como literal: o teste e puro e instantaneo, nao toca no BigQuery.

Diferente do teste_regressao_telefone.py, que e trava de MIGRACAO e so
pergunta "sumiu numero discavel?", este verifica o RESULTADO — o texto
formatado e o motivo de estar furado. Era o buraco: o de migracao compara
so os digitos, entao uma regressao na leitura de pais passava batida.

    .venv/Scripts/python.exe tests/teste_telefones_cliente.py

Sai com codigo 0 se passou, 1 se falhou.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import telefones_cliente, tipo_numero

# (cliente, o que a historia ensinou, campo do data.py, saida esperada)
# A saida e [(texto exibido, motivo de estar furado)] — motivo vazio = o
# numero serve e ganha o icone de WhatsApp.
CASOS = [
    ("4548 Ewerton",
     "o st_ddd_sac completa QUALQUER campo, nao so o st_telefone_sac",
     "982338073;ddd=071",
     [("(71) 98233-8073", "")]),

    ("3532 Match Jesus",
     "japones: o truncado COM 55 parecia maior que o inteiro sem ele",
     "5581903955778;819039557782",
     [("+81 90 3955-7782", "")]),

    ("6592 Brasas do Reino",
     "56 digitado no lugar do 55 — numero reconhecido vence o fallback cru",
     "5621999718953;21999718953",
     [("(21) 99971-8953", "")]),

    ("1623 Eglise Du Centre",
     "Suica so existia no telefone_wa_link, nao no formatar_telefone",
     "41765720874;(41)76572-0874",
     [("+41 76 572 08 74", "")]),

    ("5921 Mount Zion USA",
     "Mexico idem; e o DDD 52 nao existe, entao a leitura BR perde",
     "524461383891;52446138389",
     [("+52 446 138 3891", "")]),

    ("3230 Mevam Braga",
     "Braga e em Portugal — a mascara cortou 1 digito do +351",
     "351910485546;35191048554;(35)19104-8554",
     [("+351 910 485 546", "")]),

    ("4333 Catedral de Adoracao",
     "Angola, mesmo corte da mascara",
     "244924419534;24492441953",
     [("+244 924 419 534", "")]),

    ("4344 Bom Samaritano",
     "nono digito do celular, com o 55 na frente escondendo a relacao",
     "5592994950307;9294950307",
     [("(92) 99495-0307", "")]),

    ("4532 Restaurando Vidas",
     "o fax e o celular cortado 1 digito pela mascara",
     "5521995002430;2199500243",
     [("(21) 99500-2430", "")]),

    ("3295 Oscar de Almeida",
     "55 + DDD 51 + 7 digitos: o truncado perde pro inteiro montado do DDD",
     "55519983472;55519983472;998347242;ddd=51",
     [("(51) 99834-7242", "")]),

    ("3421 Apostolica Shalom",
     "o mesmo numero com e sem o 55 do Brasil",
     "5511954052870;11954052870",
     [("(11) 95405-2870", "")]),

    ("6625 Casa Peniel",
     "DDD 94 x 95: numeros DIFERENTES com o mesmo final, NAO juntar",
     "95981594989;94981594989",
     [("(95) 98159-4989", ""), ("(94) 98159-4989", "")]),

    ("6484 Cidade Teleios",
     "DDD 11 x 17 pelo mesmo motivo — Sao Paulo e Aracatuba",
     "11981675371;17981675371",
     [("(11) 98167-5371", ""), ("(17) 98167-5371", "")]),

    ("72 Life and Spirit",
     "irlandes cortado fica VERMELHO, e o bom aparece do lado",
     "35383043618;353876186097",
     [("(35) 38304-3618", "tem 11 dígitos mas não é celular"),
      ("+353 87 618 6097", "")]),

    ("1150 AD Floripa",
     "fixo com 1 digito a mais fica vermelho; o outro numero serve",
     "48322502582;4896014697",
     [("(48) 32250-2582", "tem 11 dígitos mas não é celular"),
      ("(48) 9601-4697", "")]),

    ("6553 Sal da Terra Horto",
     "o celular repetido no meio do fax some; sobram os tres distintos",
     "35359883724;3598156027;35359883724;3588372493;9815-6027;ddd=35",
     [("(35) 35988-3724", "tem 11 dígitos mas não é celular"),
      ("(35) 9815-6027", ""), ("(35) 8837-2493", "")]),

    ("5424 Regenerando Vidas",
     "dois numeros portugueses distintos, um deles montado do st_ddd_sac",
     "351968173332;968173292;ddd=351",
     [("+351 968 173 332", ""), ("+351 968 173 292", "")]),

    ("4474 Nacao de Cristo",
     "celular novo e celular antigo de 8 digitos convivem — sao diferentes",
     "5547997209710;4796651347",
     [("(47) 99720-9710", ""), ("(47) 9665-1347", "")]),

    ("4195 Pentecostal do Avivamento",
     "9 digitos sem DDD some; os tres com DDD ficam",
     "639927346;6392734636;6392029295;6392690922",
     [("(63) 9273-4636", ""), ("(63) 9202-9295", ""), ("(63) 9269-0922", "")]),

    ("2227 Igreja Com Regional",
     "numero de enchimento nao aparece nem em vermelho",
     "99999999999;99999999999",
     []),

    ("4156 XP Investimentos",
     "enchimento com DDD de verdade tambem sai",
     "21999999999;21999999999;9999999999;ddd=21",
     []),

    ("4220 A Mesa Coruripe",
     "so o DDI '55' nao chega a ser telefone",
     "55;55",
     []),
]

# Casos sinteticos: regras que nenhum cliente real exercita hoje, mas que
# quebrariam calado se alguem mexesse.
CASOS_SINTETICOS = [
    ("fixo de Minas que comeca com 353",
     "(35) 3830-4361 NAO e numero irlandes cortado",
     "3538304361",
     [("(35) 3830-4361", "")]),

    ("celular de Curitiba",
     "DDD 41 com 9 no 3o digito e Brasil, nao Suica",
     "41912345678",
     [("(41) 91234-5678", "")]),

    ("celular de Juiz de Fora",
     "DDD 32 idem, nao Belgica",
     "32991234567",
     [("(32) 99123-4567", "")]),

    ("fixo do Rio Grande do Sul",
     "DDD 55 em 10 digitos e Santa Maria, nao o DDI do Brasil",
     "5538104040",
     [("(55) 3810-4040", "")]),

    ("DDD que nao existe",
     "80 nao e DDD brasileiro",
     "8058163324",
     [("(80) 5816-3324", "DDD 80 não existe")]),

    ("zero a esquerda",
     "o formatador tira o 0; o motivo nao pode ler 'DDD 03'",
     "03138304361",
     [("(31) 3830-4361", "")]),

    ("EUA com 11 digitos",
     "1 + 10 = 11 e o tamanho CERTO, nao um numero cortado",
     "17472786803",
     [("+1 747 278-6803", "")]),

    ("lixo que o fallback deixava passar",
     "22 digitos sao dois numeros colados — cliente 2443, nao e telefone",
     "6199519952161999054131",
     []),

    ("o 55 repetido tres vezes",
     "cliente 2174 — o formatador nao reconhece e devolvia '+' + digitos",
     "55555562991808662",
     []),

    ("dois celulares bons que a regra de digito inserido casaria",
     "a trava 'so junta se UM dos dois for furado' protege aqui",
     "11987654321;11998765432",
     [("(11) 98765-4321", ""), ("(11) 99876-5432", "")]),
]


# tipo_numero: 'celular' | 'celular_antigo' | 'fixo'. O meio do caminho veio
# de teste empirico no proprio wa.me — ver o docstring da funcao.
CASOS_TIPO = [
    ("06992588451",   "celular_antigo", "zero a esquerda: ler o cru dava 'DDD 06' "
                                        "e caia em fixo — cliente 4216"),
    ("558399947162",  "celular_antigo", "wa.me abre: conta de antes do nono digito"),
    ("554288351487",  "celular_antigo", "idem, DDD 42"),
    ("553598156027",  "celular_antigo", "6553 ordem 1 — testado, abre"),
    ("553588372493",  "celular_antigo", "6553 ordem 2 — testado, abre"),
    ("553332717755",  "fixo",           "testado: NAO existe no WhatsApp"),
    ("5535359883724", "fixo",           "6553 ordem 3 — testado, nao abre"),
    ("554133334444",  "fixo",           "fixo de Curitiba"),
    ("559091146918",  "desconhecido",   "DDD 90 nao existe: nao da pra dizer o "
                                        "tipo, e chamar de 'fixo' seria falso"),
    ("555099231312",  "desconhecido",   "DDD 50 idem"),
    ("5541995270686", "celular",        "celular com o nono digito"),
    ("5577999221521", "celular",        "idem, montado do st_ddd_sac"),
    ("41765720874",   "celular",        "Suica: 41 e DDD valido, mas e +41 — "
                                        "deduzir dos digitos marcava 'fixo' e o "
                                        "disparo pularia o cliente 1623"),
    ("18045887655",   "celular",        "EUA pelo mesmo motivo — cliente 6504"),
    ("351913178975",  "celular",        "Portugal"),
    ("353876186097",  "celular",        "Irlanda"),
    ("524461383891",  "celular",        "Mexico"),
]


def roda_tipo():
    falhas = []
    print(f"\n=== tipo_numero ({len(CASOS_TIPO)}) ===")
    for numero, esperado, licao in CASOS_TIPO:
        obtido = tipo_numero(numero)
        ok = obtido == esperado
        print(f"  {'ok  ' if ok else 'FALHA'} {numero:16s} {obtido:16s} {licao}")
        if not ok:
            falhas.append((numero, numero, esperado, obtido))
    return falhas


def roda(titulo, casos):
    falhas = []
    print(f"\n=== {titulo} ===")
    for nome, licao, campo, esperado in casos:
        obtido = [(f, p) for _b, f, p in telefones_cliente(campo)]
        ok = obtido == esperado
        print(f"  {'ok  ' if ok else 'FALHA'} {nome:30s} {licao}")
        if not ok:
            falhas.append((nome, campo, esperado, obtido))
    return falhas


def main():
    falhas = roda(f"casos reais ({len(CASOS)})", CASOS)
    falhas += roda(f"casos sinteticos ({len(CASOS_SINTETICOS)})", CASOS_SINTETICOS)
    falhas += roda_tipo()

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} de "
              f"{len(CASOS) + len(CASOS_SINTETICOS) + len(CASOS_TIPO)} casos\n")
        for nome, campo, esperado, obtido in falhas:
            print(f"  {nome}")
            print(f"     cadastro : {campo}")
            print(f"     esperado : {esperado}")
            print(f"     obtido   : {obtido}")
        return 1
    print(f"PASSOU: {len(CASOS)+len(CASOS_SINTETICOS)+len(CASOS_TIPO)} casos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
