from datetime import date
import pandas as pd
import altair as alt
import streamlit as st

from config import STATUS_LABELS, STATUS_COLORS
from helpers import get_hist, get_hist_unificado, get_effective_status, get_effective_lastContact, get_effective_atendente, fmt_moeda_plain, dias_html
from data import fetch_historico_atrasos, fetch_evolucao_saldo_mensal
from views.dialog import dialog_editar

_MESES_PT = {1:"Jan",2:"Fev",3:"Mar",4:"Abr",5:"Mai",6:"Jun",
             7:"Jul",8:"Ago",9:"Set",10:"Out",11:"Nov",12:"Dez"}

# Estilos compartilhados
_CARD_LABEL_CSS = "font-size:13px;letter-spacing:1.2px"
_CARD_SUB_CSS   = "font-size:13px;margin-top:6px"
_CARD_VALUE_CSS = "font-size:22px;font-weight:800;margin-top:6px;line-height:1.1;font-variant-numeric:tabular-nums"
_SECTION_TITLE_CSS = "font-size:18px;font-weight:700;color:#e8eaf0;margin-bottom:14px;letter-spacing:-0.3px"


def _render_cliente(_store, clientes):
    st.markdown(
        '<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:36px;'
        'font-weight:800;color:#e8eaf0;margin-top:24px;margin-bottom:24px;letter-spacing:-1px;line-height:1.1">'
        'Visão do Cliente</div>',
        unsafe_allow_html=True,
    )

    if not clientes:
        st.info("Nenhum dado disponível. Atualize os dados na tela de Inadimplência.")
        return

    # Busca textual: filtra por nome, CNPJ ou ID do sacado. Dropdown abaixo
    # mostra só o nome da igreja — limpo, sem o sufixo "— CNPJ".
    f1, f2 = st.columns([1.5, 2])
    with f1:
        busca = st.text_input(
            "Buscar",
            placeholder="Nome, CNPJ ou ID do sacado...",
            key="cliente_busca",
        )
    # Filtra clientes que regularizaram hoje via overlay da API — não devem
    # aparecer na lista de inadimplentes pra evitar contato repetido.
    base = [c for c in clientes if not c.get("_regularizado_hoje")]
    _reg_hoje = len(clientes) - len(base)

    pool = base
    if busca:
        b = busca.lower().strip()
        pool = [
            c for c in base
            if b in str(c.get("nome", "")).lower()
            or b in str(c.get("cnpj", "")).lower()
            or b in str(c.get("id", "")).lower()
        ]
    if not pool:
        with f2:
            st.markdown('<div style="padding-top:30px;color:#6b7280;font-size:13px">Nenhum cliente encontrado.</div>', unsafe_allow_html=True)
        return

    # Dropdown: nome só, MAS quando há mais de um cliente com o mesmo nome
    # (ex.: "Ministério Ide" em 3 CNPJ diferentes), sufixamos com o CNPJ pra
    # o atendente escolher o certo. Sem o sufixo, viraria escolha cega.
    _nome_counts = {}
    for c in pool:
        _nome_counts[c["nome"]] = _nome_counts.get(c["nome"], 0) + 1

    def _label_dropdown(c):
        nome = c["nome"]
        if _nome_counts.get(nome, 0) > 1:
            extra = c.get("cnpj") or f"ID {c['id']}"
            return f"{nome} · {extra}"
        return nome

    opcoes = {c["id"]: _label_dropdown(c) for c in sorted(pool, key=lambda x: x["nome"])}
    # Label: total restante + nota de quantos regularizaram hoje (se > 0)
    _label_topo = f"Cliente ({len(opcoes)} {'encontrado' if len(opcoes) == 1 else 'encontrados'}"
    if _reg_hoje > 0:
        _label_topo += f" · {_reg_hoje} regularizou hoje" if _reg_hoje == 1 else f" · {_reg_hoje} regularizaram hoje"
    _label_topo += ")"
    with f2:
        cid = st.selectbox(
            _label_topo,
            list(opcoes.keys()),
            format_func=lambda k: opcoes[k],
            key="cliente_sel",
        )
    cliente = next((c for c in clientes if c["id"] == cid), None)
    if not cliente:
        return

    # h: histórico unificado — mesma fonte da Inadimplência (admin vê
    # status/promessa/retorno das duas atendentes mesclados).
    h = get_hist_unificado(cid)
    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)

    # ── Cards de métricas ─────────────────────────────────────────────────────
    parcelas = cliente.get("parcelas", 0)
    c1, c2, c3, c4 = st.columns(4)
    inativo_badge = '<span style="background:#6b7280;color:#fff;font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;margin-left:8px;vertical-align:middle">INATIVO</span>' if cliente.get("_inativo") else ""

    # Valor de cada card — 22px nos numéricos, 16px nos textos (nome/grupo).
    # Cores preservadas: Saldo vermelho, demais brancos.
    cards = [
        (
            c1, "Cliente",
            f'<div style="{_CARD_VALUE_CSS};font-size:16px;color:#e8eaf0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{cliente["nome"]}{inativo_badge}</div>',
            cliente.get("cnpj", "—"),
        ),
        (
            c2, "Saldo em Aberto",
            f'<div style="{_CARD_VALUE_CSS};color:#ef4444">{fmt_moeda_plain(cliente["valor"])}</div>',
            f'{parcelas} parcela{"s" if parcelas != 1 else ""} em atraso',
        ),
        (
            c3, "Maior Atraso",
            f'<div style="{_CARD_VALUE_CSS};color:#e8eaf0">{cliente.get("dias_atraso","—")}<span style="font-size:14px;color:#8b94a5;margin-left:4px;font-weight:600">dias</span></div>',
            cliente.get("vencimento", "—"),
        ),
        (
            c4, "Carteira",
            f'<div style="{_CARD_VALUE_CSS};font-size:16px;color:#e8eaf0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{cliente.get("_grupo", "—")}</div>',
            cliente.get("telefone", "—"),
        ),
    ]
    for col, label, val_html, sub in cards:
        with col:
            st.markdown(
                f'<div class="metric-card" style="padding:18px 20px">'
                f'<div class="metric-label" style="{_CARD_LABEL_CSS}">{label}</div>'
                f'{val_html}'
                f'<div class="metric-sub" style="{_CARD_SUB_CSS}">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Evolução do Saldo Devedor — depois dos cards ─────────────────────────
    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="{_SECTION_TITLE_CSS}">Evolução do Saldo Devedor — Últimos 12 Meses</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Calculando evolução do saldo..."):
        df_evol = fetch_evolucao_saldo_mensal(cid)

    if df_evol.empty:
        st.markdown(
            '<div style="background:#181c26;border:1px solid #1e2333;border-radius:10px;'
            'padding:30px;text-align:center;color:#6b7280;font-size:13px">'
            'Sem dados de saldo para esse cliente.</div>',
            unsafe_allow_html=True,
        )
    else:
        df_evol = df_evol.copy()
        df_evol["mes_dt"]    = pd.to_datetime(df_evol["mes"] + "-01", format="%Y-%m-%d", errors="coerce")
        df_evol              = df_evol.sort_values("mes_dt")
        df_evol["mes_label"] = df_evol["mes_dt"].dt.strftime("%b/%y").str.capitalize()
        df_evol["saldo_fmt"] = df_evol["saldo"].apply(fmt_moeda_plain)

        # Eixo Y usa labelExpr pra prefixar 'R$ ' (Altair não tem currency BRL
        # nativo; '$,.0f' coloca cifrão de dólar)
        x_enc = alt.X(
            "mes_dt:T",
            title=None,
            axis=alt.Axis(
                format="%b/%y",
                labelAngle=0,
                labelColor="#8b94a5",
                tickColor="#2a2f42",
                domainColor="#2a2f42",
                grid=False,
            ),
        )
        y_enc = alt.Y(
            "saldo:Q",
            title=None,
            axis=alt.Axis(
                labelExpr="'R$ ' + format(datum.value, ',.0f')",
                labelColor="#8b94a5",
                tickColor="#2a2f42",
                domainColor="#2a2f42",
                gridColor="#1e2333",
                gridOpacity=0.5,
            ),
        )
        # Tooltip uniforme em todas as marcas
        tooltip_enc = [
            alt.Tooltip("mes_label:N", title="Mês"),
            alt.Tooltip("saldo_fmt:N", title="Saldo"),
        ]

        base = alt.Chart(df_evol).encode(x=x_enc, y=y_enc, tooltip=tooltip_enc)
        area = base.mark_area(
            interpolate="monotone",
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color="rgba(239,68,68,0.0)", offset=0),
                    alt.GradientStop(color="rgba(239,68,68,0.25)", offset=1),
                ],
                x1=1, x2=1, y1=1, y2=0,
            ),
        )
        linha = base.mark_line(color="#ef4444", strokeWidth=2.5, interpolate="monotone")
        pontos = base.mark_circle(color="#ef4444", size=70, stroke="#0f1117", strokeWidth=2)

        chart = (area + linha + pontos).properties(
            height=280,
            padding={"left": 0, "top": 10, "right": 10, "bottom": 0},
        ).configure_view(
            stroke=None, fill="#181c26",
        ).configure(background="#181c26")

        st.altair_chart(chart, use_container_width=True)

        # Tendência: média 3 primeiros vs 3 últimos meses
        if len(df_evol) >= 6:
            avg_inicio = df_evol["saldo"].iloc[:3].mean()
            avg_fim    = df_evol["saldo"].iloc[-3:].mean()
            if avg_inicio > 0:
                delta_pct = (avg_fim - avg_inicio) / avg_inicio * 100
                if abs(delta_pct) < 10:
                    tendencia, cor_t = "estável", "#8b94a5"
                elif delta_pct > 0:
                    tendencia, cor_t = f"crescendo {delta_pct:+.0f}%", "#ef4444"
                else:
                    tendencia, cor_t = f"reduzindo {delta_pct:+.0f}%", "#2dd36f"
            else:
                tendencia, cor_t = "saldo estava zerado no início", "#8b94a5"
            st.markdown(
                f'<div style="font-size:12px;color:#6b7280;margin-top:8px;text-align:right">'
                f'Tendência (média 3 primeiros vs 3 últimos meses): '
                f'<span style="color:{cor_t};font-weight:700">{tendencia}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)

    # Split 50/50 — ambas seções agora são compactas, sem desperdício lateral.
    col_esq, col_dir = st.columns([1, 1])

    # ── Cobranças em aberto — tabela compacta ─────────────────────────────────
    with col_esq:
        cobracas = sorted(
            [c for c in cliente.get("_cobracas", []) if c.get("dias_atraso") and c["dias_atraso"] > 0],
            key=lambda x: x.get("dias_atraso", 0),
            reverse=True,
        )
        # Header com resumo: total + quantidade
        total_cob = sum(float(c.get("valor") or 0) for c in cobracas)
        resumo = (
            f' · {fmt_moeda_plain(total_cob)} · {len(cobracas)} parcela{"s" if len(cobracas) != 1 else ""}'
            if cobracas else ""
        )
        st.markdown(
            f'<div style="{_SECTION_TITLE_CSS}">Cobranças em Aberto'
            f'<span style="font-size:13px;color:#8b94a5;font-weight:500">{resumo}</span></div>',
            unsafe_allow_html=True,
        )

        if not cobracas:
            st.markdown(
                '<div style="background:#181c26;border:1px solid #1e2333;border-radius:10px;'
                'padding:24px;text-align:center;color:#6b7280;font-size:13px">'
                'Sem cobranças em atraso.</div>',
                unsafe_allow_html=True,
            )
        else:
            # Tabela: cabeçalho + linhas em flex (mesmo padrão da tela Pagamentos)
            hdr_html = (
                '<div style="display:flex;background:#1e2333;border:1px solid #2a2f42;'
                'border-radius:8px 8px 0 0;padding:8px 12px;font-size:11px;'
                'text-transform:uppercase;letter-spacing:1px;color:#8b94a5;font-weight:700">'
                '<div style="flex:1.2">Valor</div>'
                '<div style="flex:1">Vencimento</div>'
                '<div style="flex:0.8;text-align:right">Atraso</div>'
                '</div>'
            )
            rows_html = []
            for i, cob in enumerate(cobracas):
                last = (i == len(cobracas) - 1)
                radius = "border-radius:0 0 8px 8px;" if last else ""
                border = "border:1px solid #2a2f42;border-top:none;"
                rows_html.append(
                    f'<div style="display:flex;align-items:center;background:#181c26;'
                    f'{border}{radius}padding:8px 12px;font-size:13px">'
                    f'<div style="flex:1.2;color:#e8eaf0;font-weight:600">{fmt_moeda_plain(cob["valor"])}</div>'
                    f'<div style="flex:1;color:#8b94a5">{cob["vencimento"]}</div>'
                    f'<div style="flex:0.8;text-align:right">{dias_html(cob["dias_atraso"])}</div>'
                    f'</div>'
                )
            st.markdown(hdr_html + "".join(rows_html), unsafe_allow_html=True)

    # ── Histórico de Contato — bloco compacto com grid 2×2 ───────────────────
    with col_dir:
        st.markdown(f'<div style="{_SECTION_TITLE_CSS}">Histórico de Contato</div>', unsafe_allow_html=True)

        s   = get_effective_status(cid)
        cor = STATUS_COLORS.get(s, "#6b7280")
        ult_contato = get_effective_lastContact(cid) or "—"
        atendente   = get_effective_atendente(cid) or "—"
        retorno     = h.get("retorno", "—") or "—"
        promessa    = h.get("promiseDate", "—") or "—"

        def _fld(label, valor_html):
            return (
                f'<div style="padding:8px 12px;flex:1;min-width:0">'
                f'<div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;'
                f'color:#6b7280;margin-bottom:2px">{label}</div>'
                f'<div style="font-size:13px;color:#e8eaf0;font-weight:500;'
                f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{valor_html}</div>'
                f'</div>'
            )

        status_val   = f'<span style="color:{cor};font-weight:700">{STATUS_LABELS.get(s,"—")}</span>'

        # Bloco único com border, grid 2×3 dentro (3 linhas de 2 campos)
        bloco_html = (
            '<div style="background:#181c26;border:1px solid #1e2333;border-radius:10px;'
            'padding:4px 6px;display:flex;flex-direction:column">'
            f'<div style="display:flex">{_fld("Status", status_val)}{_fld("Especialista", atendente)}</div>'
            '<div style="height:1px;background:#1e2333;margin:0 8px"></div>'
            f'<div style="display:flex">{_fld("Último contato", ult_contato)}{_fld("Retorno agendado", retorno)}</div>'
            '<div style="height:1px;background:#1e2333;margin:0 8px"></div>'
            f'<div style="display:flex">{_fld("Prometeu pagar", promessa)}{_fld("", "")}</div>'
            '</div>'
        )
        st.markdown(bloco_html, unsafe_allow_html=True)

        if h.get("notes"):
            st.markdown(
                f'<div style="padding:10px 14px;background:#181c26;border:1px solid #1e2333;border-radius:8px;margin-top:8px">'
                f'<div style="font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b7280;margin-bottom:4px">Observações</div>'
                f'<div style="font-size:13px;color:#8b94a5;line-height:1.5">{h["notes"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
        if st.button("Editar registro", width="stretch"):
            dialog_editar(cid)

    # ── Histórico de atrasos — últimos 12 meses ───────────────────────────────
    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="{_SECTION_TITLE_CSS}">Histórico de Atrasos — Últimos 12 Meses</div>',
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
