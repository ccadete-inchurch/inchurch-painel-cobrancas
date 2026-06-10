from datetime import date

import streamlit as st

import time as _time

from helpers import get_hist, fmt_moeda_plain, dias_html, get_ultimo_contato_n8n_dias, get_msg_concluida_dias, get_painel_dias_lig, get_painel_dias_lig_tentada, get_painel_dias_msg, get_painel_acoes_hoje, hoje_lote, get_streak_cooldown_dias
from data import calcular_score, recomendar_acao, load_mensagens_from_bq, load_cooldowns_from_painel, gerar_tarefas_do_dia, atualizar_tarefas_bq, get_lote_buckets_bq, fetch_regularizados_do_dia, fetch_ids_em_qualquer_lote_hoje, _EMAIL_GRUPO
from auth import current_nome, current_role, current_email
from views.dialog import dialog_editar


def _detectar_virada_dia():
    """Detecta virada do dia operacional (08:15 BRT) e força rerun do app
    pra renovar o lote do dia. Chamado dentro do fragment dinâmico."""
    hoje = hoje_lote()
    if st.session_state.get("_dia_ativo") != hoje:
        st.session_state["_dia_ativo"] = hoje
        st.rerun(scope="app")
        return True
    return False


def _atualizar_dados_periodicos(store_clientes):
    """Recarrega N8N e painel se passou tempo suficiente. Não faz rerun —
    chamada dentro do fragment dinâmico, que se reroda sozinho via run_every."""
    last_n8n = st.session_state.get("_metricas_ts", 0)
    if _time.time() - last_n8n > 50:
        load_mensagens_from_bq()
        st.session_state["_metricas_ts"] = _time.time()

    last_painel = st.session_state.get("_painel_refresh_ts", 0)
    if _time.time() - last_painel > 80:
        status_map = st.session_state.get("_msg_status", {})
        if status_map and store_clientes:
            for _atd in _EMAIL_GRUPO.values():
                atualizar_tarefas_bq(_atd, status_map, store_clientes)
        load_cooldowns_from_painel()
        st.session_state["_painel_refresh_ts"] = _time.time()


def _acao_badge(acoes: list[str]) -> str:
    if "urgente" in acoes:
        return '<span style="background:rgba(239,68,68,.18);color:#ff5555;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">🔥 Urgente</span>'
    if "ligar" in acoes and "mensagem" in acoes:
        return '<span style="background:rgba(124,194,67,.15);color:#7cc243;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">📞 Ligar</span> <span style="background:rgba(95,163,255,.15);color:#5fa3ff;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">💬 Msg</span>'
    if "ligar" in acoes:
        return '<span style="background:rgba(124,194,67,.15);color:#7cc243;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">📞 Ligar</span>'
    if "mensagem" in acoes:
        return '<span style="background:rgba(95,163,255,.15);color:#5fa3ff;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">💬 Mensagem</span>'
    return '<span style="background:rgba(107,114,128,.15);color:#6b7280;font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px">✓ Aguardar</span>'


def _score_cor(score: int) -> str:
    if score >= 150:
        return "#ff5555"
    if score >= 80:
        return "#f59e0b"
    return "#5fa3ff"


_ICON_PERSON = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="#4b5563" style="flex-shrink:0;vertical-align:middle">'
    '<path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>'
    '</svg>'
)
_ICON_PHONE = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="#6b7280" style="flex-shrink:0;vertical-align:middle">'
    '<path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z"/>'
    '</svg>'
)
_ICON_GROUP = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="#6b7280" style="flex-shrink:0;vertical-align:middle">'
    '<path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>'
    '</svg>'
)


def _tels_html(c) -> str:
    """Renderiza telefones do cliente: primeiro destacado e os demais inline
    em fonte menor — tudo selecionável e copiável (sem depender de tooltip)."""
    tels = c.get("telefones") or []
    if not tels:
        return c.get("telefone", "—") or "—"
    if len(tels) == 1:
        return tels[0]
    extras_txt = " · ".join(tels[1:])
    return (
        f'{tels[0]} '
        f'<span style="color:#6b7280;font-size:10px;font-weight:500">'
        f'· {extras_txt}</span>'
    )


def _motivo(bucket, acoes, c) -> tuple:
    """Retorna (texto, estilo) pro badge do card.
    Fonte primária: painel_tarefas_diarias. Fallback: N8N (histórico mais antigo).
    estilo ∈ 'red' | 'blue' | 'purple' | 'lig' | 'msg' | ''.

    Cliente com acordo vencido (≥7d) tem badges prefixados por "Acordo vencido há Xd"
    pra manter a info do acordo visível mesmo durante cooldown ou em outras colunas.
    """
    if c.get("_regularizado_hoje"):
        return "Regularizado hoje · pagamento confirmado", "blue"
    if c.get("_regularizado_antes_hoje"):
        # Cliente já tinha pago em dia anterior — BQ só refletiu agora.
        # Label diferente pra atendente saber que não foi hoje (sem valor).
        return "Já regularizado · pagamento anterior", "blue"

    cid = c.get("id")
    tel = c.get("telefone", "")
    acoes_hj = get_painel_acoes_hoje(cid)
    # N8N só é usado pra fallback informativo do "Última mensagem há Xd" —
    # não decide mais estado de tarefa do dia (que vem só do BQ painel).
    dsc_n8n     = get_ultimo_contato_n8n_dias(tel)
    dias_lig_atend = get_painel_dias_lig(cid)             # atendida (concluída)
    dias_lig_tent  = get_painel_dias_lig_tentada(cid)     # qualquer tentativa
    if dias_lig_atend is None:
        dias_lig_atend = get_msg_concluida_dias(tel)      # fallback N8N
    dias_msg = get_painel_dias_msg(cid)
    if dias_msg is None:
        dias_msg = dsc_n8n
    streak_lig = get_streak_cooldown_dias(cid)            # cooldown 7d (3 falhas em série)

    acordo_dias = c.get("dias_atraso") or 0
    tem_acordo  = bool(c.get("_tem_acordo")) and acordo_dias >= 7
    prefixo_ac  = f"Acordo vencido há {acordo_dias}d"

    tentou_sem_atender = (
        dias_lig_tent is not None
        and (dias_lig_atend is None or dias_lig_tent < dias_lig_atend)
    )

    # ═══ Cliente com ACORDO ═══
    # Acordo é SEMPRE ligação (regra) — mensagem é irrelevante, não aparece no badge.
    # Padrão: "Acordo vencido há Xd · {contexto} · ligação prioritária"
    # Estado "hoje" lê SÓ BQ painel (acoes_hj). N8N session_state é informativo,
    # não decide estado da tarefa do dia.
    # Só aplica branch de acordo se bucket=lig (consistente com _canal). Se cliente
    # virou acordo durante o dia mas bucket=msg, segue como msg normal — não muda
    # de coluna no meio do expediente.
    if tem_acordo and bucket == "ligacao":
        # Estado HOJE — só liga (atendeu ou tentou e não atendeu)
        if acoes_hj.get("atend"):
            return f"{prefixo_ac} · ligação realizada hoje · ligação prioritária", "blue"
        if acoes_hj.get("lig"):
            return f"{prefixo_ac} · não atendeu ligação hoje · ligação prioritária", "purple"

        # Cliente em cooldown 7d por 3 tentativas falhadas — bloqueia ligação
        if streak_lig is not None and streak_lig > 0:
            return f"{prefixo_ac} · cooldown {streak_lig}d (3 tentativas falhadas) · ligação prioritária", "red"

        # Sem ação de ligação hoje — info de cooldown/histórico de ligação
        if tentou_sem_atender:
            return f"{prefixo_ac} · não atendeu ligação há {dias_lig_tent}d · ligação prioritária", "red"
        if dias_lig_atend is not None:
            return f"{prefixo_ac} · última ligação há {dias_lig_atend}d · ligação prioritária", "red"
        return f"{prefixo_ac} · sem ligação anterior · ligação prioritária", "red"

    # ═══ Cliente sem acordo ═══
    # Bucket=mensagem: tarefa é msg → se mandou msg, tarefa cumprida (verde)
    # mesmo que tenha tentado ligar tb. Badge reflete a tarefa do bucket.
    if bucket == "mensagem" and acoes_hj.get("msg"):
        return "Mensagem enviada hoje", "blue"

    # Bucket=ligacao: tarefa é ligar → atender ou tentar é o que importa
    if acoes_hj.get("atend"):
        return "Ligação atendida hoje", "blue"
    if acoes_hj.get("lig"):
        return "Não atendeu ligação hoje", "purple"

    # Recebeu msg hoje sem ser bucket=msg (ex.: bucket=lig pegou pré-ligação):
    # tarefa pendente, fica em LIGAÇÃO (laranja, alerta)
    if acoes_hj.get("msg"):
        if bucket == "ligacao":
            return "Mensagem enviada hoje · ligação pendente", "lig"
        return "Mensagem enviada hoje", "blue"

    if "urgente" in acoes:
        return f"{prefixo_ac} · ligação prioritária", "red"

    if bucket == "ligacao":
        if streak_lig is not None and streak_lig > 0:
            return f"Cooldown {streak_lig}d (3 tentativas falhadas) · Ligação", "purple"
        if tentou_sem_atender:
            return f"Não atendeu ligação há {dias_lig_tent}d · Ligação", "purple"
        if dias_lig_atend is not None:
            return f"Última ligação há {dias_lig_atend}d · Ligação", "lig"
        return "Sem ligação anterior · Ligação", "lig"
    if bucket == "mensagem":
        if dias_msg is not None:
            return f"Última mensagem há {dias_msg}d · Mensagem", "msg"
        return "Sem mensagem anterior · Mensagem", "msg"

    # Sem bucket (gestor "Todos os clientes") — fallback por acoes
    if "ligar" in acoes:
        if tentou_sem_atender:
            return f"Não atendeu ligação há {dias_lig_tent}d · Ligação", "purple"
        return (f"Última ligação há {dias_lig_atend}d · Ligação" if dias_lig_atend is not None
                else "Sem ligação anterior · Ligação"), "lig"
    if "mensagem" in acoes:
        return (f"Última mensagem há {dias_msg}d · Mensagem" if dias_msg is not None
                else "Sem mensagem anterior · Mensagem"), "msg"
    return "", ""


def _render_card(score, acoes, c, role, idx, bucket=None, opacity=1.0):
    cor           = _score_cor(score)
    # Opacity reduzida = card visualmente secundário (ex: admin 'Todos os
    # clientes' vê tudo, mas quem não está em lote fica esmaecido).
    _op_style     = f'opacity:{opacity};' if opacity < 1.0 else ''
    _eh_acordo    = bool(c.get("_tem_acordo")) and (c.get("dias_atraso") or 0) >= 7
    # Ambos os tipos de regularizado renderizam o mesmo layout simplificado
    # (sem score, sem botão Detalhes). Distinção visual fica no motivo.
    _regularizado = bool(c.get("_regularizado_hoje")) or bool(c.get("_regularizado_antes_hoje"))
    inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;margin-left:6px;vertical-align:middle">INATIVO</span>' if c.get("_inativo") else ""
    acordo_badge  = '<span style="background:rgba(245,158,11,.2);color:#f59e0b;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-left:6px;vertical-align:middle">ACORDO VENCIDO</span>' if _eh_acordo and not _regularizado else ""
    # Badge de pagamento parcial — cliente pagou algum boleto hoje mas ainda
    # tem vencidas. Aumentado pra ficar mais evidente (era 10px, agora 13px
    # com padding maior e borda sólida). É info crítica pra atendente —
    # cliente está pagando, prioridade alta.
    _vl_parcial = float(c.get("_valor_pago_hoje") or 0)
    parcial_badge = (
        f'<span style="background:rgba(124,194,67,.22);color:#7cc243;font-size:13px;'
        f'font-weight:800;padding:4px 10px;border-radius:6px;margin-left:6px;'
        f'border:1px solid rgba(124,194,67,.4);'
        f'vertical-align:middle;letter-spacing:.3px">PAGOU {fmt_moeda_plain(_vl_parcial)} HOJE</span>'
    ) if c.get("_pago_parcial_hoje") and not _regularizado and _vl_parcial > 0 else ""
    motivo_txt, motivo_style = _motivo(bucket, acoes, c)
    _motivo_css = {
        "red":    "color:#ff5555;background:rgba(239,68,68,.08);border-left:2px solid #ff5555;padding:4px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:0.4px",
        "blue":   "color:#7cc243;background:rgba(124,194,67,.08);border-left:2px solid #7cc243;padding:4px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:0.4px",
        "purple": "color:#a78bfa;background:rgba(167,139,250,.08);border-left:2px solid #a78bfa;padding:4px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:0.4px",
        "lig":    "color:#5fa3ff;background:rgba(95,163,255,.08);border-left:2px solid #5fa3ff;padding:4px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:0.4px",
        "msg":    "color:#f59e0b;background:rgba(245,158,11,.08);border-left:2px solid #f59e0b;padding:4px 8px;border-radius:6px;text-transform:uppercase;letter-spacing:0.4px",
    }
    motivo_html = (
        f'<div style="font-size:11px;font-weight:600;margin-bottom:8px;{_motivo_css.get(motivo_style, "")}">{motivo_txt}</div>'
        if motivo_txt else ""
    )

    if _regularizado:
        # Valor pago vem do overlay real-time da API Superlógica
        # (_valor_pago_hoje = vl_total_recb do pagamento). Confiável — não
        # depende mais do BQ Splgc (que é replicado 1x/dia).
        _vl_pago = float(c.get("_valor_pago_hoje") or 0)
        valor_html = (
            f'<div style="font-size:14px;color:#7cc243;font-weight:700;margin-bottom:10px">'
            f'Pago: {fmt_moeda_plain(_vl_pago)}</div>'
        ) if _vl_pago > 0 else ""
        st.markdown(
            f'<div style="{_op_style}background:#181c26;border:1px solid #2a2f42;border-radius:12px;'
            f'padding:14px 16px;margin-bottom:10px;border-top:2px solid #7cc243">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">'
            f'<div style="font-weight:700;font-size:17px;color:#e8eaf0;line-height:1.3;flex:1;margin-right:8px">'
            f'{c["nome"]}'
            f'<div style="font-size:11px;color:#9ca3af;font-weight:400;margin-top:4px;display:flex;align-items:center;flex-wrap:wrap;gap:4px">'
            f'<span>{c.get("cnpj","—")} · ID {c.get("id","—")}</span>'
            f'{inativo_badge}'
            f'</div>'
            f'</div>'
            f'</div>'
            f'{motivo_html}'
            f'{valor_html}'
            f'<div style="font-size:12px;color:#6b7280">'
            f'<div style="display:flex;align-items:center;gap:5px;margin-bottom:4px">'
            f'{_ICON_PHONE}<span style="color:#9ca3af">{_tels_html(c)}</span>'
            f'</div>'
            f'<div style="display:flex;align-items:center;gap:5px">'
            f'{_ICON_GROUP}<span style="color:#9ca3af">{c.get("_grupo","—")}</span>'
            f'</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        return  # sem botão "Detalhes" — não há histórico editável

    st.markdown(
        f'<div style="{_op_style}background:#181c26;border:1px solid #2a2f42;border-radius:12px;'
        f'padding:14px 16px;margin-bottom:0;border-top:2px solid {cor}99;'
        f'border-bottom-left-radius:0;border-bottom-right-radius:0">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">'
        f'<div style="font-weight:700;font-size:17px;color:#e8eaf0;line-height:1.3;flex:1;margin-right:8px">'
        f'{c["nome"]}'
        f'<div style="font-size:11px;color:#9ca3af;font-weight:400;margin-top:4px;display:flex;align-items:center;flex-wrap:wrap;gap:4px">'
        f'<span>{c.get("cnpj","—")} · ID {c.get("id","—")}</span>'
        f'{inativo_badge}{acordo_badge}{parcial_badge}'
        f'</div>'
        f'</div>'
        f'<div style="text-align:right;flex-shrink:0">'
        f'<div style="font-size:20px;font-weight:800;color:{cor};line-height:1">{score}</div>'
        f'<div style="font-size:14px;color:#6b7280">pts</div>'
        f'</div></div>'
        f'{motivo_html}'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
        f'<span style="font-size:13px;font-weight:600;color:#e8eaf0">{fmt_moeda_plain(c["valor"])}</span>'
        f'{dias_html(c.get("dias_atraso"))}'
        f'</div>'
        f'<div style="font-size:12px;color:#6b7280">'
        f'<div style="display:flex;align-items:center;gap:5px;margin-bottom:4px">'
        f'{_ICON_PHONE}<span style="color:#9ca3af">{_tels_html(c)}</span>'
        f'</div>'
        f'<div style="display:flex;align-items:center;gap:5px">'
        f'{_ICON_GROUP}<span style="color:#9ca3af">{c.get("_grupo","—")}</span>'
        f'</div>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    # Botão "Detalhes" grudado no rodapé do card (visualmente integrado).
    # Streamlit não permite st.button dentro de markdown HTML, então usa
    # st.button externo + CSS (no _render_atividades) que reduz o tamanho.
    if role != "gestor":
        if st.button("Detalhes ›", key=f"atv_{c['id']}_{idx}", width="stretch"):
            dialog_editar(c["id"])


def _render_atividades(store, clientes, role):
    # Detecta virada do dia operacional (08:15 BRT) — força rerun pra renovar lote
    if _detectar_virada_dia():
        return

    # CSS: faz o botão "Detalhes" parecer continuação do card.
    # - Mesma cor de fundo e borda
    # - Cantos superiores zerados, inferiores arredondados (encaixa no card)
    # - Sem borda superior (visualmente une com o card que tem bottom-radius:0)
    # - Fonte menor e discreta
    st.markdown("""
    <style>
    .stButton > button[kind="secondary"] {
        background-color: #181c26;
        border: 1px solid #2a2f42;
        border-top: none;
        border-top-left-radius: 0;
        border-top-right-radius: 0;
        border-bottom-left-radius: 12px;
        border-bottom-right-radius: 12px;
        color: #9ca3af;
        font-size: 12px;
        font-weight: 500;
        padding-top: 8px;
        padding-bottom: 8px;
        margin-top: 0;
        margin-bottom: 10px;
        transition: background-color 0.15s, color 0.15s;
    }
    .stButton > button[kind="secondary"]:hover {
        background-color: #1f2433;
        color: #e8eaf0;
        border-color: #3a3f55;
        border-top: none;
    }
    </style>
    """, unsafe_allow_html=True)

    hoje_str = date.today().strftime("%d/%m/%Y")
    nome  = current_nome()  or "usuário"
    email = current_email() or ""

    # ── Gera / carrega lote de 80 tarefas do dia ──────────────────────────────
    # session_state guarda {id: bucket} pra rotear cada cliente direto na coluna
    # certa (mensagem/ligacao) sem recalcular acoes. Gestor/admin só geram lote
    # quando entram no modo "Lote do dia" (lá embaixo).
    buckets_hoje = {}
    if email in _EMAIL_GRUPO:
        _key_tarefas = f"_tarefas_{hoje_lote()}_{email}"
        if _key_tarefas not in st.session_state:
            with st.spinner("Preparando tarefas do dia..."):
                st.session_state[_key_tarefas] = gerar_tarefas_do_dia(clientes, email)
        buckets_hoje = st.session_state[_key_tarefas] or {}
    ids_hoje = set(buckets_hoje.keys())

    # Lote estático do dia: 80 IDs fixos. Tarefas concluídas vão pra coluna
    # CONCLUÍDA e ficam visíveis. Renovação só na virada do dia.
    if email in _EMAIL_GRUPO:
        clientes = [c for c in clientes if c["id"] in ids_hoje]
        # IDs do lote que pagaram os atrasos durante o dia — saem da lista normal
        # mas voltam aqui como REGULARIZADO pra atendente não perder a meta.
        ids_regularizados = ids_hoje - {c["id"] for c in clientes}
        if ids_regularizados:
            clientes.extend(fetch_regularizados_do_dia(ids_regularizados))

    # ── Painel administrativo (alinhado à direita) ──────────────────────────
    _nomes_atendentes = list(_EMAIL_GRUPO.values())
    _modo_admin       = "Todos os clientes"
    _atendente_sel    = None
    if role in ("admin", "gestor"):
        _admin_spacer, _admin_box = st.columns([2.6, 2.4])
        with _admin_box:
            with st.container(border=True):
                st.markdown(
                    '<div style="display:flex;align-items:center;gap:6px;'
                    'font-size:11px;font-weight:700;color:#9ca3af;text-transform:uppercase;'
                    'letter-spacing:0.7px;margin-bottom:8px">'
                    '<svg width="13" height="13" viewBox="0 0 24 24" fill="#9ca3af">'
                    '<path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/>'
                    '</svg>'
                    'Painel Administrativo</div>',
                    unsafe_allow_html=True,
                )
                _cm, _ca = st.columns([1, 1])
                with _cm:
                    _modo_admin = st.selectbox(
                        "Visualização",
                        ["Todos os clientes", "Lote do dia"],
                        label_visibility="collapsed",
                        key="_admin_modo",
                    )
                with _ca:
                    if _modo_admin == "Lote do dia":
                        _atendente_sel = st.selectbox(
                            "Especialista",
                            _nomes_atendentes,
                            label_visibility="collapsed",
                            key="_admin_atendente",
                        )

        if _modo_admin == "Lote do dia" and _atendente_sel:
            _key_lote = f"_tarefas_admin_{hoje_lote()}_{_atendente_sel}"
            if _key_lote not in st.session_state:
                with st.spinner(f"Carregando lote de {_atendente_sel}..."):
                    buckets_bq = get_lote_buckets_bq(_atendente_sel, store["clientes"])
                    if not buckets_bq:
                        _GRUPO_EMAIL = {v: k for k, v in _EMAIL_GRUPO.items()}
                        _email_atend = _GRUPO_EMAIL.get(_atendente_sel, "")
                        buckets_bq = gerar_tarefas_do_dia(clientes, _email_atend)
                    st.session_state[_key_lote] = buckets_bq
            buckets_lote = st.session_state[_key_lote] or {}
            ids_lote = set(buckets_lote.keys())

            # Lote estático do dia: mostra os 80 IDs fixos do atendente selecionado
            clientes = [c for c in clientes if c["id"] in ids_lote]
            # Inclui regularizados (pagaram durante o dia) pra completar 80 visíveis
            ids_regularizados_adm = ids_lote - {c["id"] for c in clientes}
            if ids_regularizados_adm:
                clientes.extend(fetch_regularizados_do_dia(ids_regularizados_adm))
            # Quando admin visualiza lote de outro atendente, usa o bucket dele
            buckets_hoje = buckets_lote

    st.markdown(
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:52px;'
        f'font-weight:800;color:#e8eaf0;margin-top:32px;margin-bottom:32px;letter-spacing:-1.5px;line-height:1.1">'
        f'Bem-vindo(a), {nome}!</div>',
        unsafe_allow_html=True,
    )

    # ── Indicadores 'Hoje' — fragment próprio, auto-refresh 60s ───────────────
    # Layout horizontal: 'No Lote' (quando aplicável) e 'No Total' (admin/gestor).
    # Atendente: vê só 'No Lote' (sua carteira do dia).
    # Admin 'Todos os clientes': vê só 'No Total'.
    # Admin 'Lote do dia' de X: vê 'No Lote de X' + 'No Total'.
    @st.fragment(run_every=60)
    def _indicadores_hoje():
        clientes_full = store.get("clientes", []) or []
        # Helper: conta + soma valor — REGULARIZAÇÕES e PARCIAIS são
        # mutuamente EXCLUSIVAS (regularizou não conta em parcial e vice-versa).
        # Clareza visual: 'Reg=3, Parc=1' soma 4 sem sobreposição.
        def _agg(cs):
            reg_n, reg_v, parc_n, parc_v = 0, 0.0, 0, 0.0
            for c in cs:
                vlr = float(c.get("_valor_pago_hoje") or 0)
                if c.get("_regularizado_hoje"):
                    reg_n += 1
                    reg_v += vlr
                elif vlr > 0:
                    # Pagou algo mas NÃO zerou tudo → parcial
                    parc_n += 1
                    parc_v += vlr
            return reg_n, reg_v, parc_n, parc_v

        # Decide quais seções renderizar baseado no contexto:
        #   Atendente:                          mostra só 'No Lote'
        #   Admin/Gestor em 'Lote do dia':      mostra só 'No Lote' (o atendente
        #                                       selecionado já contextualiza)
        #   Admin/Gestor em 'Todos os clientes': mostra só 'No Total'
        _mostrar_lote = (email in _EMAIL_GRUPO) or (
            role in ("admin", "gestor") and _modo_admin == "Lote do dia" and _atendente_sel
        )
        _mostrar_total = (
            role in ("admin", "gestor") and _modo_admin == "Todos os clientes"
        )

        # Dados do LOTE
        if _mostrar_lote:
            if email in _EMAIL_GRUPO:
                _ids_lote = ids_hoje
            else:
                _key = f"_tarefas_admin_{hoje_lote()}_{_atendente_sel}"
                _buckets = st.session_state.get(_key, {}) or {}
                _ids_lote = set(_buckets.keys())
            _lote_cs = [c for c in clientes_full if c.get("id") in _ids_lote]
            lote_reg_n, lote_reg_v, lote_parc_n, lote_parc_v = _agg(_lote_cs)
        # Dados do TOTAL — respeita filtros Grupo (incluindo 'Sem especialista')
        # e Situação. Sublabel removido por feedback — visual mais limpo.
        total_reg_n = total_reg_v = total_parc_n = total_parc_v = 0
        total_label = ""  # sublabel removido por feedback
        if _mostrar_total:
            _fg = st.session_state.get("atv_filtro_grupo", "Todos")
            _fs = st.session_state.get("atv_filtro_inativo", "Todos")
            _total_cs = clientes_full
            # Filtro de Grupo
            if _fg == "Sem especialista":
                _total_cs = [
                    c for c in _total_cs
                    if not c.get("_grupo") or str(c.get("_grupo")) in ("—", "", "nan", "NaN")
                ]
            elif _atendente_sel:
                _total_cs = [c for c in _total_cs if c.get("_grupo") == _atendente_sel]
            elif _fg not in ("Todos", "", None):
                _total_cs = [c for c in _total_cs if c.get("_grupo") == _fg]
            # Filtro de Situação
            if _fs == "Ativos":
                _total_cs = [c for c in _total_cs if not c.get("_inativo")]
            elif _fs == "Inativos":
                _total_cs = [c for c in _total_cs if c.get("_inativo")]
            total_reg_n, total_reg_v, total_parc_n, total_parc_v = _agg(_total_cs)

        def _palavra(n, sing, plur):
            return sing if n == 1 else plur

        # SVG icons inline (✓ verde, ⬡ azul)
        _ico_reg = (
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#7cc243" '
            'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" '
            'style="flex-shrink:0"><polyline points="20 6 9 17 4 12"></polyline></svg>'
        )
        _ico_pag = (
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#5fa3ff" '
            'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" '
            'style="flex-shrink:0"><circle cx="12" cy="12" r="9"></circle>'
            '<path d="M12 6v6l4 2"></path></svg>'
        )

        # Card vertical — 2 linhas com divisor:
        # ✓ Regularizações (verde) → ⏱ Parciais (azul)
        def _card_html(label_topo, sublabel, reg_n, reg_v, parc_n, parc_v):
            _reg_palavra = _palavra(reg_n, "regularização", "regularizações").upper()
            _parc_palavra = _palavra(parc_n, "parcial", "parciais").upper()
            _reg_v_fmt = fmt_moeda_plain(reg_v)
            _parc_v_fmt = fmt_moeda_plain(parc_v)

            def _linha(ico, count, palavra, valor_fmt, cor_valor):
                return (
                    f'<div style="display:flex;align-items:center;gap:8px">'
                    f'{ico}'
                    f'<span style="font-size:26px;font-weight:800;color:#e8eaf0;line-height:1;'
                    f'font-variant-numeric:tabular-nums">{count}</span>'
                    f'<span style="font-size:13px;color:#9ca3af;font-weight:700;'
                    f'letter-spacing:1.2px;text-transform:uppercase">{palavra}</span>'
                    f'<span style="margin-left:auto;font-size:20px;font-weight:800;color:{cor_valor};'
                    f'font-variant-numeric:tabular-nums">{valor_fmt}</span>'
                    f'</div>'
                )

            _divisor = '<div style="height:1px;background:#2a2f42;margin:10px -18px"></div>'

            return (
                f'<div style="flex:1;background:#181c26;border:1px solid #2a2f42;'
                f'border-radius:10px;padding:14px 18px">'
                f'{_linha(_ico_reg, reg_n, _reg_palavra, _reg_v_fmt, "#7cc243")}'
                f'{_divisor}'
                f'{_linha(_ico_pag, parc_n, _parc_palavra, _parc_v_fmt, "#5fa3ff")}'
                f'</div>'
            )

        # Monta linha horizontal
        cards_html = []
        if _mostrar_lote:
            # Sublabel vazio — filtro Painel Administrativo (admin/gestor) ou
            # contexto natural (atendente vê só o próprio) já contextualizam.
            cards_html.append(_card_html(
                "No Lote", "",
                lote_reg_n, lote_reg_v, lote_parc_n, lote_parc_v,
            ))
        if _mostrar_total:
            cards_html.append(_card_html(
                "No Total", total_label,
                total_reg_n, total_reg_v, total_parc_n, total_parc_v,
            ))

        if cards_html:
            # Card na MESMA largura do filtro 'Grupo' abaixo.
            _col_widths = [1.3, 1.3, 2]
            ind_cols = st.columns(_col_widths)
            for i, html in enumerate(cards_html[:2]):
                with ind_cols[i]:
                    st.markdown(html, unsafe_allow_html=True)
            st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    # Indicadores 'Hoje' — ACIMA dos filtros (linha horizontal de destaque)
    _indicadores_hoje()

    # ── Filtros (fora do fragment — Streamlit preserva valor por session_state)
    # 'nan' (string) cai aqui quando _grupo veio de pandas com NaN convertido
    # via str() em algum ponto do pipeline. Trata junto com None, '—' e ''
    # como ausência de grupo (mesmo fix da tela Inadimplência).
    grupos_disp = sorted({
        c.get("_grupo", "—") for c in clientes
        if c.get("_grupo") and c.get("_grupo") not in ("—", "", "nan", "NaN")
    })
    _tem_sem_grupo = any(
        not c.get("_grupo") or c.get("_grupo") in ("—", "", "nan", "NaN")
        for c in clientes
    )
    fa, fb, fc = st.columns([1.3, 1.3, 2])
    with fa:
        st.selectbox(
            "Grupo",
            ["Todos"] + grupos_disp + (["Sem especialista"] if _tem_sem_grupo else []),
            key="atv_filtro_grupo",
        )
    with fb:
        st.selectbox("Situação", ["Todos", "Ativos", "Inativos"], key="atv_filtro_inativo")
    with fc:
        st.text_input("Buscar", placeholder="Nome, CNPJ ou ID...", key="atv_busca")

    # ── Conteúdo dinâmico (métricas + kanban) — fragment com run_every=60s
    # Atualiza a cada 60s sem fazer rerun do app inteiro: filtros (acima) ficam
    # com seu valor preservado, sem reset.
    @st.fragment(run_every=60)
    def _kanban_dinamico():
        # Atualiza dados periódicos (gates internos)
        _atualizar_dados_periodicos(store["clientes"])

        # Lê filtros do session_state (preserva valor entre runs do fragment)
        filtro_grupo   = st.session_state.get("atv_filtro_grupo", "Todos")
        filtro_inativo = st.session_state.get("atv_filtro_inativo", "Todos")
        busca          = st.session_state.get("atv_busca", "") or ""

        # ── Métricas dos cards do topo (contagem direta de painel_tarefas_diarias) ─
        # Conta TODOS os clientes do lote com bool=TRUE no painel — sem filtro de
        # bucket. Cliente que recebeu pré-ligação (lig=T) conta em "Realizadas",
        # cliente atendido (atend=T) conta em "Atendidas", cliente com msg conta
        # em "Mensagens" — independente do bucket onde foi colocado de manhã.
        
        
        
        
        def _metricas_lote_painel(ids_lote=None, buckets_map=None):
            acoes = st.session_state.get("_painel_acoes_hoje", {})
            buckets_norm = None
            if buckets_map is not None:
                # BQ pode devolver id_sacado_sac como int; painel usa chave string.
                buckets_norm = {str(cid): bucket for cid, bucket in buckets_map.items()}
            if ids_lote is None:
                items = [(cid, a) for cid, a in acoes.items()]
            else:
                items = [(str(cid), acoes.get(str(cid), {})) for cid in ids_lote]
            if buckets_norm is not None:
                msg = sum(1 for cid, a in items if a.get("msg") and buckets_norm.get(cid) == "mensagem")
                lig = sum(1 for cid, a in items if a.get("lig") and buckets_norm.get(cid) in ("ligacao",))
                atd = sum(1 for cid, a in items if a.get("atend") and buckets_norm.get(cid) in ("ligacao",))
            else:
                msg = sum(1 for _, a in items if a.get("msg"))
                lig = sum(1 for _, a in items if a.get("lig"))
                atd = sum(1 for _, a in items if a.get("atend"))
            return {"mensagens": msg, "ligacoes": lig, "atendidas": atd}

        # Em 'Todos os clientes' (admin/gestor), os cards M/L/A respeitam
        # os filtros Grupo e Situação. Permite admin focar nos números de
        # um grupo específico sem ter que entrar no modo 'Lote do dia'.
        # Atendente e admin 'Lote do dia' continuam com escopo do lote.
        atendente_logado = _EMAIL_GRUPO.get(email)
        if atendente_logado:
            dados_m, label_m = _metricas_lote_painel(ids_hoje, buckets_hoje), atendente_logado
        elif role in ("admin", "gestor") and _modo_admin == "Lote do dia" and _atendente_sel:
            _key_lote_adm = f"_tarefas_admin_{hoje_lote()}_{_atendente_sel}"
            _buckets_adm  = st.session_state.get(_key_lote_adm, {}) or {}
            _ids_lote_adm = set(_buckets_adm.keys())
            dados_m, label_m = _metricas_lote_painel(_ids_lote_adm, _buckets_adm), _atendente_sel
        else:
            # Admin/Gestor em 'Todos os clientes' — aplica filtros Grupo/Situação
            # pra restringir o universo de clientes contabilizados nas métricas.
            _filtrados = store.get("clientes", []) or []
            if filtro_grupo == "Sem especialista":
                _filtrados = [
                    c for c in _filtrados
                    if not c.get("_grupo") or str(c.get("_grupo")) in ("—", "", "nan", "NaN")
                ]
            elif filtro_grupo != "Todos":
                _filtrados = [c for c in _filtrados if c.get("_grupo") == filtro_grupo]
            if filtro_inativo == "Ativos":
                _filtrados = [c for c in _filtrados if not c.get("_inativo")]
            elif filtro_inativo == "Inativos":
                _filtrados = [c for c in _filtrados if c.get("_inativo")]
            _ids_filtrados = {str(c.get("id") or "") for c in _filtrados}
            # Se há filtro ativo, passa ids específicos; senão, None = todos
            _eh_filtrado = (
                filtro_grupo != "Todos" or filtro_inativo != "Todos"
            )
            dados_m, label_m = (
                _metricas_lote_painel(_ids_filtrados if _eh_filtrado else None),
                "Total" if not _eh_filtrado else "Filtrado",
            )

        meta_msg, meta_lig, meta_atend = 50, 30, 15
        n_msg, n_lig, n_atend = dados_m.get("mensagens", 0), dados_m.get("ligacoes", 0), dados_m.get("atendidas", 0)

        # Nome do especialista removido daqui por feedback — não agrega valor,
        # o nome já aparece no header e nos cards de Indicadores acima.
        # Labels com fonte maior (font-size:15px override da classe .metric-label)
        _label_style = "font-size:15px;letter-spacing:1.4px"
        m1, m2, m3 = st.columns(3)
        with m1:
            pct = min(int(n_msg / meta_msg * 100), 100)
            st.markdown(
                f'<div class="metric-card"><div class="metric-label" style="{_label_style}">Mensagens Enviadas</div>'
                f'<div class="metric-value" style="color:#5fa3ff;font-size:32px">{n_msg}<span style="font-size:18px;color:#6b7280">/{meta_msg}</span></div>'
                f'<div style="background:#1e2333;border-radius:4px;height:6px;margin-top:10px">'
                f'<div style="background:#5fa3ff;width:{pct}%;height:6px;border-radius:4px"></div></div></div>',
                unsafe_allow_html=True,
            )
        with m2:
            pct = min(int(n_lig / meta_lig * 100), 100)
            st.markdown(
                f'<div class="metric-card"><div class="metric-label" style="{_label_style}">Ligações Realizadas</div>'
                f'<div class="metric-value" style="color:#f59e0b;font-size:32px">{n_lig}<span style="font-size:18px;color:#6b7280">/{meta_lig}</span></div>'
                f'<div style="background:#1e2333;border-radius:4px;height:6px;margin-top:10px">'
                f'<div style="background:#f59e0b;width:{pct}%;height:6px;border-radius:4px"></div></div></div>',
                unsafe_allow_html=True,
            )
        with m3:
            pct = min(int(n_atend / meta_atend * 100), 100)
            st.markdown(
                f'<div class="metric-card"><div class="metric-label" style="{_label_style}">Ligações Atendidas</div>'
                f'<div class="metric-value" style="color:#7cc243;font-size:32px">{n_atend}<span style="font-size:18px;color:#6b7280">/{meta_atend}</span></div>'
                f'<div style="background:#1e2333;border-radius:4px;height:6px;margin-top:10px">'
                f'<div style="background:#7cc243;width:{pct}%;height:6px;border-radius:4px"></div></div></div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

        # ── Monta fila ────────────────────────────────────────────────────────
        fila = []
        for c in clientes:
            h = get_hist(c["id"])
            fila.append((calcular_score(c, h), recomendar_acao(c), c, h))
        fila.sort(key=lambda x: x[0], reverse=True)

        # ── Aplica filtros (lê do session_state, preserva entre runs) ─────────
        if filtro_grupo == "Sem especialista":
            # Cliente sem grupo: None, '', '—' ou 'nan' (string)
            fila = [
                (s, a, c, h) for s, a, c, h in fila
                if not c.get("_grupo") or str(c.get("_grupo")) in ("—", "", "nan", "NaN")
            ]
        elif filtro_grupo != "Todos":
            fila = [(s, a, c, h) for s, a, c, h in fila if c.get("_grupo") == filtro_grupo]
        if filtro_inativo == "Ativos":
            fila = [(s, a, c, h) for s, a, c, h in fila if not c.get("_inativo")]
        elif filtro_inativo == "Inativos":
            fila = [(s, a, c, h) for s, a, c, h in fila if c.get("_inativo")]
        if busca:
            import re as _re_b
            b = busca.strip().lower()
            b_digits = _re_b.sub(r'\D', '', b)

            def _match(c):
                nome  = str(c.get("nome") or "").lower()
                cnpj  = str(c.get("cnpj") or "")
                cnpj_digits = _re_b.sub(r'\D', '', cnpj)
                cid   = str(c.get("id") or "")
                if b in nome:
                    return True
                if b in cnpj.lower():
                    return True
                if b_digits and b_digits in cnpj_digits:
                    return True
                if b_digits and b_digits == cid:
                    return True
                return False

            fila = [(s, a, c, h) for s, a, c, h in fila if _match(c)]

        # ── Separar por coluna ────────────────────────────────────────────────
        def _canal(bucket, acoes, acoes_hj, regularizado=False, eh_acordo=False):
            # Estado "hoje" lê SÓ BQ painel (acoes_hj). N8N não é mais usado pra
            # decidir coluna — só pra badge informativo de "última mensagem há Xd"
            # no _motivo.
            if regularizado:
                return "concluida"
            # Bucket é congelado no nascimento do lote (08:30). Acordo é
            # re-avaliado em tempo real — se cliente vira acordo durante o
            # dia, NÃO pode mudar de coluna (confundiria a atendente).
            # Só respeita acordo (URGENTE) se o bucket original já era lig.
            if eh_acordo and bucket == "ligacao":
                if acoes_hj.get("atend"):
                    return "concluida"
                if acoes_hj.get("lig"):
                    return "tentar_novamente"
                return "urgente"
            if bucket != "mensagem":
                if acoes_hj.get("atend"):
                    return "concluida"
                if acoes_hj.get("lig"):
                    return "tentar_novamente"
            if bucket == "ligacao":
                return "ligacao"
            if bucket != "ligacao":
                if acoes_hj.get("msg"):
                    return "concluida"
            if "urgente" in acoes:
                return "urgente"
            if bucket == "mensagem":
                return "mensagem"
            if "ligar" in acoes:
                return "ligacao"
            if "mensagem" in acoes:
                return "mensagem"
            return "aguardar"

        _e_lote = email in _EMAIL_GRUPO or (role in ("admin", "gestor") and _modo_admin == "Lote do dia")

        # Admin em 'Todos os clientes': IDs em qualquer lote do dia, pra
        # aplicar opacidade nos cards FORA do lote (sinaliza que não estão
        # sendo trabalhados por ninguém hoje).
        _modo_todos_admin = role in ("admin", "gestor") and _modo_admin == "Todos os clientes"
        ids_em_lote_hoje = fetch_ids_em_qualquer_lote_hoje() if _modo_todos_admin else set()

        acordos = []; ligacao = []; so_msg = []; tentar_nov = []; concluida = []; aguardar = []
        for item in fila:
            s, a, c, h = item
            bucket = buckets_hoje.get(c["id"]) if isinstance(buckets_hoje, dict) else None
            acoes_hj = get_painel_acoes_hoje(c["id"])
            eh_acordo = bool(c.get("_tem_acordo")) and (c.get("dias_atraso") or 0) >= 7
            canal = _canal(bucket, a, acoes_hj,
                           regularizado=bool(c.get("_regularizado_hoje")) or bool(c.get("_regularizado_antes_hoje")),
                           eh_acordo=eh_acordo)
            if _e_lote and canal == "aguardar":
                continue
            if   canal == "urgente":          acordos.append(item)
            elif canal == "ligacao":          ligacao.append(item)
            elif canal == "mensagem":         so_msg.append(item)
            elif canal == "tentar_novamente": tentar_nov.append(item)
            elif canal == "concluida":        concluida.append(item)
            else:                             aguardar.append(item)

        # Sort dentro de CADA coluna: quem pagou hoje (parcial ou total) sobe
        # pro topo, independente do score. Prioridade:
        #   1) regularizou TUDO hoje (_regularizado_hoje)
        #   2) pagou ALGO hoje (_valor_pago_hoje > 0)
        #   3) score normal (descendente)
        def _prio(item):
            _, _, c, _ = item
            reg_hoje = bool(c.get("_regularizado_hoje"))
            pagou_alg = float(c.get("_valor_pago_hoje") or 0) > 0
            # Maior valor = topo (depois reverse=True implícito no sorted negativo)
            return (
                2 if reg_hoje else (1 if pagou_alg else 0),
                item[0],  # score original
            )
        for col_list in (acordos, ligacao, so_msg, tentar_nov, concluida, aguardar):
            col_list.sort(key=_prio, reverse=True)

        def _svg(path, color, size=13, ml=0, mr=6):
            return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="{color}" '
                    f'style="flex-shrink:0;margin-left:{ml}px;margin-right:{mr}px">'
                    f'<path d="{path}"/></svg>')

        _fire  = _svg("M13.5.67s.74 2.65.74 4.8c0 2.06-1.35 3.73-3.41 3.73-2.07 0-3.63-1.67-3.63-3.73l.03-.36C5.21 7.51 4 10.62 4 14c0 4.42 3.58 8 8 8s8-3.58 8-8C20 8.61 17.41 3.8 13.5.67z", "#7cc243", 17)
        _phone = _svg("M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z", "#f59e0b", 16)
        _env   = _svg("M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z", "#e8eaf0", 15)
        _retry = _svg("M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z", "#a78bfa", 16)
        _check = _svg("M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z", "#7cc243", 16)

        colunas = [
            (f'{_fire}URGENTE',           acordos,    "#ff5555"),
            (f'{_env}MENSAGEM',           so_msg,     "#5fa3ff"),
            (f'{_phone}LIGAÇÃO',          ligacao,    "#f59e0b"),
            (f'{_retry}TENTAR NOVAMENTE', tentar_nov, "#a78bfa"),
            (f'{_check}CONCLUÍDA',        concluida,  "#7cc243"),
        ]

        cols = st.columns(len(colunas))
        for col, (titulo, itens, cor) in zip(cols, colunas):
            with col:
                st.markdown(
                    f'<div style="background:#1e2333;border-radius:10px 10px 0 0;padding:10px 12px;'
                    f'margin-bottom:8px;display:flex;justify-content:space-between;align-items:center">'
                    f'<span style="display:inline-flex;align-items:center;font-size:13px;font-weight:800;color:#e8eaf0;letter-spacing:0.3px">{titulo}</span>'
                    f'<span style="background:#2a2f42;color:#e8eaf0;font-size:14px;font-weight:800;'
                    f'padding:2px 8px;border-radius:10px">{len(itens)}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if not itens:
                    st.markdown(
                        '<div style="background:#181c26;border:1px solid #2a2f42;border-radius:10px;'
                        'padding:20px;text-align:center;color:#4b5563;font-size:11px">Nenhum cliente</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    for idx, (score, acoes, c, h) in enumerate(itens):
                        bk = buckets_hoje.get(c["id"]) if isinstance(buckets_hoje, dict) else None
                        # Admin em 'Todos os clientes': cards FORA de qualquer
                        # lote ficam com opacidade reduzida (visualmente
                        # secundários — não estão sendo trabalhados hoje).
                        # NOTA: wrapping com st.markdown('<div>') NÃO funciona
                        # porque Streamlit renderiza cada bloco como SIBLING
                        # no DOM, não nested. Precisa aplicar opacity direto
                        # no estilo do card (via param do _render_card).
                        fora_do_lote = (
                            _modo_todos_admin
                            and str(c.get("id", "")) not in ids_em_lote_hoje
                        )
                        with st.container():
                            _render_card(
                                score, acoes, c, role, f"{titulo}_{idx}",
                                bucket=bk,
                                opacity=0.45 if fora_do_lote else 1.0,
                            )

    _kanban_dinamico()

