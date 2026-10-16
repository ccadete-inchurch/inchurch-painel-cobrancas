# -*- coding: utf-8 -*-
"""Proposta de acordo: parcelamento e desconto.

NAO calcula encargos. Quem calcula e o Superlogica, e a conta chega pronta
pelo /inadimplencia (ver data.fetch_encargos_superlogica). Aqui so soma,
divide e formata.

A primeira versao calculava aqui, com as taxas configuradas na empresa — 2%
de multa e 1% ao mes de juros. Chegava perto: na proposta real da Igreja
Evangelica Vinho Novo dava R$ 771,02 contra os R$ 770,74 do documento. Mas
"perto" nao serve pra papel que a igreja assina, e a diferenca vinha de tres
coisas que so o Superlogica sabe:

  juros     0,033% ao DIA, com o valor diario arredondado e multiplicado
            pelos dias. Nao e (dias/30) * 1% sobre o valor exato.
  correcao  por indice mensal, e pode dar ZERO quando o indice CAI — foi o
            caso da Vinho Novo: 178,32 * 104,62704 (out/2026) / 104,96292
            (ago/2026) = 177,75, menos que o principal, entao trava em zero.
            Ja o Somma Church, com 709 dias de atraso, paga R$ 11,08 de
            correcao numa parcela de R$ 137,50.
  base      cobrancas que o painel nao enxerga. Ele le so a
            splgc-cobrancas_competencia-all e ignora a -hist, onde moram
            6.704 cobrancas em aberto. No Somma isso e a diferenca entre os
            R$ 1.204,70 do card e os R$ 2.099,50 de principal real.

Puxando do Superlogica, a proposta da Vinho Novo sai R$ 770,74 exato, nas
cinco cobrancas, sem um centavo de diferenca.

O que continua sendo decidido aqui, porque e da especialista e nao do
sistema: quantas parcelas e quanto de desconto.
"""
from dataclasses import dataclass, field

PARCELAS_MAX = 12    # 177 dos 184 acordos ja fechados ficam em 12 ou menos


@dataclass
class Proposta:
    principal: float = 0.0
    multa: float = 0.0
    juros: float = 0.0
    correcao: float = 0.0
    desconto: float = 0.0
    parcelas: int = 1
    dias_max: int = 0
    detalhe: list = field(default_factory=list)

    @property
    def atualizado(self) -> float:
        """O que o Superlogica cobraria hoje, antes do desconto.

        Soma o 'valorcorrigido' de cada cobranca em vez de principal +
        encargos: os dois batem, mas o valorcorrigido e o numero que o
        Superlogica emite, e e ele que tem que aparecer na proposta.
        """
        return sum(d.get("total", 0.0) for d in self.detalhe)

    @property
    def encargos(self) -> float:
        return self.multa + self.juros + self.correcao

    @property
    def total(self) -> float:
        return max(self.atualizado - self.desconto, 0.0)

    @property
    def valor_parcela(self) -> float:
        return self.total / self.parcelas if self.parcelas > 0 else self.total

    @property
    def pct_desconto(self) -> float:
        return 100.0 * self.desconto / self.atualizado if self.atualizado else 0.0


def montar(itens, parcelas: int = 1, desconto: float = 0.0) -> Proposta:
    """Monta a proposta a partir do que o Superlogica devolveu.

    itens: o que o data.fetch_encargos_superlogica entrega — dicts com
    id_recebimento, vencimento, dias, principal, multa, juros, correcao e
    total (o valorcorrigido da API).

    O desconto NAO e mais zerado quando parcela. A primeira versao fazia
    isso porque o modelo do financeiro so tem desconto na opcao a vista.
    Mas o Caio pediu os dois: a negociacao acontece como "a vista dou 10%,
    parcelado dou 5%", e cada opcao leva o desconto dela. Quem decide qual
    valor vai em cada uma e o dialog.
    """
    p = Proposta(parcelas=max(1, int(parcelas or 1)))
    for it in itens or []:
        p.detalhe.append(dict(it))
        p.principal += float(it.get("principal") or 0)
        p.multa     += float(it.get("multa") or 0)
        p.juros     += float(it.get("juros") or 0)
        p.correcao  += float(it.get("correcao") or 0)
        p.dias_max = max(p.dias_max, int(it.get("dias") or 0))
    p.desconto = min(max(float(desconto or 0), 0.0), p.atualizado)
    return p


def _pct(v: float) -> str:
    """Percentual com virgula, do jeito que se escreve em portugues. Uma casa
    so quando e menor que 1% — R$ 500 em R$ 670 mil arredondava pra '0%'."""
    return (f"{v:.1f}".replace(".", ",") if v < 1 else f"{v:.0f}")
