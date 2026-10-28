# -*- coding: utf-8 -*-
"""Gera o .streamlit/config.toml a partir dos tokens de config.py.

As duas secoes saem dos MESMOS tokens que as telas ja usam, entao a paleta
e uma so: o Streamlit passa a pintar os widgets DELE (placeholder, campo
desabilitado, calendario, dropdown, slider, tooltip, X do dialog) com a
nossa, em vez de escolher cinzas por conta.

    .venv/Scripts/python.exe gera_tema_config.py .streamlit/config.toml

Rodar sempre que mexer em _TOKENS_CLARO / _TOKENS_ESCURO.
"""
import sys
from pathlib import Path

from config import _TOKENS_CLARO, _TOKENS_ESCURO

# Streamlit -> nosso token. Os nomes da esquerda sao os que o Streamlit
# expoe por modo (84 ao todo); aqui vao os que realmente mudam alguma coisa
# visivel no painel.
MAPA = {
    "backgroundColor":                 "bg",
    "secondaryBackgroundColor":        "surface-2",
    "textColor":                       "txt",
    "borderColor":                     "border",
    "primaryColor":                    "brand",
    "linkColor":                       "info",
    "codeBackgroundColor":             "surface-3",
    "codeTextColor":                   "txt",
    "dataframeHeaderBackgroundColor":  "surface-2",
    "dataframeBorderColor":            "border",
    "grayColor":                       "txt-3",
    "grayTextColor":                   "txt-2",
    "greenColor":                      "ok",
    "greenTextColor":                  "ok",
    "redColor":                        "erro",
    "redTextColor":                    "erro",
    "orangeColor":                     "laranja",
    "orangeTextColor":                 "laranja",
    "yellowColor":                     "amarelo",
    "yellowTextColor":                 "amarelo",
    "blueColor":                       "info",
    "blueTextColor":                   "info",
    "violetColor":                     "roxo",
    "violetTextColor":                 "roxo",
    # A sidebar tem fundo proprio no painel (--surface-3), entao nao pode
    # herdar o backgroundColor geral.
    "sidebar.backgroundColor":         "surface-3",
    "sidebar.secondaryBackgroundColor": "surface-2",
    "sidebar.textColor":               "txt-2",
    "sidebar.borderColor":             "border",
    "sidebar.primaryColor":            "brand",
}


def secao(nome, tokens):
    # As chaves com ponto (sidebar.x) viram subsecao propria no TOML.
    raiz = {k: v for k, v in MAPA.items() if "." not in k}
    side = {k.split(".", 1)[1]: v for k, v in MAPA.items() if k.startswith("sidebar.")}
    linhas = [f"[theme.{nome}]"]
    linhas += [f'{k} = "{tokens[t]}"' for k, t in raiz.items()]
    linhas += ["", f"[theme.{nome}.sidebar]"]
    linhas += [f'{k} = "{tokens[t]}"' for k, t in side.items()]
    return "\n".join(linhas)


CAB_PAINEL = """# NAO EDITAR NA MAO — gerado a partir dos tokens de config.py
# (_TOKENS_CLARO / _TOKENS_ESCURO). Mexeu num token? Rode o gerador de novo,
# senao o Streamlit pinta os widgets dele com a paleta velha.
#
# Nao existe `base` aqui, e e de proposito. Com `base` fixo o Streamlit
# escolhe o cinza de placeholder, campo desabilitado, calendario, dropdown,
# slider e tooltip pensando num fundo so — e no outro modo esses widgets
# saem ilegiveis. Sem `base`, ele decide entre as duas secoes abaixo, e quem
# decide por ele e o tema.py: o botao da sidebar grava a escolha no
# localStorage que o proprio Streamlit le.
#
# A ordem de resolucao dele e: tema forcado por config > escolha gravada >
# preferencia do sistema. Como gravamos a escolha, o Windows da pessoa nao
# interfere.
"""

CAB_DEMO = """# DEMO — nao e o config do painel.
# Gerado por gera_config_nativo.py a partir dos tokens do config.py.

[server]
headless = true

[browser]
gatherUsageStats = false
"""

destino = Path(sys.argv[1])
demo = len(sys.argv) > 2 and sys.argv[2] == "demo"
destino.parent.mkdir(parents=True, exist_ok=True)
destino.write_text(
    (CAB_DEMO if demo else CAB_PAINEL) + "\n"
    + secao("light", _TOKENS_CLARO) + "\n\n"
    + secao("dark", _TOKENS_ESCURO) + "\n",
    encoding="utf-8")
print(f"escrito: {destino}")
print(f"{len(MAPA)} opcoes por modo, {len(MAPA)*2} no total")
