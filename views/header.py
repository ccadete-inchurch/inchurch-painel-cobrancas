import re

import streamlit as st

from auth import current_nome, current_role, current_email
from helpers import _BRT
from data import get_store, ping_online, get_online_users, diagnosticar_bq_saude


_ROLE_DISPLAY = {
    "admin":     "ADMIN",
    "atendente": "SPECIALIST",
}


def _texto_bq_stale(diag):
    """Monta o aviso de dados desatualizados em linguagem simples.

    Devolve (titulo, linha, chips). O `detalhes` cru do diagnóstico é
    técnico ("1 pipeline(s) critico(s) Splgc nao rodaram hoje. Time travel:
    2026-09-21.") e entra só como fallback de motivo desconhecido.
    """
    _dt = diag.get("ts_ultimo_bom")
    dia = ""
    if _dt is not None:
        try:
            dia = _dt.astimezone(_BRT).strftime("%d/%m")
        except Exception:
            dia = ""
    if not dia:
        _m = re.search(r"Time travel:\s*(\d{4})-(\d{2})-(\d{2})", diag.get("detalhes") or "")
        if _m:
            dia = f"{_m.group(3)}/{_m.group(2)}"

    chips = ["Pagamentos do dia continuam aparecendo (API Superlógica)",
             "Snapshot de hoje não gravado"]
    # Nomes curtos dos pipelines que faltaram: "Pipeline de cobranças por
    # liquidação Inchurch, 01/01/2025 a 03/31/2025" -> "liquidação 01/01/2025
    # a 03/31/2025". Até 3; o resto vira "e mais N".
    _falt = [re.sub(r"^Pipeline de cobranças por\s*", "", f).replace(" Inchurch,", "")
             for f in (diag.get("faltando") or [])]
    if _falt:
        _lista = ", ".join(_falt[:3])
        if len(_falt) > 3:
            _lista += f" e mais {len(_falt) - 3}"
        _quais = f" Não rodou: {_lista}."
    else:
        _quais = ""
    if diag.get("motivo") == "pipelines_faltando" and dia:
        return ("Time travel: mostrando os dados de " + dia,
                "A carga diária do Superlógica não rodou hoje, então o painel está "
                "usando a última versão confiável." + _quais,
                chips)
    if diag.get("motivo") == "pipelines_faltando":
        return ("Dados podem estar incorretos",
                "A carga diária do Superlógica não rodou hoje e não há versão "
                "confiável nos últimos 14 dias (sem time travel possível)." + _quais,
                ["Verifique o pipeline antes de usar os números"])
    return ("Dados do BigQuery desatualizados",
            diag.get("detalhes") or "O painel está usando a última versão confiável.",
            chips)


def _banner_bq_stale():
    """Aviso visivel SO PRA ADMIN quando BQ Splgc esta com dados ruins/velhos.
    Aparece em todas as telas via render_header().

    Motivo de ser so admin: atendentes/gestores nao podem agir sobre
    pipeline BQ. Ver o alerta cria confusao sem acao possivel. Admin
    (voce/BI) sabe reprocessar partiçoes, apagar snapshots ruins etc.

    Painel continua funcionando com time travel silencioso pra todos.
    """
    if current_role() != "admin":
        return
    diag = diagnosticar_bq_saude()
    if diag["e_confiavel"]:
        return
    titulo, linha, chips = _texto_bq_stale(diag)
    chips_html = "".join(
        f'<span style="display:inline-block;background:rgba(245,158,11,.14);'
        f'border:1px solid rgba(245,158,11,.35);border-radius:20px;'
        f'padding:3px 10px;font-size:11.5px;color:var(--amarelo);margin:6px 6px 0 0">{c}</span>'
        for c in chips
    )
    st.markdown(
        # Faixa lateral âmbar em vez de borda inteira: menos "alarme", mais
        # aviso. O texto antigo vinha sem acentos e em termos técnicos
        # ("time travel", "pipelines criticos"), que ninguém fora do BI lê.
        f'<div style="background:rgba(245,158,11,.08);border-left:3px solid var(--alerta);'
        f'border-radius:6px;padding:12px 16px;margin:0 24px 14px;'
        f'display:flex;align-items:flex-start;gap:12px">'
        f'<span style="font-size:16px;line-height:1.3;flex-shrink:0">⚠️</span>'
        f'<div style="flex:1;min-width:0">'
        f'<div style="font-size:13.5px;font-weight:700;color:var(--alerta);'
        f'letter-spacing:.2px">{titulo}</div>'
        f'<div style="font-size:12.5px;color:var(--amarelo-2);line-height:1.5;margin-top:3px">{linha}</div>'
        f'<div>{chips_html}</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _botao_tema():
    """Sol/lua no canto direito da topbar.

    O rotulo e vazio de proposito: o icone ja diz tudo e o texto estouraria o
    circulo. Quem explica o clique e o `help`. O icone mostra pra ONDE o
    clique leva, nao o estado atual — sol quando esta escuro, lua quando esta
    claro.
    """
    claro = st.session_state.get("tema_claro", False)
    if st.button("", key="btn_tema",
                 icon=":material/dark_mode:" if claro else ":material/light_mode:",
                 help="Mudar para o modo escuro" if claro else "Mudar para o modo claro"):
        st.session_state["tema_claro"] = not claro
        st.rerun()


def render_header():
    # Fragment auto-refresh a cada 30s — pinga a sessão atual e re-renderiza
    # a lista de "online agora" sem precisar reload da página.
    @st.fragment(run_every=30)
    def _header_dynamic():
        store    = get_store()
        upd      = store.get("ultima_atualizacao") or "—"
        _r       = current_role()
        _r_label = _ROLE_DISPLAY.get(_r, _r.upper() if _r else "")
        role_tag = (
            f'<span style="background:rgba(124,194,67,.2);color:var(--brand);font-size:11px;'
            f'padding:3px 10px;border-radius:12px;font-weight:700;margin-left:8px;'
            f'letter-spacing:.5px">{_r_label}</span>'
        ) if _r_label else ""

        # Mantém a sessão como ativa + lê quem tá online agora
        ping_online(current_email(), current_nome())
        online = get_online_users(janela_s=90)

        # Render dos "pills" de online — primeiro nome só pra caber.
        # Exclui o próprio usuário pra não ficar redundante (já aparece à
        # direita no badge de identificação).
        _meu_email = current_email() or ""
        outros_online = [u for u in online if u["email"] != _meu_email]
        online_html = ""
        if outros_online:
            # Mesmo estilo das pills "Atualizado" e badge do usuário (border
            # cinza var(--border), padding 6px 14px, font 13px) — só o bullet fica
            # verde como indicador de presença.
            online_html = "".join(
                f'<span style="display:inline-flex;align-items:center;gap:8px;'
                f'background:var(--surface-2);border:1px solid var(--border);border-radius:20px;'
                f'padding:6px 14px;font-size:13px;color:var(--txt);font-weight:500;'
                f'white-space:nowrap;flex-shrink:0">'
                f'<span style="width:8px;height:8px;background:var(--brand);border-radius:50%;display:inline-block;flex-shrink:0"></span>'
                f'{u["nome"].split()[0] if u["nome"] else u["email"]}'
                f'</span>'
                for u in outros_online[:4]  # cap pra não estourar o header
            )

        # Layout: presença do time na esquerda; status/usuário à direita.
        #
        # Em tela estreita o header quebrava em cima de si mesmo: a altura era
        # height:60px FIXO, e sem white-space:nowrap o "Atualizado: ..." e o
        # nome quebravam em duas linhas dentro de uma caixa que nao crescia —
        # dai o texto saindo por cima.
        #
        # Agora: min-height no lugar de height (se um dia quebrar, cresce em
        # vez de transbordar), nowrap nos dois pills da direita, e o bloco da
        # direita com flex-shrink:0 — quem cede espaco e a lista de "online
        # agora" da esquerda, que e decorativa e pode perder o ultimo nome
        # sem prejuizo. As classes servem as regras responsivas do config.py.
        st.markdown(f"""
        <div class="topbar" style="background:var(--surface);border-bottom:1px solid var(--border);padding:0 24px;min-height:60px;display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:24px;box-shadow:var(--sombra-barra)">
          <div class="topbar-online" style="display:flex;align-items:center;gap:8px;min-width:0;overflow:hidden">{online_html}</div>
          <div class="topbar-status" style="display:flex;align-items:center;gap:12px;flex-shrink:0">
            <span class="topbar-upd" style="font-size:13px;color:var(--txt-2);background:var(--surface-2);padding:6px 14px;border-radius:20px;border:1px solid var(--border);white-space:nowrap">Atualizado: {upd}</span>
            <span style="font-size:13px;background:var(--surface-2);border:1px solid var(--border);border-radius:20px;padding:6px 14px;display:inline-flex;align-items:center;gap:8px;font-weight:500;white-space:nowrap">
              <span style="width:8px;height:8px;background:var(--brand);border-radius:50%;display:inline-block;flex-shrink:0"></span>{current_nome()}{role_tag}
            </span>
          </div>
        </div>""", unsafe_allow_html=True)

    # Os dois no mesmo container porque o botao de tema e ancorado POR CIMA da
    # barra — o CSS do config.py precisa de um pai comum pra isso.
    #
    # E o botao fica FORA do fragmento: dentro dele o st.rerun() teria escopo
    # de fragmento, e os tokens do tema sao injetados no app.py, fora daqui.
    # A cor so mudaria na interacao seguinte.
    with st.container(key="topbar_wrap"):
        _header_dynamic()
        _botao_tema()
    _banner_bq_stale()
