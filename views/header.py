import streamlit as st

from auth import current_nome, current_role, current_email
from data import get_store, ping_online, get_online_users, diagnosticar_bq_saude


_ROLE_DISPLAY = {
    "admin":     "ADMIN",
    "atendente": "SPECIALIST",
}


def _banner_bq_stale():
    """Banner amarelo visivel SO PRA ADMIN quando BQ Splgc esta com dados
    ruins/velhos. Aparece em todas as telas via render_header().

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
    st.markdown(
        f'<div style="background:#3d2f0f;border:1px solid #f59e0b;'
        f'border-radius:8px;padding:12px 18px;margin:0 24px 12px;'
        f'display:flex;align-items:flex-start;gap:12px">'
        f'<span style="font-size:20px;line-height:1;flex-shrink:0">⚠️</span>'
        f'<div style="flex:1;font-size:13px;color:#fde68a;line-height:1.5">'
        f'<div style="font-weight:700;margin-bottom:4px;color:#fbbf24">'
        f'Dados BQ desatualizados — mostrando ultima versao confiavel'
        f'</div>'
        f'<div>{diag["detalhes"]}</div>'
        f'<div style="margin-top:6px;color:#d97706;font-size:12px">'
        f'Painel esta usando time travel do BQ automaticamente. '
        f'Snapshots do dia nao estao sendo gravados.'
        f'</div>'
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
