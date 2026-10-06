# -*- coding: utf-8 -*-
"""Trava de seguranca para a mudanca do telefone no painel.

Compara, cliente a cliente, a lista de telefones que o painel monta HOJE com a
que montaria DEPOIS de ler os quatro campos do cadastro.

Falha numa unica condicao: um numero QUE DA PRA DISCAR sumir da tela. Essa e'
a unica coisa que a atendente nao pode perder. Numero furado pode sumir — e'
o que acontece quando a dedupe funde a versao suja com a limpa do mesmo
telefone — desde que sobre algum numero para o cliente.

A trava de proposito nao repete as regras de fusao do helpers: se repetisse,
aprovaria qualquer fusao que o helpers fizesse, inclusive uma errada.

Ganhar numero invalido novo nao falha: ficou definido exibi-los em vermelho,
sem icone de WhatsApp, em vez de esconde-los.

Rodar antes e depois de mexer em helpers.py / data.py:

    .venv/Scripts/python.exe scripts/teste_regressao_telefone.py

Sai com codigo 0 se passou, 1 se falhou.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data as D
from helpers import (formatar_telefone, telefone_wa_link, fmt_tel_lista,
                     telefones_cliente, problema_telefone)

so = lambda v: re.sub(r"\D", "", str(v or ""))

DDD_OK = {11,12,13,14,15,16,17,18,19,21,22,24,27,28,31,32,33,34,35,37,38,41,42,43,44,45,46,47,48,49,
          51,53,54,55,61,62,63,64,65,66,67,68,69,71,73,74,75,77,79,81,82,83,84,85,86,87,88,89,
          91,92,93,94,95,96,97,98,99}
# tamanho do numero nacional (sem DDI) por pais, so para DDIs de 3 digitos:
# os de 1-2 digitos coincidem com DDD brasileiro e a leitura fica ambigua.
TAM_NACIONAL_3 = {"351": 9, "352": 9, "353": 9, "244": 9, "258": 9,
                  "591": 8, "595": 9, "598": 8}


def invalido(d):
    """O numero, do jeito que esta, leva a lugar nenhum.

    Nao basta olhar a quantidade de digitos: nos EUA 1+10=11 e correto, na
    Franca/Espanha 2+9=11 tambem. So da para afirmar que esta cortado quando
    o DDI tem 3 digitos (nenhum coincide com DDD brasileiro).
    """
    if not d or len(set(d)) <= 2:
        return True
    # numero de enchimento: DDD de verdade seguido de um digito so
    # repetido. (21) 99999-9999 tem forma de celular valido, mas nao e o
    # telefone de ninguem — ficou definido nem exibir.
    nucleo = d[2:] if d.startswith("55") and len(d) > 11 else d
    if (len(nucleo) in (10, 11) and int(nucleo[:2]) in DDD_OK
            and len(set(nucleo[2:])) == 1):
        return True
    for ddi, tam in TAM_NACIONAL_3.items():
        if d.startswith(ddi):
            return (len(d) - len(ddi)) != tam
    if formatar_telefone(d) in ("", "—"):
        return True
    wa = telefone_wa_link(d)
    if not wa:
        return True
    if wa.startswith("55") and not d.startswith("55"):
        n = wa[2:]
        if len(n) in (10, 11) and int(n[:2]) not in DDD_OK:
            return True
        if len(n) == 11 and n[2] != "9":
            return True
    return False


def monta(campos, usar_campos_novos):
    """A lista de telefones do cliente, como o painel monta.

    usar_campos_novos=False reproduz o comportamento ANTIGO (so fax e
    telefone, sem dedupe por digito). True chama telefones_cliente(), que e
    a funcao que roda em producao — o teste guarda o codigo de verdade, nao
    uma copia dele.
    """
    if not usar_campos_novos:
        brutos = fmt_tel_lista(campos.get("fax")) + fmt_tel_lista(campos.get("telefone"))
        saida = []
        for t in brutos:
            d = so(t)
            if not d or len(set(d)) <= 1 or formatar_telefone(d) in ("", "—"):
                continue
            if d not in saida:
                saida.append(d)
        return saida

    # DEPOIS: a string que o data.py monta, na mesma ordem — os tres campos
    # de numero e o st_ddd_sac marcado no fim (ele completa qualquer um dos
    # tres, nao so o st_telefone_sac)
    partes = [str(campos.get(k) or "").strip()
              for k in ("celular", "fax", "telefone")
              if str(campos.get(k) or "").strip()]
    ddd = str(campos.get("ddd") or "").strip()
    if ddd:
        partes.append("ddd=" + ddd)
    return [so(b) for b, _f, _p in telefones_cliente(";".join(partes))]


def carregar():
    """celular e ddd ja estao no BigQuery — e' de la que o painel le."""
    c = D.get_bq_client()
    return c.query("""
        WITH m AS (
            SELECT CAST(id_sacado_sac AS STRING) cid, MAX(st_nome_sac) nome,
                   MAX(st_telefone_sac) telefone, MAX(st_fax_sac) fax,
                   MAX(st_celular_sac) celular, MAX(st_ddd_sac) ddd
            FROM `business-intelligence-467516.Splgc.splgc-clientes-inchurch`
            GROUP BY 1),
        g AS (SELECT DISTINCT CAST(id_sacado_sac AS STRING) cid, grupo
              FROM `business-intelligence-467516.Splgc.splgc-grupo`
              WHERE grupo IN ('Ana Carolina','Priscila Oliveira')),
        s AS (SELECT CAST(id_sacado_sac AS STRING) cid, ROUND(SUM(valor_saldo),2) devido
              FROM `business-intelligence-467516.inadimplencia_painel_cobrancas.cobrancas_snapshot_diario`
              WHERE data_snapshot = (SELECT MAX(data_snapshot)
                                     FROM `business-intelligence-467516.inadimplencia_painel_cobrancas.cobrancas_snapshot_diario`)
                AND dias_atraso >= 1
              GROUP BY 1)
        SELECT m.*, g.grupo, s.devido FROM m
        LEFT JOIN g USING (cid) LEFT JOIN s USING (cid)
    """).to_dataframe()


def main():
    df = carregar()
    print(f"clientes: {len(df)}\n")

    perdidos, ruins_novos = [], []
    ficaram_sem = 0
    inval_antes = inval_depois = 0
    ganharam = 0

    for _, r in df.iterrows():
        base = {"telefone": r.telefone, "fax": r.fax}
        extra = dict(base, celular=r.celular, ddd=r.ddd)
        antes = monta(base, False)
        depois = monta(extra, True)

        for d in antes:
            # continua sendo o mesmo numero, so guardado de outro jeito
            # (com o 55 na frente, com o DDD que faltava, inteiro em vez de
            # cortado). Checagem frouxa de proposito: ela so pode DEIXAR
            # passar uma perda, nunca inventar uma.
            #
            # Compara tambem sem o 55 do Brasil: o numero que sobrevive a
            # dedupe pode ficar guardado com o DDI, e ai nenhuma das
            # comparacoes abaixo casa com a versao sem ele (cliente 4532,
            # 5521995002430 sobrevivendo no lugar de 2199500243).
            s55 = lambda v: v[2:] if v.startswith("55") and len(v) in (12, 13) else v
            dn = s55(d)
            if any(x == d or x[-8:] == d[-8:] or x.endswith(d)
                   or (len(x) > len(d) and x.startswith(d))
                   or s55(x) == dn or s55(x).endswith(dn)
                   or (len(s55(x)) > len(dn) and s55(x).startswith(dn))
                   for x in depois):
                continue
            # O numero some legitimamente quando foi fundido com outro: a
            # versao inteira dele mesmo, ou a versao limpa de um numero que
            # o cadastro repetiu sujo (DDD digitado duas vezes, digito solto
            # na frente, 9 do celular faltando).
            #
            # A trava aqui NAO repete as regras de fusao do helpers — se
            # repetisse, o teste aprovaria qualquer fusao que o helpers
            # fizesse, inclusive uma errada. Ela afirma o que de fato
            # importa: numero que DA PRA DISCAR nunca pode sumir da tela.
            # Se o que sumiu ja era um numero furado e sobrou algum, a
            # atendente nao perdeu nada; se sumiu um numero bom, e' falha.
            if not invalido(d):
                perdidos.append((r.cid, r.nome, d))
        if antes and not depois:
            # nao e falha: so acontece quando tudo que o cliente tinha era
            # numero de enchimento (99999999999), que ficou definido nem
            # exibir. Contado aqui so pra ficar visivel.
            ficaram_sem += 1
        if len(depois) > len(antes):
            ganharam += 1
        if r.grupo:
            inval_antes += sum(invalido(x) for x in antes)
            inval_depois += sum(invalido(x) for x in depois)
        if r.devido == r.devido and r.devido is not None:   # devendo
            for d in depois:
                if invalido(d) and not any(x[-8:] == d[-8:] for x in antes):
                    ruins_novos.append((r.cid, r.nome, d, r.devido))

    print(f"clientes que ganham numero        : {ganharam}")
    print(f"clientes que ficam sem numero     : {ficaram_sem}"
          f"  (so tinham numero de enchimento)")
    print(f"numeros invalidos na carteira     : {inval_antes} -> {inval_depois}")

    falhas = []
    if perdidos:
        falhas.append(f"{len(perdidos)} numeros desapareceriam da tela")
        for cid, nome, d in perdidos[:10]:
            print(f"   PERDA  {cid} {str(nome)[:28]:28s} {d}")
    if ruins_novos:
        # nao falha: ficou definido exibir esses em vermelho, sem icone de
        # WhatsApp. Eles ja existem no cadastro — a mudanca so os torna visiveis.
        print()
        print(f"{len(ruins_novos)} devedores ganham numero invalido "
              f"(serao exibidos em vermelho):")
        for cid, nome, d, dev in ruins_novos[:10]:
            print(f"   {cid} {str(nome)[:28]:28s} {d}  (R$ {dev:,.2f})")

    print()
    if falhas:
        print("FALHOU:")
        for f in falhas:
            print(f"  - {f}")
        return 1
    print("PASSOU: nenhum numero discavel sumiu da tela.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
