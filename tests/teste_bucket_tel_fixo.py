# -*- coding: utf-8 -*-
"""Trava da decisao de voltar pra coluna de mensagem ao desmarcar
'telefone fixo'.

Essa regra ja produziu tres bugs seguidos — cliente com acordo sendo
movido, cooldown de mensagem ignorado, e mensagem ja enviada travando o
movimento quando era justamente o caso em que ele mais rende. Nenhum foi
pego por teste: todos sairam de alguem olhar a tela e perguntar.

Aqui ficam os sete casos escritos. Roda em milissegundos e nao toca no
BigQuery — o que ele cobre e a DECISAO, que foi onde os tres bugs
estiveram, nao a escrita.

    .venv/Scripts/python.exe tests/teste_bucket_tel_fixo.py

Sai com codigo 0 se passou, 1 se falhou.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from data import deve_voltar_pra_mensagem


def cliente(dias, acordo=False, nao_cobrar=False):
    """Cliente minimo, do jeito que o painel monta."""
    return {
        "id": "9999",
        "dias_atraso": dias,
        "_cobracas": [{"dias_atraso": dias}],
        "_tem_acordo": acordo,
        "_grupo_nao_cobrar": nao_cobrar,
    }


def cooldown(msg_dias=None, lig_dias=None, streak=None):
    """Simula o que o load_cooldowns_from_painel deixa no session_state."""
    st.session_state["_painel_dias_msg"] = {"9999": msg_dias} if msg_dias is not None else {}
    st.session_state["_painel_dias_lig"] = {"9999": lig_dias} if lig_dias is not None else {}
    st.session_state["_streak_cooldown_dias"] = {"9999": streak} if streak is not None else {}


# (nome, cliente, acoes de hoje, cooldowns, esperado)
CASOS = [
    ("nada registrado, atraso 30d",
     cliente(30), {}, {}, True),

    ("so mensagem enviada hoje — move pra RECUPERAR a metrica",
     cliente(30), {"msg": True}, {}, True),

    ("ligacao registrada hoje (nao atendeu)",
     cliente(30), {"lig": True}, {}, False),

    ("ligacao atendida hoje",
     cliente(30), {"lig": True, "atend": True}, {}, False),

    ("ligacao + mensagem hoje",
     cliente(30), {"lig": True, "msg": True}, {}, False),

    ("cliente com acordo — acordo e sempre so ligacao",
     cliente(30, acordo=True), {}, {}, False),

    ("cooldown de mensagem ativo (mandou ha 1 dia)",
     cliente(30), {}, {"msg_dias": 1}, False),

    ("atraso de 3 dias — lote nao daria tarefa nenhuma",
     cliente(3), {}, {}, False),

    ("atraso de 6 dias — so mensagem, e ela vale",
     cliente(6), {}, {}, True),

    ("grupo NAO COBRAR da Superlogica",
     cliente(30, nao_cobrar=True), {}, {}, False),

    ("cooldown de mensagem ja vencido (3 dias)",
     cliente(30), {}, {"msg_dias": 3}, True),

    ("streak de 2 ligacoes falhadas — bloqueia lig, nao msg",
     cliente(30), {}, {"streak": 5}, True),
]


def main():
    falhas = []
    print(f"{'caso':58s} {'esperado':9s} {'obtido'}")
    print("-" * 80)
    for nome, cli, acoes, cd, esperado in CASOS:
        cooldown(**cd)
        obtido = deve_voltar_pra_mensagem(cli, acoes)
        ok = obtido == esperado
        marca = "" if ok else "   <-- FALHOU"
        print(f"{nome:58s} {str(esperado):9s} {str(obtido)}{marca}")
        if not ok:
            falhas.append(nome)

    print()
    if falhas:
        print(f"FALHOU: {len(falhas)} de {len(CASOS)} casos")
        for f in falhas:
            print(f"  - {f}")
        return 1
    print(f"PASSOU: {len(CASOS)} casos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
