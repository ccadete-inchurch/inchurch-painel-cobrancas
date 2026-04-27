import pandas as pd
import streamlit as st

from helpers import fmt_moeda_plain


def _render_historico(store):
    st.markdown(
        '<div style="font-size:15px;color:#e8eaf0;margin-bottom:16px">'
        '<b style="font-family:Syne,sans-serif;font-size:18px">✅ Histórico de Regularizados</b></div>',
        unsafe_allow_html=True,
    )

    reg = store["regularizados"]
    if not reg:
        st.info("Nenhum cliente regularizado ainda.")
        return

    df_reg = pd.DataFrame(reg)
    df_reg["valor_fmt"]  = df_reg["valor"].apply(fmt_moeda_plain)
    df_reg["tipo_fmt"]   = df_reg["tipo"].map({"auto": "🟢 Automático", "manual": "🔵 Manual"})
    df_reg["status_fmt"] = df_reg["inativo"].apply(lambda x: "INATIVO" if x else "") if "inativo" in df_reg.columns else ""

    st.dataframe(
        df_reg[["data", "nome", "cnpj", "valor_fmt", "atendente", "tipo_fmt", "status_fmt"]].rename(columns={
            "data":       "Data",
            "nome":       "Cliente",
            "cnpj":       "CNPJ",
            "valor_fmt":  "Valor",
            "atendente":  "Atendente",
            "tipo_fmt":   "Tipo",
            "status_fmt": "Situação",
        }),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Data":     st.column_config.TextColumn(width="small"),
            "Situação": st.column_config.TextColumn(width="small"),
        },
    )

    st.markdown(
        f'<div style="margin-top:16px;font-size:13px;color:#8b94a5;text-align:center">'
        f'Total: <b style="color:#7cc243">{len(reg)}</b> clientes regularizados</div>',
        unsafe_allow_html=True,
    )
