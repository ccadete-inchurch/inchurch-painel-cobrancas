from datetime import date

import streamlit as st

import time as _time

from helpers import get_hist, fmt_moeda_plain, dias_html, get_painel_dias_lig, get_painel_dias_lig_tentada, get_painel_dias_msg, get_painel_acoes_hoje, hoje_lote, get_streak_cooldown_dias
from data import calcular_score, recomendar_acao, load_mensagens_from_bq, load_cooldowns_from_painel, gerar_tarefas_do_dia, atualizar_tarefas_bq, get_lote_buckets_bq, fetch_regularizados_do_dia, fetch_ids_em_qualquer_lote_hoje, fetch_npl_metrics, _EMAIL_GRUPO
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
    acoes_hj = get_painel_acoes_hoje(cid)
    # Painel é a única fonte. Sem fallback N8N — atividade fora do painel é
    # invisível pro sistema (cooldown, badge, métricas). Atendente que conversa
    # por WhatsApp fora do lote vai ver "Sem msg anterior" mesmo tendo conversado
    # ontem. Pressão construtiva pra usar o painel ou implementar sync N8N→painel
    # pra capturar atividade fora-de-lote.
    dias_lig_atend = get_painel_dias_lig(cid)             # atendida (concluída)
    dias_lig_tent  = get_painel_dias_lig_tentada(cid)     # qualquer tentativa
    dias_msg = get_painel_dias_msg(cid)
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
        # Atendeu hoje vence tudo — info mais positiva, atendente já fechou
        if acoes_hj.get("atend"):
            return f"{prefixo_ac} · ligação realizada hoje · ligação prioritária", "blue"

        # Cooldown 7d (3 falhas) tem prioridade sobre "tentou hoje" — é a
        # info mais útil pra atendente (ela precisa SABER que esse cliente
        # já está bloqueado). Senão, ao tentar hoje, o badge perdia o
        # contexto do cooldown e virava só "não atendeu ligação hoje".
        if streak_lig is not None and streak_lig > 0:
            return f"{prefixo_ac} · não atendeu as últimas 3 ligações · ligação prioritária", "purple"

        if acoes_hj.get("lig"):
            return f"{prefixo_ac} · não atendeu ligação hoje · ligação prioritária", "purple"

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

    # Cooldown 7d (3 falhas) prevalece sobre "tentou hoje" — atendente
    # precisa saber que o cliente já está bloqueado, mesmo se ela
    # insistiu hoje. Mesma lógica do acordo (acima).
    if bucket == "ligacao" and streak_lig is not None and streak_lig > 0:
        return "Não atendeu as últimas 3 ligações · Ligação", "purple"

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
            return "Não atendeu as últimas 3 ligações · Ligação", "purple"
        if tentou_sem_atender:
            return f"Não atendeu ligação há {dias_lig_tent}d · Ligação", "purple"
        if dias_lig_atend is not None:
            return f"Última ligação há {dias_lig_atend}d · Ligação", "lig"
        return "Sem ligação anterior · Ligação", "lig"
    if bucket == "mensagem":
        if dias_msg is not None:
            return f"Última mensagem há {dias_msg}d · Mensagem", "msg"
        return "Sem mensagem anterior · Mensagem", "msg"

    # Sem bucket (admin "Todos os clientes") — fallback por acoes
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
    # Badge de pagamento parcial — aparece sempre que overlay marcou
    # _pago_parcial_hoje, mostra "HOJE" (perspectiva do sistema: o sistema
    # detectou hoje, mesmo que liquidação real tenha sido ontem). Coerente
    # com o badge "Regularizado hoje" que segue mesma lógica.
    _eh_parcial = bool(c.get("_pago_parcial_hoje")) and not _regularizado and _vl_parcial > 0
    parcial_badge = (
        f'<span style="background:rgba(124,194,67,.18);color:#7cc243;font-size:10px;'
        f'font-weight:700;padding:2px 7px;border-radius:4px;margin-left:6px;'
        f'border:1px solid rgba(124,194,67,.35);'
        f'vertical-align:middle">PAGOU {fmt_moeda_plain(_vl_parcial)} HOJE</span>'
    ) if _eh_parcial else ""
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
    if role == "admin":
        _admin_spacer, _admin_box = st.columns([5, 1.3])
        with _admin_box:
            st.markdown(
                '<div style="font-size:10px;font-weight:700;color:#6b7280;'
                'text-transform:uppercase;letter-spacing:1.4px;margin-bottom:4px;'
                'text-align:right">Painel admin</div>',
                unsafe_allow_html=True,
            )
            _modo_admin = st.selectbox(
                "Visualização",
                ["Todos os clientes", "Lote do dia"],
                label_visibility="collapsed",
                key="_admin_modo",
            )
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

    # ── Cards NPL: TOTAL, 30D+, 90D+ (acima do "Bem-vindo") ─────────────────
    # Combina 3 fontes de filtro em ordem de precedência:
    #   1. Painel Administrativo (admin "Lote do dia" de X): trava em X
    #   2. Filtro "Grupo" abaixo do "Bem-vindo": admin pode escolher Ana,
    #      Priscila ou Sem especialista
    #   3. Filtro "Situação": Todos / Ativos / Inativos
    # Atendente comum logada sempre vê sua própria carteira.
    _filtro_grupo   = st.session_state.get("atv_filtro_grupo", "Todos")
    _filtro_inativo = st.session_state.get("atv_filtro_inativo", "Todos")

    if role == "admin" and _modo_admin == "Lote do dia" and _atendente_sel:
        _npl_atendente = _atendente_sel
        _npl_escopo = f"Carteira de {_atendente_sel}"
    elif role == "admin" and _filtro_grupo == "Sem especialista":
        _npl_atendente = "__SEM_ESPECIALISTA__"
        _npl_escopo = "Sem especialista"
    elif role == "admin" and _filtro_grupo in _EMAIL_GRUPO.values():
        _npl_atendente = _filtro_grupo
        _npl_escopo = f"Carteira de {_filtro_grupo}"
    elif email in _EMAIL_GRUPO:
        _npl_atendente = _EMAIL_GRUPO[email]
        _npl_escopo = f"Sua carteira ({_npl_atendente})"
    else:
        _npl_atendente = None
        _npl_escopo = "Carteira inChurch"

    _sit_map = {"Ativos": "ativos", "Inativos": "inativos"}
    _npl_situacao = _sit_map.get(_filtro_inativo, "todos")
    if _npl_situacao != "todos":
        _npl_escopo += f" · {_filtro_inativo.lower()}"

    _npl = fetch_npl_metrics(_npl_atendente, _npl_situacao) or {}
    if _npl:
        def _delta_html(v: float) -> str:
            if abs(v) < 0.05:
                return '<span style="color:#9ca3af;font-size:14px">— 0,0 p.p.</span>'
            arrow, color = ("▼", "#22c55e") if v < 0 else ("▲", "#f59e0b")
            val = f"{abs(v):.1f}".replace(".", ",")
            return (
                f'<span style="color:{color};font-size:14px;font-weight:600">'
                f'{arrow} {val} p.p. vs 7d</span>'
            )

        def _fmt_rs(v: float) -> str:
            s = f"{v:,.2f}"
            return s.replace(",", "X").replace(".", ",").replace("X", ".")

        def _card(label: str, pct: float, delta: float, rs: float) -> str:
            pct_str = f"{pct:.1f}".replace(".", ",")
            return (
                '<div style="flex:1;background:rgba(124,194,67,0.04);'
                'border:1px solid rgba(124,194,67,0.15);border-radius:12px;'
                'padding:22px 24px;min-width:0">'
                f'<div style="font-size:12px;font-weight:700;color:#9ca3af;'
                f'text-transform:uppercase;letter-spacing:1.6px;margin-bottom:12px">'
                f'{label}</div>'
                f'<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:8px">'
                f'<span style="font-size:38px;font-weight:800;color:#e8eaf0;'
                f'letter-spacing:-1.2px;line-height:1">{pct_str}%</span>'
                f'{_delta_html(delta)}'
                f'</div>'
                f'<div style="font-size:14px;color:#6b7280">'
                f'R$ {_fmt_rs(rs)} em aberto</div>'
                '</div>'
            )

        _html = (
            '<div style="margin-top:20px;margin-bottom:4px">'
            f'<div style="font-size:12px;font-weight:700;color:#6b7280;'
            f'text-transform:uppercase;letter-spacing:1.6px;margin-bottom:10px">'
            f'{_npl_escopo} · {_npl["carteira"]} clientes</div>'
            '<div style="display:flex;gap:14px">'
            + _card("Inadimplência total", _npl["total_pct"], _npl["delta_total"], _npl["total_r"])
            + _card("Atraso até 30 dias",  _npl["d30_pct"],   _npl["delta_d30"],   _npl["d30_r"])
            + _card("Atraso 90 dias ou mais", _npl["d90_pct"], _npl["delta_d90"],  _npl["d90_r"])
            + '</div></div>'
        )
        st.markdown(_html, unsafe_allow_html=True)

    st.markdown(
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:52px;'
        f'font-weight:800;color:#e8eaf0;margin-top:32px;margin-bottom:32px;letter-spacing:-1.5px;line-height:1.1">'
        f'Bem-vindo(a), {nome}!</div>',
        unsafe_allow_html=True,
    )

    # ── Indicadores 'Hoje' — fragment próprio, auto-refresh 60s ───────────────
    # Layout horizontal: 'No Lote' (quando aplicável) e 'No Total' (admin).
    # Atendente: vê só 'No Lote' (sua carteira do dia).
    # Admin 'Todos os clientes': vê só 'No Total'.
    # Admin 'Lote do dia' de X: vê 'No Lote de X' + 'No Total'.
    @st.fragment(run_every=60)
    def _indicadores_hoje():
        clientes_full = store.get("clientes", []) or []
        # Helper: conta inadimplentes restantes (não regularizados hoje) +
        # regularizações + parciais. REG e PARC são mutuamente exclusivas;
        # INAD inclui parciais (cliente que pagou parte continua inadimplente).
        def _agg(cs, strict_hoje=False):
            """Conta inad, reg, parc.

            strict_hoje=False (modo LOTE): cliente está no lote do dia,
            então qualquer regularização/parcial detectada vale — é trabalho
            do dia. Cobre o caso: cliente que pagou ontem mas BQ não viu,
            entrou no lote de hoje, overlay detectou durante o dia.

            strict_hoje=True (modo TOTAL): exige _pagamento_foi_hoje pra
            excluir limbo de outros dias. Reflete só pagamentos do DIA
            (placar honesto sem inflação dos 3d do overlay).

            Pra parcial, exige _pago_parcial_hoje (a flag explícita do
            overlay) — sem isso, cliente que pagou cobrança FUTURA
            antecipada (ex: Igreja Evangélica Ministério Somar pagou
            cobrança que vence 06/07) era contado erroneamente como
            parcial só porque _valor_pago_hoje > 0.
            """
            inad_n, reg_n, reg_v, parc_n, parc_v = 0, 0, 0.0, 0, 0.0
            for c in cs:
                vlr = float(c.get("_valor_pago_hoje") or 0)
                foi_hoje = c.get("_pagamento_foi_hoje")
                if c.get("_regularizado_hoje"):
                    # No LOTE: conta direto. No TOTAL: só se foi_hoje.
                    if not strict_hoje or foi_hoje:
                        reg_n += 1
                        reg_v += vlr
                else:
                    inad_n += 1
                    if (
                        c.get("_pago_parcial_hoje")
                        and vlr > 0
                        and (not strict_hoje or foi_hoje)
                    ):
                        parc_n += 1
                        parc_v += vlr
            return inad_n, reg_n, reg_v, parc_n, parc_v

        # Decide quais seções renderizar baseado no contexto:
        #   Atendente:                     mostra só 'No Lote'
        #   Admin em 'Lote do dia':        mostra só 'No Lote' (o atendente
        #                                  selecionado já contextualiza)
        #   Admin em 'Todos os clientes':  mostra só 'No Total'
        _mostrar_lote = (email in _EMAIL_GRUPO) or (
            role == "admin" and _modo_admin == "Lote do dia" and _atendente_sel
        )
        _mostrar_total = (
            role == "admin" and _modo_admin == "Todos os clientes"
        )

        # Mix de fontes:
        #   • Inadimplentes = carteira completa do atendente (todo) — diminui
        #     ao longo do dia conforme pagamentos chegam por qualquer canal
        #   • Reg / Parc = SÓ do lote de hoje (mérito do trabalho do atendente
        #     com a lista priorizada; pagamentos fora do lote não contam aqui)
        lote_inad_n = lote_reg_n = lote_parc_n = 0
        lote_reg_v = lote_parc_v = 0.0
        if _mostrar_lote:
            if email in _EMAIL_GRUPO:
                _atendente_nome = _EMAIL_GRUPO[email]
                _ids_lote = ids_hoje
            else:
                _atendente_nome = _atendente_sel
                _key = f"_tarefas_admin_{hoje_lote()}_{_atendente_sel}"
                _buckets = st.session_state.get(_key, {}) or {}
                _ids_lote = set(_buckets.keys())
            # Inadimplentes: carteira inteira do atendente — descontando reg.
            _carteira_cs = [c for c in clientes_full if c.get("_grupo") == _atendente_nome]
            lote_inad_n = sum(1 for c in _carteira_cs if not c.get("_regularizado_hoje"))
            # Reg + Parc: só do lote do dia (mérito do trabalho do atendente).
            # strict_hoje=False — cliente em lote é trabalho do dia mesmo se
            # liquidação foi ontem (BQ não viu, overlay detectou).
            _lote_cs = [c for c in clientes_full if c.get("id") in _ids_lote]
            _, lote_reg_n, lote_reg_v, lote_parc_n, lote_parc_v = _agg(_lote_cs, strict_hoje=False)
        # Dados do TOTAL — respeita filtros Grupo (incluindo 'Sem especialista')
        # e Situação. Sublabel removido por feedback — visual mais limpo.
        total_inad_n = total_reg_n = total_parc_n = 0
        total_reg_v = total_parc_v = 0.0
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
            # strict_hoje=True — placar honesto do DIA, sem inflar com limbo
            # de pagamentos de 3 dias atrás detectados pelo overlay.
            total_inad_n, total_reg_n, total_reg_v, total_parc_n, total_parc_v = _agg(_total_cs, strict_hoje=True)

        def _palavra(n, sing, plur):
            return sing if n == 1 else plur

        # SVG icons inline (vermelho alerta, verde check, azul relógio)
        _ico_inad = (
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ef4444" '
            'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" '
            'style="flex-shrink:0"><circle cx="12" cy="12" r="9"></circle>'
            '<line x1="12" y1="8" x2="12" y2="13"></line>'
            '<line x1="12" y1="16" x2="12.01" y2="16"></line></svg>'
        )
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

        # Card vertical empilhado: Inadimplentes (1ª linha) + divisor + Reg +
        # divisor + Parc. Mesmo padrão que tinha antes; Inadimplentes só foi
        # adicionada no topo pra mostrar quanto da carteira ainda tá pendente.
        def _card_html(label_topo, sublabel, inad_n, reg_n, reg_v, parc_n, parc_v):
            _inad_palavra = _palavra(inad_n, "inadimplente", "inadimplentes").upper()
            _reg_palavra = _palavra(reg_n, "regularização", "regularizações").upper()
            _parc_palavra = _palavra(parc_n, "parcial", "parciais").upper()
            _reg_v_fmt = fmt_moeda_plain(reg_v)
            _parc_v_fmt = fmt_moeda_plain(parc_v)

            def _linha(ico, count, palavra, valor_fmt, cor_valor):
                _direita = (
                    f'<span style="margin-left:auto;font-size:20px;font-weight:800;'
                    f'color:{cor_valor};font-variant-numeric:tabular-nums">{valor_fmt}</span>'
                ) if valor_fmt else ""
                return (
                    f'<div style="display:flex;align-items:center;gap:8px">'
                    f'{ico}'
                    f'<span style="font-size:26px;font-weight:800;color:#e8eaf0;line-height:1;'
                    f'font-variant-numeric:tabular-nums">{count}</span>'
                    f'<span style="font-size:13px;color:#9ca3af;font-weight:700;'
                    f'letter-spacing:1.2px;text-transform:uppercase">{palavra}</span>'
                    f'{_direita}'
                    f'</div>'
                )

            _divisor = '<div style="height:1px;background:#2a2f42;margin:10px -18px"></div>'

            return (
                f'<div style="flex:1;background:#181c26;border:1px solid #2a2f42;'
                f'border-radius:10px;padding:14px 18px">'
                f'{_linha(_ico_inad, inad_n, _inad_palavra, "", "")}'
                f'{_divisor}'
                f'{_linha(_ico_reg, reg_n, _reg_palavra, _reg_v_fmt, "#7cc243")}'
                f'{_divisor}'
                f'{_linha(_ico_pag, parc_n, _parc_palavra, _parc_v_fmt, "#5fa3ff")}'
                f'</div>'
            )

        # Monta linha horizontal — 1 card por contexto (lote ou total).
        cards_html = []
        if _mostrar_lote:
            cards_html.append(_card_html(
                "No Lote", "",
                lote_inad_n, lote_reg_n, lote_reg_v, lote_parc_n, lote_parc_v,
            ))
        if _mostrar_total:
            cards_html.append(_card_html(
                "No Total", total_label,
                total_inad_n, total_reg_n, total_reg_v, total_parc_n, total_parc_v,
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

        # Em 'Todos os clientes' (admin), os cards M/L/A respeitam
        # os filtros Grupo e Situação. Permite admin focar nos números de
        # um grupo específico sem ter que entrar no modo 'Lote do dia'.
        # Atendente e admin 'Lote do dia' continuam com escopo do lote.
        atendente_logado = _EMAIL_GRUPO.get(email)
        if atendente_logado:
            dados_m, label_m = _metricas_lote_painel(ids_hoje, buckets_hoje), atendente_logado
        elif role == "admin" and _modo_admin == "Lote do dia" and _atendente_sel:
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
        def _canal(bucket, acoes, acoes_hj, regularizado=False, eh_acordo=False,
                   streak_lig=None):
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
                # Cooldown 7d ativo (3 falhas anteriores) — acordo não tem
                # alternativa, mas a atendente vê visualmente que o cliente
                # tá em "tentar novamente" em vez de urgente.
                if streak_lig is not None and streak_lig > 0:
                    return "tentar_novamente"
                return "urgente"
            if bucket != "mensagem":
                if acoes_hj.get("atend"):
                    return "concluida"
                if acoes_hj.get("lig"):
                    return "tentar_novamente"
            if bucket == "ligacao":
                # Cooldown 7d ativo (3 falhas anteriores, ativou após cron) —
                # mesmo tratamento do acordo: vai pra TENTAR NOVAMENTE.
                if streak_lig is not None and streak_lig > 0:
                    return "tentar_novamente"
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

        _e_lote = email in _EMAIL_GRUPO or (role == "admin" and _modo_admin == "Lote do dia")

        # Admin em 'Todos os clientes': IDs em qualquer lote do dia, pra
        # aplicar opacidade nos cards FORA do lote (sinaliza que não estão
        # sendo trabalhados por ninguém hoje).
        _modo_todos_admin = role == "admin" and _modo_admin == "Todos os clientes"
        ids_em_lote_hoje = fetch_ids_em_qualquer_lote_hoje() if _modo_todos_admin else set()

        acordos = []; ligacao = []; so_msg = []; tentar_nov = []; concluida = []; aguardar = []
        for item in fila:
            s, a, c, h = item
            bucket = buckets_hoje.get(c["id"]) if isinstance(buckets_hoje, dict) else None
            acoes_hj = get_painel_acoes_hoje(c["id"])
            eh_acordo = bool(c.get("_tem_acordo")) and (c.get("dias_atraso") or 0) >= 7
            _streak = get_streak_cooldown_dias(c["id"])
            canal = _canal(bucket, a, acoes_hj,
                           regularizado=bool(c.get("_regularizado_hoje")) or bool(c.get("_regularizado_antes_hoje")),
                           eh_acordo=eh_acordo,
                           streak_lig=_streak)
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

