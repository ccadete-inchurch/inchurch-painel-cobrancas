import streamlit as st

from config import STATUS_LABELS, STATUS_COLORS
from helpers import get_hist, fmt_moeda_plain, dias_html
from views.dialog import dialog_editar


def _render_cliente(_store, clientes):
    st.markdown(
        '<div style="font-family:Syne,sans-serif;font-size:20px;font-weight:700;margin-bottom:20px">Visão do Cliente</div>',
        unsafe_allow_html=True,
    )

    if not clientes:
        st.info("Nenhum dado disponível. Atualize os dados na tela de Inadimplência.")
        return

    opcoes  = {f"{c['nome']} — {c.get('cnpj','')}": c["id"] for c in sorted(clientes, key=lambda x: x["nome"])}
    sel     = st.selectbox("Selecionar cliente", list(opcoes.keys()), label_visibility="collapsed", key="cliente_sel")
    cid     = opcoes[sel]
    cliente = next((c for c in clientes if c["id"] == cid), None)
    if not cliente:
        return

    h = get_hist(cid)
    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)

    # ── Cards de métricas ─────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    infos = [
        (c1, "Cliente",         cliente["nome"],                    cliente.get("cnpj", "—")),
        (c2, "Saldo em Aberto", fmt_moeda_plain(cliente["valor"]),  f'{len(cliente.get("_cobracas", []))} cobranças'),
        (c3, "Maior Atraso",    f'{cliente.get("dias_atraso","—")}d', cliente.get("vencimento", "—")),
        (c4, "Carteira",        cliente.get("_grupo", "—"),          cliente.get("telefone", "—")),
    ]
    for col, label, val, sub in infos:
        with col:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="metric-label">{label}</div>'
                f'<div style="font-size:15px;font-weight:600;color:#e8eaf0;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{val}</div>'
                f'<div class="metric-sub">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:20px"></div>', unsafe_allow_html=True)

    col_esq, col_dir = st.columns([1.6, 1])

    # ── Cobranças em aberto ───────────────────────────────────────────────────
    with col_esq:
        st.markdown('<div style="font-size:13px;font-weight:700;color:#8b94a5;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">Cobranças em Aberto</div>', unsafe_allow_html=True)
        cobracas = sorted(
            [c for c in cliente.get("_cobracas", []) if c.get("dias_atraso") and c["dias_atraso"] > 0],
            key=lambda x: x.get("dias_atraso", 0),
            reverse=True,
        )
        for cob in cobracas:
            st.markdown(
                f'<div style="background:#181c26;border:1px solid #1e2333;border-radius:10px;padding:12px 16px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center">'
                f'<div>'
                f'<div style="font-size:14px;font-weight:600;color:#e8eaf0">{fmt_moeda_plain(cob["valor"])}</div>'
                f'<div style="font-size:11px;color:#6b7280;margin-top:2px">Venc. {cob["vencimento"]} · {cob["parcelas"]}x competências</div>'
                f'</div>'
                f'<div>{dias_html(cob["dias_atraso"])}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        if not cobracas:
            st.info("Sem cobranças em atraso.")

    # ── Histórico de contato ──────────────────────────────────────────────────
    with col_dir:
        st.markdown('<div style="font-size:13px;font-weight:700;color:#8b94a5;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">Histórico de Contato</div>', unsafe_allow_html=True)

        s   = h.get("status", "pending")
        cor = STATUS_COLORS.get(s, "#6b7280")

        fields = [
            ("Status",           f'<span style="color:{cor};font-weight:700">{STATUS_LABELS.get(s,"—")}</span>'),
            ("Último contato",   h.get("lastContact", "—")),
            ("Retorno agendado", h.get("retorno",     "—") or "—"),
            ("Prometeu pagar",   h.get("promiseDate", "—") or "—"),
            ("Atendente",        h.get("atendente",   "—") or "—"),
        ]
        for label, val in fields:
            st.markdown(
                f'<div style="padding:10px 14px;background:#181c26;border:1px solid #1e2333;border-radius:8px;margin-bottom:6px">'
                f'<div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b7280;margin-bottom:3px">{label}</div>'
                f'<div style="font-size:13px;color:#e8eaf0;font-weight:500">{val}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        if h.get("notes"):
            st.markdown(
                f'<div style="padding:10px 14px;background:#181c26;border:1px solid #1e2333;border-radius:8px;margin-top:4px">'
                f'<div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b7280;margin-bottom:4px">Observações</div>'
                f'<div style="font-size:13px;color:#8b94a5;line-height:1.5">{h["notes"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        if st.button("Editar registro", width="stretch"):
            dialog_editar(cid)

    # ── Placeholder gráficos ──────────────────────────────────────────────────
    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="background:#181c26;border:1px dashed #2a2f42;border-radius:12px;padding:40px;text-align:center;color:#374151;font-size:13px">'
        'Gráficos e análises — em breve'
        '</div>',
        unsafe_allow_html=True,
    )
