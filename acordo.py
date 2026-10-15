# -*- coding: utf-8 -*-
"""Proposta de acordo: valor atualizado, parcelamento e desconto.

O valor que o Superlogica mostra e o painel exibe e o PRINCIPAL — sem juros
nem multa. Quando a especialista negocia, ela precisa do valor de hoje, e
hoje ela calcula na mao ou pede pro financeiro.

As duas taxas sao as do cadastro da cobranca no Superlogica:

    vl_txmulta_emp = 2.00    multa, uma vez, quando atrasa
    vl_txjuros_emp = 1.00    juros, 1% ao mes

Conferidas contra 118 acordos ja fechados, lidos pelo endpoint /acordos:
a multa fica entre 1,9% e 2,1% do principal em 99 deles (84%), e os juros
divididos pelo principal dao uma distribuicao continua de 0,5 a 32 "meses",
que e o que se espera de 1% x meses — nao e valor fixo nem tem teto.

Tres decisoes que os dados NAO resolvem, assumidas aqui e sinalizadas na
tela pra especialista conferir:

1. Os juros contam por COBRANCA, cada uma do proprio vencimento. Usar o
   atraso da parcela mais antiga pra todas superestimaria: um cliente com
   parcela de 600 dias e outra de 30 pagaria 20% em cima das duas.
2. Pro rata por dia (dias/30), nao mes cheio arredondado pra cima. Mes
   cheio da um numero maior e o Superlogica pode fazer diferente — por isso
   a tela mostra os dias, pra dar pra conferir.
3. A linha 'AtualizacaoMonetaria' que aparece em 112 dos 195 acordos fica
   FORA. Mediana de 0,34% do principal, e sem saber o indice nao da pra
   reproduzir. Se tiver que entrar, e so somar aqui.

O desconto e opcional e so existe a vista: parcelou, nao tem desconto. Ele
NAO e calculado — nos 195 acordos lidos a mediana de desconto e 0% e nao
ha relacao com a quantidade de parcelas, ou seja, e decisao de quem
negocia, nao regra da casa.
"""
from dataclasses import dataclass, field

TAXA_MULTA = 0.02    # 2%, uma vez
TAXA_JUROS = 0.01    # 1% ao mes
PARCELAS_MAX = 12    # 177 dos 184 acordos lidos ficam em 12 ou menos


@dataclass
class Proposta:
    principal: float = 0.0
    multa: float = 0.0
    juros: float = 0.0
    desconto: float = 0.0
    parcelas: int = 1
    dias_max: int = 0
    detalhe: list = field(default_factory=list)

    @property
    def atualizado(self) -> float:
        """Principal + multa + juros, antes do desconto."""
        return self.principal + self.multa + self.juros

    @property
    def total(self) -> float:
        return max(self.atualizado - self.desconto, 0.0)

    @property
    def valor_parcela(self) -> float:
        return self.total / self.parcelas if self.parcelas > 0 else self.total

    @property
    def pct_desconto(self) -> float:
        return 100.0 * self.desconto / self.atualizado if self.atualizado else 0.0

    @property
    def pct_acrescimo(self) -> float:
        return 100.0 * (self.multa + self.juros) / self.principal if self.principal else 0.0


def calcular(cobrancas, parcelas: int = 1, desconto: float = 0.0) -> Proposta:
    """Monta a proposta a partir das cobrancas em atraso do cliente.

    cobrancas: iteravel de dicts com 'valor' e 'dias_atraso' — e o formato
    que o cliente["_cobracas"] do data.py ja entrega.

    Desconto vira 0 automaticamente quando parcelas > 1: a regra e que so
    existe desconto a vista, e deixar o valor passar escondido numa aba que
    a tela esconde seria o tipo de erro que ninguem ve.
    """
    p = Proposta(parcelas=max(1, int(parcelas or 1)))
    if p.parcelas > 1:
        desconto = 0.0

    for c in cobrancas or []:
        try:
            valor = float(c.get("valor") or 0)
        except (TypeError, ValueError):
            continue
        dias = c.get("dias_atraso") or 0
        try:
            dias = int(dias)
        except (TypeError, ValueError):
            dias = 0
        if valor <= 0 or dias <= 0:
            continue
        multa = valor * TAXA_MULTA
        juros = valor * TAXA_JUROS * (dias / 30.0)
        p.principal += valor
        p.multa += multa
        p.juros += juros
        p.dias_max = max(p.dias_max, dias)
        p.detalhe.append({
            # id_recebimento e o numero do boleto: conferi os cinco da
            # proposta real da Vinho Novo (122661, 122662, 126436, 128066,
            # 129623) contra o BigQuery e batem numero, vencimento e valor.
            # E a coluna "No COBRANCA" do PDF — sem ele a igreja nao
            # reconhece a cobranca que esta sendo negociada.
            "id_recebimento": str(c.get("id_recebimento") or ""),
            "valor": valor, "dias": dias, "multa": multa, "juros": juros,
            "vencimento": c.get("vencimento", ""),
            "total": valor + multa + juros,
        })

    p.desconto = min(max(float(desconto or 0), 0.0), p.atualizado)
    return p



def _pct(v: float) -> str:
    """Percentual com virgula, do jeito que se escreve em portugues. Uma casa
    so quando e menor que 1% — R$ 500 em R$ 670 mil arredondava pra '0%'."""
    return (f"{v:.1f}".replace(".", ",") if v < 1 else f"{v:.0f}")


def texto_whatsapp(nome_cliente: str, p: Proposta) -> str:
    """A proposta em texto corrido, pra especialista colar no WhatsApp.

    Sem markdown de tela: o WhatsApp usa *negrito* com um asterisco so, e
    tabela nao existe la.
    """
    m = lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    linhas = [
        f"Olá! Segue a proposta para regularizar a pendência"
        + (f" da {nome_cliente}" if nome_cliente else "") + ":",
        "",
        f"Valor original: {m(p.principal)}",
        f"Multa (2%): {m(p.multa)}",
        f"Juros (1% ao mês): {m(p.juros)}",
        f"*Total atualizado: {m(p.atualizado)}*",
    ]
    if p.desconto > 0:
        linhas += [
            "",
            f"Desconto para pagamento à vista: -{m(p.desconto)}"
            + f" ({_pct(p.pct_desconto)}%)",
            f"*Valor à vista: {m(p.total)}*",
        ]
    elif p.parcelas > 1:
        linhas += [
            "",
            f"*Parcelado em {p.parcelas}x de {m(p.valor_parcela)}*",
        ]
    else:
        linhas += ["", f"*Valor à vista: {m(p.total)}*"]
    return "\n".join(linhas)
