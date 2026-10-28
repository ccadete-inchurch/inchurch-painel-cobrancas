# -*- coding: utf-8 -*-
"""Claro/escuro: mantem o tema do Streamlit e o nosso apontando pro mesmo lado.

Sao DOIS temas, nao um. O nosso sao os tokens CSS de config.py, que pintam
cards, badges e texto. O do Streamlit pinta o que nunca passa pelo nosso CSS:
placeholder, campo desabilitado, calendario do date picker, dropdown do
selectbox, slider, tooltip, scrollbar, X do dialog. Se os dois discordarem,
metade da tela fica no tema errado.

Por que nao bastava `base` no config.toml: ele e lido uma vez, quando o
servidor sobe, e vale pra todo mundo. Nao da pra ser por pessoa, e o painel
tem varias atendentes ao mesmo tempo. Fixar `base="dark"` deixava o modo
claro remendado — so os widgets que o nosso CSS alcancasse.

Entao o config.toml nao tem `base`, e sim [theme.light] + [theme.dark]. A
ordem de resolucao do Streamlit e:

    tema forcado por config  >  escolha gravada  >  preferencia do sistema

Sem `base`, o primeiro nao existe. Gravando a escolha, o segundo decide — e
o Windows da pessoa (o terceiro) nao interfere, que e o que se espera de um
botao dentro do app.

ONDE a escolha mora e por que em dois lugares:

    localStorage   e' onde o Streamlit LE. Chave dele, formato dele.
    ?tema= na URL  e' onde o Python le. Precisa ser a URL porque alinhar o
                   Streamlit exige recarregar a pagina, e session_state nao
                   sobrevive a um reload.

Quem manda depende de quem sabe. Em aba NOVA a URL nao diz nada e o
localStorage guarda a escolha da pessoa, entao ele dita e a URL segue — sem
isso o padrao (escuro) apagaria a preferencia de quem gosta de claro toda
vez que abrisse o painel. Depois de um clique a URL e' a intencao mais
recente, entao ela dita e o localStorage segue.

RISCO CONHECIDO: `stActiveTheme-<path>-v2` e' chave interna do Streamlit, e
o `2` vem de um CACHED_THEME_VERSION do codigo deles. Num upgrade que mude
isso, o botao para de mandar nos widgets nativos — em silencio. Por isso o
bloco <<fix-base>> do config.py FICA: ele cobre placeholder, campo
desabilitado e X do dialog por CSS. No pior caso o claro volta a ficar
remendado nos outros widgets, que era o estado anterior. Degrada, nao quebra.
Se acontecer: conferir o CACHED_THEME_VERSION no bundle e ajustar _CHAVE_V.
"""
import json

import streamlit as st
import streamlit.components.v1 as components

from config import css_tema

# Versao da chave de localStorage do Streamlit (CACHED_THEME_VERSION).
# Confirmado no bundle da 1.59.2.
_CHAVE_V = 2


def esta_claro() -> bool:
    """O tema atual, lido da URL. Escuro e o padrao do painel."""
    return st.query_params.get("tema") == "claro"


def alternar() -> None:
    """Inverte o tema. Chamado pelo botao da sidebar.

    So mexe na URL: o reload que alinha o Streamlit e' disparado pelo
    _sincronizar(), que roda no proximo render e ve a divergencia.
    """
    st.query_params["tema"] = "escuro" if esta_claro() else "claro"
    st.rerun()


def _sincronizar() -> None:
    """Alinha o localStorage do Streamlit com o ?tema= da URL (ou o contrario).

    Roda num iframe de componente, que tem allow-same-origin e por isso
    alcanca o localStorage da pagina de cima. st.markdown nao serviria: passa
    por DOMPurify e perde o <script>.

    Os dois caminhos so recarregam quando algo REALMENTE difere — senao
    seria loop de reload.
    """
    na_url = st.query_params.get("tema")
    components.html(f"""
    <script>
    (function() {{
      try {{
        var p = window.parent;
        var k = "stActiveTheme-" + p.location.pathname + "-v{_CHAVE_V}";
        var salvo = null;
        try {{ salvo = JSON.parse(p.localStorage.getItem(k)); }} catch (e) {{}}
        var naUrl = {json.dumps(na_url)};

        if (naUrl === null) {{
          // Aba nova: a escolha gravada decide. "System" ou vazio -> escuro,
          // que e o padrao do painel.
          var u = new URL(p.location.href);
          u.searchParams.set("tema", (salvo === "Light") ? "claro" : "escuro");
          p.location.replace(u.toString());   // replace: nao suja o historico
          return;
        }}

        // Depois de um clique: a URL dita, o localStorage segue.
        var alvo = (naUrl === "claro") ? "Light" : "Dark";
        if (salvo !== alvo) {{
          p.localStorage.setItem(k, JSON.stringify(alvo));
          p.location.reload();
        }}
      }} catch (e) {{
        // Chave renomeada num upgrade, ou localStorage bloqueado: o painel
        // segue com os tokens certos e o <<fix-base>> do config.py cobrindo
        // os widgets criticos.
      }}
    }})();
    </script>
    """, height=0)


def aplicar(sincronizar: bool = True) -> None:
    """Injeta os tokens do tema atual e alinha o Streamlit. Chamar no app.py.

    Os tokens vem DEPOIS do CSS global: os dois definem :root e o ultimo
    vence na cascata.

    `sincronizar=False` na tela de login: o alinhamento reescreve a URL, e
    fazer isso no meio do vai-e-volta do OAuth e risco sem retorno — a tela
    de login crava o proprio fundo (#0f1117) e todas as cores dela, entao
    fica escura em qualquer tema de qualquer jeito. Depois do login o sync
    roda e a escolha da pessoa volta.
    """
    st.markdown(css_tema(esta_claro()), unsafe_allow_html=True)
    if sincronizar:
        _sincronizar()
