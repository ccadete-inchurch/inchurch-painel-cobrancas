import json
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import streamlit as st
from google.cloud import bigquery

from config import MAP_COB, MAP_INAD, DIAS_SEM_CONTATO
from auth import get_store, current_nome
from helpers import calc_dias, parse_date_br, get_col, get_hist


# ── BigQuery ──────────────────────────────────────────────────────────────────

@st.cache_resource
def get_bq_client():
    try:
        return bigquery.Client(project="business-intelligence-467516")
    except Exception as e:
        st.error(f"❌ Erro de autenticação com BigQuery: {str(e)}")
        st.markdown("""
        **Para configurar a autenticação com Google Cloud:**

        1. Abra o terminal/prompt de comando
        2. Execute: `gcloud auth application-default login`
        3. Faça login com sua conta Google
        4. Reinicie o Streamlit

        [Mais informações](https://cloud.google.com/docs/authentication/external/set-up-adc)
        """)
        return None


@st.cache_data(ttl=3600)
def fetch_cobrancas_competencia():
    client = get_bq_client()
    if not client:
        return pd.DataFrame()
    query = """
    SELECT
        c.id_sacado_sac as codigo,
        c.st_nome_sac as nome,
        c.st_cgc_sac as cnpj,
        c.st_telefone_sac as telefone,
        c.vl_total_recb as valor,
        c.dt_vencimento_recb as vencimento,
        c.comp_nm_quantidade_comp as parcelas,
        c.fl_status_recb as status,
        u.nm_grupo as grupo
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` c
    LEFT JOIN `business-intelligence-467516.Splgc.vw-splgc-clientes_unificada` u
        ON c.id_sacado_sac = u.id_sacado_sac
    WHERE c.fl_status_recb = '0'
        AND c.dt_desativacao_sac IS NULL
    ORDER BY c.vl_total_recb DESC
    """
    try:
        return client.query(query).to_dataframe()
    except Exception as e:
        st.error(f"Erro ao puxar dados de competência: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_cobrancas_liquidacao():
    client = get_bq_client()
    if not client:
        return pd.DataFrame()
    query = """
    SELECT
        id_sacado_sac as codigo,
        st_nome_sac as nome,
        st_cgc_sac as cnpj,
        st_telefone_sac as telefone,
        vl_total_recb as valor,
        dt_vencimento_recb as vencimento,
        comp_nm_quantidade_comp as parcelas,
        dt_liquidacao_recb as data_liquidacao,
        fl_status_recb as status
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
    WHERE fl_status_recb = '1'
        AND dt_desativacao_sac IS NULL
    ORDER BY dt_liquidacao_recb DESC
    """
    try:
        return client.query(query).to_dataframe()
    except Exception as e:
        st.error(f"Erro ao puxar dados de liquidação: {e}")
        return pd.DataFrame()


# ── Processamento ─────────────────────────────────────────────────────────────

def processar_dados_bigquery():
    store          = get_store()
    df_competencia = fetch_cobrancas_competencia()
    df_liquidacao  = fetch_cobrancas_liquidacao()

    if df_competencia.empty:
        return [], 0

    clientes_dict = {}

    for _, row in df_competencia.iterrows():
        codigo = str(row["codigo"])

        try:
            vencimento = pd.to_datetime(row["vencimento"]).strftime("%d/%m/%Y") if pd.notna(row["vencimento"]) else ""
        except Exception:
            vencimento = ""

        dias_atraso = calc_dias(vencimento) if vencimento else None

        if codigo in clientes_dict:
            cobranca_item = {
                "valor":       float(row["valor"])   if pd.notna(row["valor"])   else 0.0,
                "vencimento":  vencimento,
                "dias_atraso": dias_atraso,
                "parcelas":    int(row["parcelas"])  if pd.notna(row["parcelas"]) else 0,
                "status":      str(row["status"] or ""),
            }
            clientes_dict[codigo]["_cobracas"].append(cobranca_item)

            if dias_atraso and dias_atraso > 0:
                clientes_dict[codigo]["valor"] += float(row["valor"]) if pd.notna(row["valor"]) else 0.0
                atual_min = clientes_dict[codigo].get("_min_atraso")
                if atual_min is None or dias_atraso < atual_min:
                    clientes_dict[codigo]["_min_atraso"] = dias_atraso

            if dias_atraso and (
                clientes_dict[codigo]["dias_atraso"] is None
                or dias_atraso > clientes_dict[codigo]["dias_atraso"]
            ):
                clientes_dict[codigo]["dias_atraso"] = dias_atraso
                clientes_dict[codigo]["vencimento"]  = vencimento
        else:
            dias_atraso_num = dias_atraso if (dias_atraso and dias_atraso > 0) else None
            valor_devedor   = float(row["valor"]) if pd.notna(row["valor"]) and dias_atraso and dias_atraso > 0 else 0.0

            clientes_dict[codigo] = {
                "id":          codigo,
                "cod":         codigo,
                "nome":        str(row["nome"]     or ""),
                "cnpj":        str(row["cnpj"]     or ""),
                "telefone":    str(row["telefone"] or ""),
                "valor":       valor_devedor,
                "vencimento":  vencimento,
                "dias_atraso": dias_atraso_num,
                "_min_atraso": dias_atraso_num,
                "_novo":       False,
                "_atualizado": False,
                "_grupo":      str(row.get("grupo", "") or "—"),
                "_cobracas":   [{
                    "valor":       float(row["valor"])  if pd.notna(row["valor"])  else 0.0,
                    "vencimento":  vencimento,
                    "dias_atraso": dias_atraso,
                    "parcelas":    int(row["parcelas"]) if pd.notna(row["parcelas"]) else 0,
                    "status":      str(row["status"] or ""),
                }],
            }

    for c in clientes_dict.values():
        oldest = c.get("dias_atraso") or 0
        newest = c.get("_min_atraso") or 0
        c["_nova_cobranca"] = (oldest > 30 and 0 < newest <= 30)

    clientes = [c for c in clientes_dict.values() if c["valor"] > 0]

    historico_regularizados = []
    for _, row in df_liquidacao.iterrows():
        try:
            data_liq = pd.to_datetime(row["data_liquidacao"]).strftime("%d/%m/%Y") if pd.notna(row["data_liquidacao"]) else date.today().strftime("%d/%m/%Y")
        except Exception:
            data_liq = date.today().strftime("%d/%m/%Y")

        historico_regularizados.append({
            "id":        str(row["codigo"]),
            "nome":      str(row["nome"]  or ""),
            "cnpj":      str(row["cnpj"]  or ""),
            "valor":     float(row["valor"]) if pd.notna(row["valor"]) else 0.0,
            "atendente": "Sistema (BigQuery)",
            "data":      data_liq,
            "tipo":      "auto",
        })

    store["clientes"]           = clientes
    store["regularizados"]      = historico_regularizados
    store["ultima_atualizacao"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    salvar_cache_local()

    return clientes, len(historico_regularizados)


def importar_planilhas(f_cob, f_inad):
    store = get_store()

    def ler(f):
        try:
            return pd.read_excel(f) if f.name.endswith(("xlsx", "xls")) else pd.read_csv(f)
        except Exception as e:
            st.toast(f"⚠️ Erro ao ler {f.name}: {e}", icon="⚠️")
            return pd.DataFrame()

    df_cob  = ler(f_cob)
    df_inad = ler(f_inad)
    if df_cob.empty or df_inad.empty:
        return [], 0, 0, 0

    df_cob["_cod"]  = df_cob[MAP_COB["codigo"]].astype(str).str.strip()
    df_inad["_cod"] = df_inad[MAP_INAD["codigo"]].astype(str).str.strip()

    idx_cob = {}
    for _, row in df_cob.iterrows():
        cod = row["_cod"]
        if not cod:
            continue
        try:
            vd = pd.to_datetime(row.get(MAP_COB["vencimento"]))
        except Exception:
            vd = None
        if cod not in idx_cob or (vd and idx_cob[cod]["vd"] and vd > idx_cob[cod]["vd"]):
            idx_cob[cod] = {"vd": vd, "vr": row.get(MAP_COB["vencimento"]), "tel": get_col(row, MAP_COB["telefone"])}

    ids_ant  = {c["id"]: c["valor"] for c in store["clientes"]}
    clientes = []

    for _, row in df_inad.iterrows():
        cod = row["_cod"]
        if not cod:
            continue
        nome = get_col(row, MAP_INAD["nome"])
        cnpj = get_col(row, MAP_INAD["cnpj"])
        tel  = get_col(row, MAP_INAD["telefone1"]) or get_col(row, MAP_INAD["telefone2"])
        try:
            valor = float(row.get(MAP_INAD["valor"]) or 0)
        except Exception:
            valor = 0.0
        try:
            parcelas = int(row.get(MAP_INAD["parcelas"]) or 0)
        except Exception:
            parcelas = 0

        venc = ""
        if cod in idx_cob:
            vr = idx_cob[cod]["vr"]
            if vr is not None and pd.notna(vr):
                try:
                    venc = pd.to_datetime(vr).strftime("%d/%m/%Y")
                except Exception:
                    venc = str(vr)
            if not tel:
                tel = idx_cob[cod]["tel"]

        is_novo = cod not in ids_ant
        is_upd  = (not is_novo) and (ids_ant.get(cod, 0) != valor)

        clientes.append({
            "id": cod, "cod": cod, "nome": nome, "cnpj": cnpj,
            "telefone": tel, "valor": valor, "parcelas": parcelas,
            "vencimento": venc, "dias_atraso": calc_dias(venc),
            "_novo": is_novo, "_atualizado": is_upd,
        })

    ids_novos = {c["id"] for c in clientes}
    removidos = [c for c in store["clientes"] if c["id"] not in ids_novos]
    hoje      = date.today().strftime("%d/%m/%Y")
    for c in removidos:
        store["regularizados"].append({
            "id": c["id"], "nome": c["nome"], "cnpj": c.get("cnpj", ""),
            "valor": c["valor"], "atendente": current_nome(), "data": hoje, "tipo": "auto",
        })

    store["clientes"]           = clientes
    store["ultima_atualizacao"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    return clientes, sum(c["_novo"] for c in clientes), sum(c["_atualizado"] for c in clientes), len(removidos)


def calcular_pendencias(clientes):
    pendencias = []
    hoje       = date.today()
    for c in clientes:
        h = get_hist(c["id"])
        s = h.get("status", "pending")
        if s == "paid":
            continue
        if s == "promise" and h.get("promiseDate"):
            dt = parse_date_br(h["promiseDate"])
            if dt and dt <= hoje:
                pendencias.append((c, h, "promise", f"Prometeu pagar em {h['promiseDate']}"))
                continue
        if h.get("retorno"):
            dt = parse_date_br(h["retorno"])
            if dt and dt <= hoje:
                pendencias.append((c, h, "retorno", f"Retorno para {h['retorno']}"))
                continue
        if h.get("lastContact"):
            dt = parse_date_br(h["lastContact"])
            if dt:
                diff = (hoje - dt).days
                if diff >= DIAS_SEM_CONTATO:
                    pendencias.append((c, h, "semcontato", f"Sem contato há {diff} dias"))
    return pendencias


# ── Cache local ───────────────────────────────────────────────────────────────

def salvar_cache_local():
    store      = get_store()
    cache_file = Path(__file__).parent / "cache_dados.json"
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({
                "clientes":           store["clientes"],
                "regularizados":      store["regularizados"],
                "ultima_atualizacao": store["ultima_atualizacao"],
            }, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def carregar_cache_local():
    cache_file = Path(__file__).parent / "cache_dados.json"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        store                       = get_store()
        store["clientes"]           = data.get("clientes",           [])
        store["regularizados"]      = data.get("regularizados",      [])
        store["ultima_atualizacao"] = data.get("ultima_atualizacao", "")
        return True
    except Exception:
        return False
