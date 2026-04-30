import json
import time
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

# ── OAuth popup: armazenamento temporário compartilhado entre sessões ─────────
_pending_oauth: dict = {}

def set_pending_oauth(nonce: str, email: str, nome: str) -> None:
    cutoff = time.time() - 120
    for k in list(_pending_oauth):
        if _pending_oauth[k]["ts"] < cutoff:
            del _pending_oauth[k]
    _pending_oauth[nonce] = {"email": email, "nome": nome, "ts": time.time()}

def get_pending_oauth(nonce: str) -> dict | None:
    entry = _pending_oauth.get(nonce)
    if entry and (time.time() - entry["ts"]) < 60:
        del _pending_oauth[nonce]
        return entry
    return None

import pandas as pd
import streamlit as st
from google.cloud import bigquery

from config import MAP_COB, MAP_INAD, DIAS_SEM_CONTATO
from auth import get_store, current_nome
from helpers import calc_dias, parse_date_br, get_col, get_hist, fmt_tel


# ── BigQuery ──────────────────────────────────────────────────────────────────

_BQ_PROJECT  = "business-intelligence-467516"
_BQ_DATASET  = "inadimplencia_painel_cobrancas"
_HIST_TABLE  = f"{_BQ_PROJECT}.{_BQ_DATASET}.painel_historico"
_N8N_TABLE   = f"{_BQ_PROJECT}.N8N.n8nfinchatbot_historico_atendente"

_MSG_CONCLUIDA    = ("além da ligação",)
_MSG_NAO_ATENDIDA = ("não estava disponível",)
_MSG_PRE_LIGACAO  = ("vou te ligar em instantes",)


@st.cache_resource
def get_bq_client():
    try:
        if "gcp_service_account" in st.secrets:
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            return bigquery.Client(project=_BQ_PROJECT, credentials=credentials)
        return bigquery.Client(project=_BQ_PROJECT)
    except Exception as e:
        st.error(f"❌ Erro de autenticação com BigQuery: {str(e)}")
        st.markdown("""
        **Para configurar a autenticação:**
        - **Local**: `gcloud auth application-default login`
        - **Streamlit Cloud**: configure `st.secrets["gcp_service_account"]`
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
        c.id_recebimento_recb as id_recebimento,
        c.st_nome_sac as nome,
        c.st_cgc_sac as cnpj,
        COALESCE(NULLIF(cli.st_fax_sac, ''), c.st_telefone_sac) as telefone,
        c.comp_valor as valor,
        FORMAT_TIMESTAMP('%Y-%m-%d', c.dt_vencimento_recb) as vencimento,
        c.fl_status_recb as status,
        u.nm_grupo as grupo,
        p.parcelas_em_atraso as parcelas,
        CASE WHEN ac.id_sacado_sac IS NOT NULL THEN TRUE ELSE FALSE END as tem_acordo,
        CASE WHEN c.dt_desativacao_sac IS NOT NULL THEN TRUE ELSE FALSE END as inativo
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` c
    LEFT JOIN (
        SELECT CAST(id_sacado_sac AS STRING) AS id_sacado_sac, MAX(grupo) AS nm_grupo
        FROM `business-intelligence-467516.Splgc.vw-splgc-clientes_unificada`
        GROUP BY id_sacado_sac
    ) u ON CAST(c.id_sacado_sac AS STRING) = u.id_sacado_sac
    LEFT JOIN (
        SELECT CAST(id_sacado_sac AS STRING) AS id_sacado_sac, MAX(st_fax_sac) AS st_fax_sac
        FROM `business-intelligence-467516.Splgc.splgc-clientes-inchurch`
        GROUP BY id_sacado_sac
    ) cli ON CAST(c.id_sacado_sac AS STRING) = cli.id_sacado_sac
    LEFT JOIN (
        SELECT id_sacado_sac, COUNT(DISTINCT id_recebimento_recb) as parcelas_em_atraso
        FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
        WHERE fl_status_recb = '0'
        GROUP BY id_sacado_sac
    ) p ON c.id_sacado_sac = p.id_sacado_sac
    LEFT JOIN (
        SELECT DISTINCT id_sacado_sac
        FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
        WHERE comp_st_conta_cont = '1.2.13'
          AND fl_status_recb = '0'
    ) ac ON c.id_sacado_sac = ac.id_sacado_sac
    WHERE c.fl_status_recb = '0'
    ORDER BY c.comp_valor DESC
    """
    try:
        return client.query(query).to_dataframe()
    except Exception as e:
        st.error(f"Erro ao puxar dados de competência: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_historico_atrasos(cliente_id: str) -> pd.DataFrame:
    client = get_bq_client()
    if not client:
        return pd.DataFrame()
    query = f"""
    WITH em_atraso AS (
      SELECT DISTINCT id_recebimento_recb, dt_vencimento_recb, comp_valor, 'atraso' AS situacao
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE fl_status_recb = '0'
        AND id_sacado_sac = '{cliente_id}'
        AND dt_vencimento_recb <= CURRENT_TIMESTAMP()
    ),
    pago AS (
      SELECT DISTINCT id_recebimento_recb, dt_vencimento_recb, comp_valor, 'pago' AS situacao
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
      WHERE fl_status_recb = '1'
        AND id_sacado_sac = '{cliente_id}'
        AND dt_vencimento_recb >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 365 DAY)
        AND dt_vencimento_recb <= CURRENT_TIMESTAMP()
    )
    SELECT
      FORMAT_TIMESTAMP('%Y-%m', dt_vencimento_recb) AS mes,
      COUNTIF(situacao = 'atraso') AS parcelas_atraso,
      COUNTIF(situacao = 'pago')   AS parcelas_pagas,
      ROUND(SUM(CASE WHEN situacao = 'atraso' THEN comp_valor ELSE 0 END), 2) AS valor_atraso,
      ROUND(SUM(CASE WHEN situacao = 'pago'   THEN comp_valor ELSE 0 END), 2) AS valor_pago
    FROM (SELECT * FROM em_atraso UNION ALL SELECT * FROM pago)
    GROUP BY 1
    ORDER BY 1 ASC
    """
    try:
        return client.query(query).to_dataframe()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_proximas_cobracas(days: int = 30) -> pd.DataFrame:
    client = get_bq_client()
    if not client:
        return pd.DataFrame()
    query = f"""
    SELECT
        c.id_sacado_sac                                      AS codigo,
        MAX(c.st_nome_sac)                                        AS nome,
        MAX(c.st_cgc_sac)                                         AS cnpj,
        MAX(COALESCE(NULLIF(cli.st_fax_sac, ''), c.st_telefone_sac)) AS telefone,
        MAX(c.comp_valor)                                      AS valor,
        FORMAT_TIMESTAMP('%Y-%m-%d', MAX(c.dt_vencimento_recb))   AS vencimento,
        MAX(u.nm_grupo)                                           AS grupo,
        MAX(CASE WHEN c.dt_desativacao_sac IS NOT NULL THEN TRUE ELSE FALSE END) AS inativo
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` c
    LEFT JOIN (
        SELECT CAST(id_sacado_sac AS STRING) AS id_sacado_sac, MAX(grupo) AS nm_grupo
        FROM `business-intelligence-467516.Splgc.vw-splgc-clientes_unificada`
        GROUP BY id_sacado_sac
    ) u ON CAST(c.id_sacado_sac AS STRING) = u.id_sacado_sac
    LEFT JOIN (
        SELECT CAST(id_sacado_sac AS STRING) AS id_sacado_sac, MAX(st_fax_sac) AS st_fax_sac
        FROM `business-intelligence-467516.Splgc.splgc-clientes-inchurch`
        GROUP BY id_sacado_sac
    ) cli ON CAST(c.id_sacado_sac AS STRING) = cli.id_sacado_sac
    WHERE c.fl_status_recb    = '0'
      AND c.dt_vencimento_recb > CURRENT_TIMESTAMP()
      AND c.dt_vencimento_recb <= TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
    GROUP BY c.id_sacado_sac, c.id_recebimento_recb
    ORDER BY MAX(c.dt_vencimento_recb) ASC
    """
    try:
        return client.query(query).to_dataframe()
    except Exception as e:
        st.error(f"Erro ao puxar próximas cobranças: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_historico_meses_bulk() -> pd.DataFrame:
    client = get_bq_client()
    if not client:
        return pd.DataFrame()
    query = """
    WITH meses AS (
        -- Faturas ainda em atraso com vencimento nos últimos 12 meses
        SELECT DISTINCT id_sacado_sac, FORMAT_TIMESTAMP('%Y-%m', dt_vencimento_recb) AS mes
        FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
        WHERE fl_status_recb = '0'
          AND dt_vencimento_recb >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 365 DAY)
          AND dt_vencimento_recb <= CURRENT_TIMESTAMP()

        UNION DISTINCT

        -- Faturas pagas com atraso (liquidação após vencimento) nos últimos 12 meses
        SELECT DISTINCT id_sacado_sac, FORMAT_TIMESTAMP('%Y-%m', dt_vencimento_recb) AS mes
        FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
        WHERE fl_status_recb = '1'
          AND dt_liquidacao_recb > dt_vencimento_recb
          AND dt_vencimento_recb >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 365 DAY)
          AND dt_vencimento_recb <= CURRENT_TIMESTAMP()
    )
    SELECT
        CAST(id_sacado_sac AS STRING) AS id_sacado_sac,
        COUNT(DISTINCT mes) AS meses_em_atraso
    FROM meses
    GROUP BY id_sacado_sac
    """
    try:
        return client.query(query).to_dataframe()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_cobrancas_liquidacao():
    client = get_bq_client()
    if not client:
        return pd.DataFrame()
    query = """
    SELECT
        id_sacado_sac                                              AS codigo,
        MAX(st_nome_sac)                                          AS nome,
        MAX(st_cgc_sac)                                           AS cnpj,
        SUM(comp_valor)                                           AS valor,
        FORMAT_TIMESTAMP('%Y-%m-%d', MAX(dt_liquidacao_recb))     AS data_liquidacao,
        MAX(CASE WHEN dt_desativacao_sac IS NOT NULL THEN TRUE ELSE FALSE END) AS inativo
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
    WHERE fl_status_recb = '1'
      AND dt_liquidacao_recb <= CURRENT_TIMESTAMP()
    GROUP BY id_sacado_sac, id_recebimento_recb
    HAVING SUM(comp_valor) > 0
    ORDER BY MAX(dt_liquidacao_recb) DESC
    """
    try:
        return client.query(query).to_dataframe()
    except Exception as e:
        st.error(f"Erro ao puxar dados de liquidação: {e}")
        return pd.DataFrame()


# ── Historico de atendimento no BigQuery ─────────────────────────────────────

def ensure_historico_table():
    """Cria a tabela painel_historico no BQ se não existir."""
    client = get_bq_client()
    if not client:
        return
    schema = [
        bigquery.SchemaField("uid",            "STRING",    mode="REQUIRED"),
        bigquery.SchemaField("cliente_id",     "STRING",    mode="REQUIRED"),
        bigquery.SchemaField("historico_json", "STRING"),
        bigquery.SchemaField("updated_at",     "TIMESTAMP"),
    ]
    table = bigquery.Table(_HIST_TABLE, schema=schema)
    try:
        client.create_table(table, exists_ok=True)
    except Exception:
        pass


def load_historico_from_bq():
    """Carrega todo o historico do usuário logado do BQ para o session_state."""
    from auth import current_uid, get_store as _get_store
    uid = current_uid()
    if not uid:
        return
    client = get_bq_client()
    if not client:
        return
    ensure_historico_table()
    query = """
    SELECT cliente_id, historico_json
    FROM (
        SELECT cliente_id, historico_json,
               ROW_NUMBER() OVER (PARTITION BY cliente_id ORDER BY updated_at DESC) AS rn
        FROM `{table}`
        WHERE uid = @uid
    )
    WHERE rn = 1
    """.format(table=_HIST_TABLE)
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("uid", "STRING", uid)]
    )
    try:
        df = client.query(query, job_config=job_config).to_dataframe()
        store = _get_store()
        if uid not in store["historico"]:
            store["historico"][uid] = {}
        for _, row in df.iterrows():
            try:
                store["historico"][uid][row["cliente_id"]] = json.loads(row["historico_json"])
            except Exception:
                pass
    except Exception:
        pass


def load_mensagens_from_bq():
    """1x por sessão — lê tabela completa para detectar status de cada telefone."""
    import re
    from datetime import timezone as _tz

    def _norm(phone: str) -> str:
        p = re.sub(r'\D', '', phone or '')
        if p.startswith('55') and len(p) > 11:
            p = p[2:]
        return (p[:2] + p[-8:]) if len(p) >= 10 else p

    st.session_state.setdefault("_msg_status", {})
    st.session_state.setdefault("_msg_concluida_dias", {})

    client = get_bq_client()
    if not client:
        return

    try:
        df = client.query(f"""
            SELECT telefone, message, created_at
            FROM `{_N8N_TABLE}`
            ORDER BY created_at ASC
        """).to_dataframe()
    except Exception:
        return

    status_map   = {}
    concluida_ts = {}

    for _, row in df.iterrows():
        chave = _norm(str(row.get("telefone") or ""))
        if not chave:
            continue
        msg = str(row.get("message") or "").lower()
        ts  = row.get("created_at")

        if any(p in msg for p in _MSG_CONCLUIDA):
            status_map[chave] = "concluida"
            if ts is not None:
                concluida_ts[chave] = ts
        elif any(p in msg for p in _MSG_NAO_ATENDIDA):
            if status_map.get(chave) != "concluida":
                status_map[chave] = "tentar_novamente"
        elif any(p in msg for p in _MSG_PRE_LIGACAO):
            if status_map.get(chave) != "concluida":
                status_map[chave] = "ligacao_pendente"
        else:
            if chave not in status_map:
                status_map[chave] = "mensagem"

    now_utc = datetime.now(_tz.utc)
    concluida_dias = {}
    for phone, ts in concluida_ts.items():
        try:
            concluida_dias[phone] = max((now_utc - ts).days, 0)
        except Exception:
            pass

    st.session_state["_msg_status"]         = status_map
    st.session_state["_msg_concluida_dias"] = concluida_dias


def load_metricas_from_bq():
    """A cada 5 min na tela Atividades — só hoje, por atendente."""
    import re

    def _norm(phone: str) -> str:
        p = re.sub(r'\D', '', phone or '')
        if p.startswith('55') and len(p) > 11:
            p = p[2:]
        return (p[:2] + p[-8:]) if len(p) >= 10 else p

    _INSTANCIA_NOME = {"priscila": "Priscila Oliveira", "adriely": "Ana Carolina"}
    _zero = {"mensagens": 0, "ligacoes": 0, "atendidas": 0}
    st.session_state.setdefault("_n8n_hoje", {
        "total": {**_zero}, "Priscila Oliveira": {**_zero}, "Ana Carolina": {**_zero},
    })

    client = get_bq_client()
    if not client:
        return

    _BRT    = timezone(timedelta(hours=-3))
    hoje_ts = datetime.now(_BRT).date().strftime("%Y-%m-%d")

    try:
        df = client.query(f"""
            SELECT telefone, message, instancia
            FROM `{_N8N_TABLE}`
            WHERE DATE(created_at, "America/Sao_Paulo") = "{hoje_ts}"
        """).to_dataframe()
    except Exception:
        return

    msgs_hoje  = {"total": set(), "Priscila Oliveira": set(), "Ana Carolina": set()}
    lig_hoje   = {"total": 0, "Priscila Oliveira": 0, "Ana Carolina": 0}
    atend_hoje = {"total": 0, "Priscila Oliveira": 0, "Ana Carolina": 0}

    for _, row in df.iterrows():
        chave = _norm(str(row.get("telefone") or ""))
        if not chave:
            continue
        msg      = str(row.get("message") or "").lower()
        inst_raw = str(row.get("instancia") or "").strip().lower()
        atend    = _INSTANCIA_NOME.get(inst_raw, "total_only")

        msgs_hoje["total"].add(chave)
        if atend in msgs_hoje:
            msgs_hoje[atend].add(chave)
        if any(p in msg for p in _MSG_PRE_LIGACAO):
            lig_hoje["total"] += 1
            if atend in lig_hoje:
                lig_hoje[atend] += 1
        if any(p in msg for p in _MSG_CONCLUIDA):
            atend_hoje["total"] += 1
            if atend in atend_hoje:
                atend_hoje[atend] += 1

    st.session_state["_n8n_hoje"] = {
        "total":             {"mensagens": len(msgs_hoje["total"]),             "ligacoes": lig_hoje["total"],             "atendidas": atend_hoje["total"]},
        "Priscila Oliveira": {"mensagens": len(msgs_hoje["Priscila Oliveira"]), "ligacoes": lig_hoje["Priscila Oliveira"], "atendidas": atend_hoje["Priscila Oliveira"]},
        "Ana Carolina":      {"mensagens": len(msgs_hoje["Ana Carolina"]),      "ligacoes": lig_hoje["Ana Carolina"],      "atendidas": atend_hoje["Ana Carolina"]},
    }


def save_hist_to_bq(uid: str, cid: str, data: dict):
    """Persiste uma entrada do historico no BQ (append; leitura sempre pega a mais recente)."""
    client = get_bq_client()
    if not client:
        return
    rows = [{
        "uid":            uid,
        "cliente_id":     cid,
        "historico_json": json.dumps(data, ensure_ascii=False),
        "updated_at":     datetime.now(timezone.utc).isoformat(),
    }]
    try:
        client.insert_rows_json(_HIST_TABLE, rows)
    except Exception:
        pass


# ── Processamento ─────────────────────────────────────────────────────────────

def processar_dados_bigquery():
    fetch_cobrancas_competencia.clear()
    fetch_cobrancas_liquidacao.clear()
    fetch_proximas_cobracas.clear()
    fetch_historico_meses_bulk.clear()
    store          = get_store()
    df_competencia = fetch_cobrancas_competencia()
    df_liquidacao  = fetch_cobrancas_liquidacao()
    df_hist_meses  = fetch_historico_meses_bulk()
    hist_meses = {}
    if not df_hist_meses.empty:
        for _, row in df_hist_meses.iterrows():
            hist_meses[str(row["id_sacado_sac"])] = int(row["meses_em_atraso"])

    if df_competencia.empty:
        return [], 0

    clientes_dict = {}

    for _, row in df_competencia.iterrows():
        codigo = str(row["codigo"])

        try:
            venc_raw = row["vencimento"]
            if pd.notna(venc_raw) and venc_raw:
                vencimento = datetime.strptime(str(venc_raw)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
            else:
                vencimento = ""
        except Exception:
            vencimento = ""

        dias_atraso = calc_dias(vencimento) if vencimento else None

        if codigo in clientes_dict:
            id_receb = str(row.get("id_recebimento") or "")
            ids_vistos = clientes_dict[codigo]["_ids_recebimento"]
            if id_receb and id_receb not in ids_vistos:
                ids_vistos.add(id_receb)
                cobranca_item = {
                    "id_recebimento": id_receb,
                    "valor":          float(row["valor"])   if pd.notna(row["valor"])   else 0.0,
                    "vencimento":     vencimento,
                    "dias_atraso":    dias_atraso,
                    "status":         str(row["status"] or ""),
                }
                clientes_dict[codigo]["_cobracas"].append(cobranca_item)
                if dias_atraso and dias_atraso > 0:
                    clientes_dict[codigo]["valor"] += float(row["valor"]) if pd.notna(row["valor"]) else 0.0
                    atual_min = clientes_dict[codigo].get("_min_atraso")
                    if atual_min is None or dias_atraso < atual_min:
                        clientes_dict[codigo]["_min_atraso"] = dias_atraso
            if row.get("tem_acordo"):
                clientes_dict[codigo]["_tem_acordo"] = True

            if dias_atraso and (
                clientes_dict[codigo]["dias_atraso"] is None
                or dias_atraso > clientes_dict[codigo]["dias_atraso"]
            ):
                clientes_dict[codigo]["dias_atraso"] = dias_atraso
                clientes_dict[codigo]["vencimento"]  = vencimento
        else:
            dias_atraso_num = dias_atraso if (dias_atraso and dias_atraso > 0) else None
            valor_devedor   = float(row["valor"]) if pd.notna(row["valor"]) and dias_atraso and dias_atraso > 0 else 0.0

            id_receb = str(row.get("id_recebimento") or "")
            clientes_dict[codigo] = {
                "id":               codigo,
                "cod":              codigo,
                "nome":             str(row["nome"]     or ""),
                "cnpj":             str(row["cnpj"]     or ""),
                "telefone":         fmt_tel(row["telefone"]),
                "valor":            valor_devedor,
                "vencimento":       vencimento,
                "dias_atraso":      dias_atraso_num,
                "parcelas":         int(row["parcelas"]) if pd.notna(row["parcelas"]) else 0,
                "_min_atraso":      dias_atraso_num,
                "_novo":            False,
                "_atualizado":      False,
                "_grupo":           str(row.get("grupo", "") or "—"),
                "_tem_acordo":      bool(row.get("tem_acordo", False)),
                "_inativo":         bool(row.get("inativo", False)),
                "_ids_recebimento": {id_receb} if id_receb else set(),
                "_cobracas":        [{
                    "id_recebimento": id_receb,
                    "valor":          float(row["valor"])  if pd.notna(row["valor"])  else 0.0,
                    "vencimento":     vencimento,
                    "dias_atraso":    dias_atraso,
                    "status":         str(row["status"] or ""),
                }],
            }

    for c in clientes_dict.values():
        oldest = c.get("dias_atraso") or 0
        newest = c.get("_min_atraso") or 0
        c["parcelas"] = len([x for x in c["_cobracas"] if x.get("dias_atraso") and x["dias_atraso"] > 0])
        c["_nova_cobranca"] = (c["parcelas"] > 1 and 0 < newest <= 30)
        c["_meses_atraso"] = hist_meses.get(c["id"], 0)
        c.pop("_ids_recebimento", None)

    clientes = [c for c in clientes_dict.values() if c["valor"] > 0]

    historico_regularizados = []
    for _, row in df_liquidacao.iterrows():
        try:
            liq_raw  = row["data_liquidacao"]
            data_liq = datetime.strptime(str(liq_raw)[:10], "%Y-%m-%d").strftime("%d/%m/%Y") if pd.notna(liq_raw) and liq_raw else date.today().strftime("%d/%m/%Y")
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
            "inativo":   bool(row.get("inativo", False)),
        })

    store["clientes"]           = clientes
    store["regularizados"]      = historico_regularizados
    store["ultima_atualizacao"] = datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M")
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
    store["ultima_atualizacao"] = datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M")
    return clientes, sum(c["_novo"] for c in clientes), sum(c["_atualizado"] for c in clientes), len(removidos)


def calcular_score(cliente, hist) -> int:
    score = 0

    # Receita total / 100
    score += float(cliente.get("valor", 0)) / 100

    # +1 por dia de atraso (maior atraso do cliente)
    dias_atraso = cliente.get("dias_atraso") or 0
    score += dias_atraso

    # +15 por receita acima de 15 dias (cumulativo)
    cobracas = [c for c in cliente.get("_cobracas", []) if (c.get("dias_atraso") or 0) > 0]
    if cobracas:
        score += sum(15 for c in cobracas if int(c.get("dias_atraso") or 0) > 15)
    elif dias_atraso > 15:
        score += 15

    # Acordo pendente → flat +20
    if cliente.get("_tem_acordo"):
        score += 20

    # +50 por receita adicional
    parcelas = int(cliente.get("parcelas") or 1)
    if parcelas > 1:
        score += (parcelas - 1) * 50

    # +2 por dia sem contato (desde o último contato ou, se nunca contatado, desde o vencimento)
    lc = hist.get("lastContact")
    if lc:
        try:
            dt = datetime.strptime(lc, "%d/%m/%Y").date()
            score += (date.today() - dt).days * 2
        except Exception:
            pass
    elif dias_atraso > 0:
        score += dias_atraso * 2

    return int(score)


def _dias_sem_contato(hist) -> int | None:
    """Retorna dias desde o último contato registrado, ou None se nunca contatado."""
    lc = hist.get("lastContact")
    if not lc:
        return None
    try:
        dt = datetime.strptime(lc, "%d/%m/%Y").date()
        return (date.today() - dt).days
    except Exception:
        return None


def recomendar_acao(cliente, hist) -> list[str]:
    cobracas = [c for c in cliente.get("_cobracas", []) if (c.get("dias_atraso") or 0) > 0]
    if cobracas:
        dias = min(int(c.get("dias_atraso") or 0) for c in cobracas)
    else:
        dias = cliente.get("dias_atraso") or 0

    if cliente.get("_tem_acordo") and dias >= 7:
        return ["ligar", "mensagem", "urgente"]

    dsc = _dias_sem_contato(hist)  # None = nunca contatado

    # Regra proativa: vencida 15-25 dias e sem contato há 3+ dias → ligar + mensagem
    if 15 <= dias <= 25 and (dsc is None or dsc >= 3):
        return ["ligar", "mensagem"]

    acoes = []
    if dias >= 7:
        # Não ligar se houve ligação bem-sucedida há menos de 2 dias
        from helpers import get_msg_concluida_dias
        dias_lig = get_msg_concluida_dias(cliente.get("telefone", ""))
        if dias_lig is None or dias_lig >= 2:
            acoes.append("ligar")
    if dias >= 5:
        acoes.append("mensagem")
    return acoes


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
                "historico":          store.get("historico", {}),
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
        store["historico"]          = data.get("historico",          {})
        return True
    except Exception:
        return False
