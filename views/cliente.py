from datetime import date
import streamlit as st

from config import STATUS_LABELS, STATUS_COLORS
from helpers import get_hist, fmt_moeda_plain, dias_html
from data import fetch_historico_atrasos
from views.dialog import dialog_editar

_MESES_PT = {1:"Jan",2:"Fev",3:"Mar",4:"Abr",5:"Mai",6:"Jun",
             7:"Jul",8:"Ago",9:"Set",10:"Out",11:"Nov",12:"Dez"}


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
    parcelas = cliente.get("parcelas", 0)
    c1, c2, c3, c4 = st.columns(4)
    inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;margin-left:6px;vertical-align:middle">INATIVO</span>' if cliente.get("_inativo") else ""
    infos = [
        (c1, "Cliente",         f'{cliente["nome"]}{inativo_badge}', cliente.get("cnpj", "—")),
        (c2, "Saldo em Aberto", fmt_moeda_plain(cliente["valor"]),   f'{parcelas} parcela{"s" if parcelas != 1 else ""} em atraso'),
        (c3, "Maior Atraso",    f'{cliente.get("dias_atraso","—")}d', cliente.get("vencimento", "—")),
        (c4, "Carteira",        cliente.get("_grupo", "—"),           cliente.get("telefone", "—")),
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
                f'<div style="font-size:11px;color:#6b7280;margin-top:2px">Venc. {cob["vencimento"]}</div>'
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

    # ── Histórico de atrasos — últimos 12 meses ───────────────────────────────
    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:13px;font-weight:700;color:#8b94a5;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px">Histórico de Atrasos — Últimos 12 Meses</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Carregando histórico..."):
        df_hist = fetch_historico_atrasos(cid)

    # Gera lista dos últimos 12 meses (do mais antigo ao mais recente)
    hoje   = date.today()
    meses  = []
    for i in range(11, -1, -1):
        m = hoje.month - i
        y = hoje.year
        while m <= 0:
            m += 12
            y -= 1
        meses.append(f"{y:04d}-{m:02d}")

    hist_dict = {}
    if not df_hist.empty:
        for _, row in df_hist.iterrows():
            hist_dict[row["mes"]] = row

    cells = []
    for mes in meses:
        ano_str, mes_str = mes.split("-")
        label = f"{_MESES_PT[int(mes_str)]}/{ano_str[2:]}"
        data  = hist_dict.get(mes)

        if data is None:
            bg    = "#181c26"
            borda = "#1e2333"
            cor   = "#4b5563"
            icone = "—"
            sub   = "sem registro"
        elif data["parcelas_atraso"] > 0:
            bg    = "rgba(239,68,68,.10)"
            borda = "#ef4444"
            cor   = "#ff5555"
            icone = "●"
            n     = int(data["parcelas_atraso"])
            sub   = f"{n} em atraso"
        else:
            bg    = "rgba(34,197,94,.10)"
            borda = "#22c55e"
            cor   = "#2dd36f"
            icone = "●"
            n     = int(data["parcelas_pagas"])
            sub   = f"{n} pago{'s' if n != 1 else ''}"

        cells.append(
            f'<div style="flex:1;background:{bg};border:1px solid {borda};border-radius:8px;'
            f'padding:10px 6px;text-align:center;min-width:0">'
            f'<div style="font-size:11px;color:#8b94a5;font-weight:600;white-space:nowrap">{label}</div>'
            f'<div style="font-size:16px;color:{cor};margin:4px 0 2px">{icone}</div>'
            f'<div style="font-size:10px;color:{cor};font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{sub}</div>'
            f'</div>'
        )

    st.markdown(
        f'<div style="display:flex;gap:6px">{"".join(cells)}</div>',
        unsafe_allow_html=True,
    )

    # Legenda
    st.markdown(
        '<div style="display:flex;gap:16px;margin-top:10px;font-size:11px;color:#6b7280">'
        '<span><span style="color:#2dd36f;font-weight:700">●</span> Pagou em dia</span>'
        '<span><span style="color:#ff5555;font-weight:700">●</span> Em atraso</span>'
        '<span><span style="color:#4b5563;font-weight:700">—</span> Sem registro</span>'
        '</div>',
        unsafe_allow_html=True,
    )
