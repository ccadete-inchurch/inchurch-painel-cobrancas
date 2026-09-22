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
        f'padding:3px 10px;font-size:11.5px;color:#fcd34d;margin:6px 6px 0 0">{c}</span>'
        for c in chips
    )
    st.markdown(
        # Faixa lateral âmbar em vez de borda inteira: menos "alarme", mais
        # aviso. O texto antigo vinha sem acentos e em termos técnicos
        # ("time travel", "pipelines criticos"), que ninguém fora do BI lê.
        f'<div style="background:rgba(245,158,11,.08);border-left:3px solid #f59e0b;'
        f'border-radius:6px;padding:12px 16px;margin:0 24px 14px;'
        f'display:flex;align-items:flex-start;gap:12px">'
        f'<span style="font-size:16px;line-height:1.3;flex-shrink:0">⚠️</span>'
        f'<div style="flex:1;min-width:0">'
        f'<div style="font-size:13.5px;font-weight:700;color:#fbbf24;'
        f'letter-spacing:.2px">{titulo}</div>'
        f'<div style="font-size:12.5px;color:#fde68a;line-height:1.5;margin-top:3px">{linha}</div>'
        f'<div>{chips_html}</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


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
            f'<span style="background:rgba(124,194,67,.2);color:#7cc243;font-size:11px;'
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
            # cinza #2a2f42, padding 6px 14px, font 13px) — só o bullet fica
            # verde como indicador de presença.
            online_html = "".join(
                f'<span style="display:inline-flex;align-items:center;gap:8px;'
                f'background:#1e2333;border:1px solid #2a2f42;border-radius:20px;'
                f'padding:6px 14px;font-size:13px;color:#e8eaf0;font-weight:500">'
                f'<span style="width:8px;height:8px;background:#7cc243;border-radius:50%;display:inline-block"></span>'
                f'{u["nome"].split()[0] if u["nome"] else u["email"]}'
                f'</span>'
                for u in outros_online[:4]  # cap pra não estourar o header
            )

        # Layout: presença do time na esquerda; status/usuário à direita.
        st.markdown(f"""
        <div style="background:#181c26;border-bottom:1px solid #2a2f42;padding:0 24px;height:60px;display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,.15)">
          <div style="display:flex;align-items:center;gap:8px">{online_html}</div>
          <div style="display:flex;align-items:center;gap:12px">
            <span style="font-size:13px;color:#8b94a5;background:#1e2333;padding:6px 14px;border-radius:20px;border:1px solid #2a2f42">Atualizado: {upd}</span>
            <span style="font-size:13px;background:#1e2333;border:1px solid #2a2f42;border-radius:20px;padding:6px 14px;display:inline-flex;align-items:center;gap:8px;font-weight:500">
              <span style="width:8px;height:8px;background:#7cc243;border-radius:50%;display:inline-block"></span>{current_nome()}{role_tag}
            </span>
          </div>
        </div>""", unsafe_allow_html=True)

    _header_dynamic()
    _banner_bq_stale()
