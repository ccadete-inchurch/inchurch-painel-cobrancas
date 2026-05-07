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
from helpers import calc_dias, parse_date_br, get_col, get_hist, fmt_tel, hoje_lote


# ── BigQuery ──────────────────────────────────────────────────────────────────

_BQ_PROJECT    = "business-intelligence-467516"
_BQ_DATASET    = "inadimplencia_painel_cobrancas"
_HIST_TABLE    = f"{_BQ_PROJECT}.{_BQ_DATASET}.painel_historico"
_TAREFAS_TABLE = f"{_BQ_PROJECT}.{_BQ_DATASET}.painel_tarefas_diarias"

_EMAIL_GRUPO = {
    "priscila.oliveira@inchurch.com.br":    "Priscila Oliveira",
    "anacarolina.silveira@inchurch.com.br": "Ana Carolina",
}

_MSG_CONCLUIDA    = ("além da ligação",)
_MSG_NAO_ATENDIDA = ("não estava disponível",)
_MSG_PRE_LIGACAO  = ("vou te ligar em instantes",)

# ── Lote diário: caps de inativos (únicos hard caps) + alvo ──────────────────
# Ligação = urgente OU ligar. Mensagem = só mensagem.
# Caps duros: no máximo 10 inativos em ligação e 15 inativos em mensagem.
# Totais 30/50 são apenas referência das metas diárias — ativos preenchem o lote
# livremente até atingir _LOTE_TARGET=80.
_LOTE_TARGET       = 80
_LOTE_META_LIG     = 30
_LOTE_META_MSG     = 50
_LOTE_MAX_INAT_LIG = 10
_LOTE_MAX_INAT_MSG = 15


@st.cache_resource
def get_pg_n8n_conn():
    """Conexão direta ao Postgres do N8N. Substitui o BQ Data Transfer (atrasado 30min)."""
    try:
        import psycopg2
    except ImportError:
        st.error("psycopg2 não instalado — rode `pip install psycopg2-binary`")
        return None
    if "n8n_postgres" not in st.secrets:
        st.warning("Configuração [n8n_postgres] ausente em secrets.toml")
        return None
    s = st.secrets["n8n_postgres"]
    sslmode = s.get("sslmode", "require")
    last_err = None
    for mode in (sslmode, "prefer", "disable"):
        try:
            conn = psycopg2.connect(
                host=s["host"], port=int(s.get("port", 5432)),
                dbname=s["database"], user=s["user"], password=s["password"],
                sslmode=mode, connect_timeout=10,
                application_name="painel-inadimplencia",
            )
            conn.set_session(readonly=True, autocommit=True)
            return conn
        except Exception as e:
            last_err = e
    st.error(f"Falha ao conectar Postgres N8N: {last_err}")
    return None


def _pg_table_ref():
    s = st.secrets.get("n8n_postgres", {})
    schema = s.get("schema", "public")
    table = s.get("table", "n8nfinchatbot_historico_atendente")
    return f'"{schema}"."{table}"'


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
    # Agrupa por (sacado, recebimento) para somar todos os itens de uma mesma cobrança.
    # Sem este GROUP BY, múltiplos itens do mesmo id_recebimento geram linhas duplicadas
    # e o Python descartava os menores, resultando em valores incorretos.
    query = """
    SELECT
        c.id_sacado_sac                                                   AS codigo,
        c.id_recebimento_recb                                             AS id_recebimento,
        MAX(c.st_nome_sac)                                                AS nome,
        MAX(c.st_cgc_sac)                                                 AS cnpj,
        MAX(COALESCE(NULLIF(cli.st_fax_sac, ''), c.st_telefone_sac))     AS telefone,
        SUM(c.comp_valor)                                                 AS valor,
        FORMAT_TIMESTAMP('%Y-%m-%d', MAX(c.dt_vencimento_recb))          AS vencimento,
        MAX(c.fl_status_recb)                                             AS status,
        MAX(u.nm_grupo)                                                   AS grupo,
        MAX(p.parcelas_em_atraso)                                         AS parcelas,
        MAX(CASE WHEN ac.id_sacado_sac IS NOT NULL THEN TRUE ELSE FALSE END) AS tem_acordo,
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
    LEFT JOIN (
        SELECT id_sacado_sac, COUNT(DISTINCT id_recebimento_recb) AS parcelas_em_atraso
        FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
        WHERE fl_status_recb = '0'
        GROUP BY id_sacado_sac
    ) p ON c.id_sacado_sac = p.id_sacado_sac
    LEFT JOIN (
        -- Cliente só conta como "acordo" se tem cobrança categoria 1.2.13
        -- VENCIDA (dt_vencimento <= hoje). Cobranças de acordo a vencer
        -- não disparam a regra "acordo vencido há 7d".
        SELECT DISTINCT id_sacado_sac
        FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
        WHERE comp_st_conta_cont = '1.2.13'
          AND fl_status_recb = '0'
          AND dt_vencimento_recb <= CURRENT_TIMESTAMP()
    ) ac ON c.id_sacado_sac = ac.id_sacado_sac
    WHERE c.fl_status_recb = '0'
    GROUP BY c.id_sacado_sac, c.id_recebimento_recb
    ORDER BY SUM(c.comp_valor) DESC
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
    """Lê histórico N8N direto do Postgres em historico_msgs (conversa completa).
    Mantém o nome 'from_bq' por compat. Filtra fromme='true' pra pegar só msgs
    do bot/atendente — quando o bot manda "vou te ligar em instantes" + "Obrigado,
    além da ligação", AMBAS são gravadas, e o sistema marca lig_atendida=TRUE.
    Popula _msg_status (últimos 3d), _msg_concluida_dias e _msg_ultimo_contato_dias.
    """
    import re

    def _norm(phone: str) -> str:
        p = re.sub(r'\D', '', phone or '')
        if p.startswith('55') and len(p) > 11:
            p = p[2:]
        return (p[:2] + p[-8:]) if len(p) >= 10 else p

    st.session_state.setdefault("_msg_status", {})
    st.session_state.setdefault("_msg_concluida_dias", {})
    st.session_state.setdefault("_msg_ultimo_contato_dias", {})

    conn = get_pg_n8n_conn()
    if not conn:
        return

    table = _pg_table_ref()
    cur = conn.cursor()

    # Janela de 3 dias. fromme=true ignora respostas do cliente (saudações etc).
    try:
        cur.execute(f"""
            SELECT telefone, message, created_at
            FROM {table}
            WHERE created_at >= NOW() - INTERVAL '3 days'
              AND LOWER(fromme::text) = 'true'
            ORDER BY created_at ASC
        """)
        rows = cur.fetchall()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        st.warning(f"Falha ao ler N8N (3d): {e}")
        cur.close()
        return

    status_map        = {}
    concluida_ts      = {}
    ultimo_contato_ts = {}

    for tel_raw, msg_raw, ts in rows:
        chave = _norm(str(tel_raw or ""))
        if not chave:
            continue
        msg = str(msg_raw or "").lower()
        if ts is not None:
            ultimo_contato_ts[chave] = ts

        # historico_msgs tem TODAS as mensagens — "atendida" sobrescreve
        # "ligacao_pendente" quando vem depois (mesma conversa).
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

    _BRT_TZ     = timezone(timedelta(hours=-3))
    hoje_brt_dt = datetime.now(_BRT_TZ).date()

    def _dias_calendario_brt(ts):
        try:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return max((hoje_brt_dt - ts.astimezone(_BRT_TZ).date()).days, 0)
        except Exception:
            return None

    concluida_dias      = {}
    ultimo_contato_dias = {}
    for phone, ts in concluida_ts.items():
        d = _dias_calendario_brt(ts)
        if d is not None:
            concluida_dias[phone] = d
    for phone, ts in ultimo_contato_ts.items():
        d = _dias_calendario_brt(ts)
        if d is not None:
            ultimo_contato_dias[phone] = d

    # Último contato histórico completo (MAX por telefone, sem janela)
    try:
        cur.execute(f"""
            SELECT telefone, MAX(created_at) AS ultimo_contato
            FROM {table}
            WHERE LOWER(fromme::text) = 'true'
            GROUP BY telefone
        """)
        for tel_raw, ts in cur.fetchall():
            chave = _norm(str(tel_raw or ""))
            if not chave or ts is None:
                continue
            dias = _dias_calendario_brt(ts)
            if dias is not None and (chave not in ultimo_contato_dias or dias < ultimo_contato_dias[chave]):
                ultimo_contato_dias[chave] = dias
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

    cur.close()

    st.session_state["_msg_status"]              = status_map
    st.session_state["_msg_concluida_dias"]      = concluida_dias
    st.session_state["_msg_ultimo_contato_dias"] = ultimo_contato_dias


def load_cooldowns_from_painel():
    """Carrega cooldowns por id_sacado_sac via painel_tarefas_diarias.
    Fonte de verdade pra geração do lote (substitui cooldown N8N).
    Janela: 5 dias (cobre ligação 5d e mensagem 3d).
    Salva no session_state:
      _painel_dias_msg[id]            → dias desde dt_mensagem_enviada (None se nunca)
      _painel_dias_lig[id]            → dias desde dt_ligacao_atendida — cooldown 5d só conta atendida
      _painel_dias_lig_tentada[id]    → dias desde dt_ligacao_feita — qualquer tentativa (badge)
      _painel_acoes_hoje[id]          → {"msg": bool, "lig": bool, "atend": bool} do dia atual
    """
    st.session_state.setdefault("_painel_dias_msg", {})
    st.session_state.setdefault("_painel_dias_lig", {})
    st.session_state.setdefault("_painel_dias_lig_tentada", {})
    st.session_state.setdefault("_painel_acoes_hoje", {})

    client = get_bq_client()
    if not client:
        return

    hoje = hoje_lote()
    _BRT = timezone(timedelta(hours=-3))
    hoje_brt_dt = datetime.now(_BRT).date()

    def _dias(ts):
        if ts is None or pd.isna(ts):
            return None
        try:
            return max((hoje_brt_dt - ts.astimezone(_BRT).date()).days, 0)
        except Exception:
            return None

    try:
        df = client.query(f"""
            SELECT id_sacado_sac,
                   MAX(dt_mensagem_enviada) AS dt_msg,
                   MAX(dt_ligacao_atendida) AS dt_lig_atend,
                   MAX(dt_ligacao_feita)    AS dt_lig_tent
            FROM `{_TAREFAS_TABLE}`
            WHERE data_tarefa >= DATE_SUB(CURRENT_DATE("America/Sao_Paulo"), INTERVAL 6 DAY)
            GROUP BY id_sacado_sac
        """).to_dataframe()
    except Exception:
        return

    dias_msg = {}
    dias_lig = {}          # cooldown — só ligação ATENDIDA conta
    dias_lig_tentada = {}  # tentativa de ligação (atendida OU não) — informativo, badge
    for _, row in df.iterrows():
        cid = str(row["id_sacado_sac"])
        d_msg       = _dias(row.get("dt_msg"))
        d_lig       = _dias(row.get("dt_lig_atend"))
        d_lig_tent  = _dias(row.get("dt_lig_tent"))
        if d_msg is not None:
            dias_msg[cid] = d_msg
        if d_lig is not None:
            dias_lig[cid] = d_lig
        if d_lig_tent is not None:
            dias_lig_tentada[cid] = d_lig_tent

    # Bools do dia atual (pra status visual no kanban)
    try:
        df_hoje = client.query(f"""
            SELECT id_sacado_sac, mensagem_enviada, ligacao_feita, ligacao_atendida
            FROM `{_TAREFAS_TABLE}`
            WHERE data_tarefa = '{hoje}'
        """).to_dataframe()
    except Exception:
        df_hoje = pd.DataFrame()

    acoes_hoje = {}
    for _, row in df_hoje.iterrows():
        cid = str(row["id_sacado_sac"])
        acoes_hoje[cid] = {
            "msg":   bool(row.get("mensagem_enviada")),
            "lig":   bool(row.get("ligacao_feita")),
            "atend": bool(row.get("ligacao_atendida")),
        }

    st.session_state["_painel_dias_msg"]         = dias_msg
    st.session_state["_painel_dias_lig"]         = dias_lig
    st.session_state["_painel_dias_lig_tentada"] = dias_lig_tentada
    st.session_state["_painel_acoes_hoje"]       = acoes_hoje


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


# ── Tarefas diárias ───────────────────────────────────────────────────────────

def _classificar_lote(cliente):
    """Classifica cliente para o lote diário.
    Retorna (bucket, eh_inativo) onde bucket é 'ligacao' (urgente/ligar) ou 'mensagem'.
    Retorna None se o cliente não tem ações elegíveis (cooldown já tratado em recomendar_acao).
    """
    acoes = recomendar_acao(cliente)
    if not acoes:
        return None
    eh_ligacao = "urgente" in acoes or "ligar" in acoes
    return ("ligacao" if eh_ligacao else "mensagem", bool(cliente.get("_inativo")))


def _quota_atual_lote(lote_clientes):
    """Conta quotas usadas pelo lote atual: (lig, msg, inat_lig, inat_msg)."""
    lig = msg = inat_lig = inat_msg = 0
    for c in lote_clientes:
        cls = _classificar_lote(c)
        if cls is None:
            continue
        bucket, eh_inativo = cls
        if bucket == "ligacao":
            lig += 1
            if eh_inativo:
                inat_lig += 1
        else:
            msg += 1
            if eh_inativo:
                inat_msg += 1
    return lig, msg, inat_lig, inat_msg


def _selecionar_top_30_50(clientes: list, lote_atual_ids: set | None = None) -> list:
    """Seleção de lote com ranking por score + fallback por inativos aleatórios.
    
    FASE 1: Seleção por Score (com limites de inativos)
      • Top 30 elegíveis pra LIG por score (limite máx 10 inativos)
      • Top 50 elegíveis pra MSG por score (limite máx 15 inativos, excluindo LIG)
      • Para se atingir o teto da categoria (pode ser < 30 ou < 50 se pool seco)
    
    FASE 2: Fallback Aleatório de Inativos (SEM limites)
      • Se LIG < 30: sorteia inativos aleatórios até completar 30
      • Se MSG < 50: sorteia inativos aleatórios até completar 50
      • Objetivo: garantir 80 total = 30 LIG + 50 MSG
    
    Retorna lista de (id, bucket).
    """
    import random
    
    lote_atual_ids = lote_atual_ids or set()
    
    # ─────────────────────────────────────────────────────────────────
    # FASE 1: Seleção por Score com Limites de Inativos
    # ─────────────────────────────────────────────────────────────────
    
    # Constrói lista com (score, cid, cliente_dict)
    cands_all = []
    for c in clientes:
        if c["id"] in lote_atual_ids:
            continue
        score = calcular_score(c, get_hist(c["id"]))
        cands_all.append((score, c["id"], c))
    
    # Ordena por score (decrescente)
    cands_all.sort(reverse=True, key=lambda x: x[0])
    
    novos = []
    inat_lig = 0
    inat_msg = 0
    ids_lig = set()
    ids_msg = set()
    
    # Top 30 LIG: pega elegíveis com limite 10 inativos
    for score, cid, c in cands_all:
        if len(ids_lig) >= _LOTE_META_LIG:
            break
        
        # Verifica elegibilidade para LIG
        acoes = recomendar_acao(c)
        if not ("ligar" in acoes or "urgente" in acoes):
            continue
        
        # Verifica limite de inativos
        eh_inativo = bool(c.get("_inativo"))
        if eh_inativo and inat_lig >= _LOTE_MAX_INAT_LIG:
            continue
        
        novos.append((cid, "ligacao"))
        ids_lig.add(cid)
        if eh_inativo:
            inat_lig += 1
    
    # Top 50 MSG: pega elegíveis (excluindo LIG) com limite 15 inativos
    for score, cid, c in cands_all:
        if len(ids_msg) >= _LOTE_META_MSG:
            break
        
        # Pula se já foi selecionado em LIG (sem cruzamento)
        if cid in ids_lig:
            continue
        
        # Verifica elegibilidade para MSG
        acoes = recomendar_acao(c)
        if "mensagem" not in acoes:
            continue
        
        # Verifica limite de inativos
        eh_inativo = bool(c.get("_inativo"))
        if eh_inativo and inat_msg >= _LOTE_MAX_INAT_MSG:
            continue
        
        novos.append((cid, "mensagem"))
        ids_msg.add(cid)
        if eh_inativo:
            inat_msg += 1
    
    # ─────────────────────────────────────────────────────────────────
    # FASE 2: Fallback Aleatório (SEM limites de inativos)
    # ─────────────────────────────────────────────────────────────────
    
    ids_selecionados = ids_lig | ids_msg
    
    # Pool de inativos disponíveis (não selecionados, não no lote atual)
    inativos_disponiveis = []
    for score, cid, c in cands_all:
        if cid not in ids_selecionados and c.get("_inativo"):
            inativos_disponiveis.append(cid)
    
    # Completar LIG até 30 com inativos aleatórios
    while len(ids_lig) < _LOTE_META_LIG and inativos_disponiveis:
        idx = random.randint(0, len(inativos_disponiveis) - 1)
        cid = inativos_disponiveis.pop(idx)
        novos.append((cid, "ligacao"))
        ids_lig.add(cid)
        ids_selecionados.add(cid)
    
    # Completar MSG até 50 com inativos aleatórios
    while len(ids_msg) < _LOTE_META_MSG and inativos_disponiveis:
        idx = random.randint(0, len(inativos_disponiveis) - 1)
        cid = inativos_disponiveis.pop(idx)
        novos.append((cid, "mensagem"))
        ids_msg.add(cid)
        ids_selecionados.add(cid)
    
    return novos


def _quota_buckets_para(clientes_no_lote: list) -> dict:
    """Reclassifica clientes JÁ comprometidos no lote (leitura).
    Aplica top 30 LIG + top 50 MSG sobre o conjunto comprometido.
    Caps inativos (10/15) são teto absoluto; sem cruzamento entre buckets.
    Cliente sem elegibilidade alguma fica de fora do dict — atividades.py o
    interpreta como 'aguardar/sem ação' (raro: só clientes em cooldown total).
    """
    pares = _selecionar_top_30_50(clientes_no_lote, lote_atual_ids=set())
    return {cid: bucket for cid, bucket in pares}


def selecionar_lote_com_quotas(grupo_clientes, lote_clientes=None):
    """Geração do lote do dia. Retorna lista [(id, bucket)].
    
    FASE 1: Top 30 LIG + Top 50 MSG (com limites de inativos)
      • Ordena por score
      • Top 30 elegíveis para LIG (máx 10 inativos)
      • Top 50 elegíveis para MSG, excluindo LIG (máx 15 inativos)
    
    FASE 2: Fallback Aleatório (sem limites de inativos)
      • Se LIG < 30: completa com inativos aleatórios
      • Se MSG < 50: completa com inativos aleatórios
      • Objetivo: garantir 80 total = 30 LIG + 50 MSG
    """
    lote_clientes = lote_clientes or []
    ids_no_lote = {c["id"] for c in lote_clientes}
    return _selecionar_top_30_50(grupo_clientes, lote_atual_ids=ids_no_lote)


def gerar_tarefas_do_dia(clientes, email_logado: str) -> dict:
    """Retorna {id: bucket} do lote do dia ('ligacao' | 'mensagem').
    Gera e persiste no BQ se ainda não existe lote para hoje.
    Bucket guia tanto a coluna inicial do kanban quanto o timestamp gravado no BQ.
    """
    atendente = _EMAIL_GRUPO.get(email_logado)
    if not atendente:
        # gestor vê todos — bucket fake só pra render (não usado em filtro)
        return {c["id"]: "ligacao" for c in clientes}

    client = get_bq_client()
    hoje = hoje_lote()

    # Lote já gerado hoje? Lê bucket DIRETO do BQ (autoritativo).
    # O bucket foi gravado no INSERT inicial pelo algoritmo top 30/50 — a métrica
    # do card precisa ser consistente com isso. Reclassificar em tempo de leitura
    # causa divergência (bool=lig+bucket=msg → não conta nada).
    if client:
        try:
            df = client.query(f"""
                SELECT id_sacado_sac, dt_entrou_coluna_msg, dt_entrou_coluna_ligacao
                FROM `{_TAREFAS_TABLE}`
                WHERE atendente = '{atendente}'
                  AND data_tarefa = '{hoje}'
            """).to_dataframe()
            if not df.empty:
                buckets = {}
                for _, row in df.iterrows():
                    cid = row["id_sacado_sac"]
                    buckets[cid] = "mensagem" if pd.notna(row.get("dt_entrou_coluna_msg")) else "ligacao"
                return buckets
        except Exception:
            pass

    # Geração inicial: 4 fases (30 lig + 50 msg, ≤10/15 inativos, overflow B)
    grupo_clientes = [c for c in clientes if c.get("_grupo") == atendente]
    pares = selecionar_lote_com_quotas(grupo_clientes, lote_clientes=[])
    buckets = {cid: bucket for cid, bucket in pares}

    if client and pares:
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = []
        for cid, bucket in pares:
            rows.append({
                "id_sacado_sac":            cid,
                "atendente":                atendente,
                "data_tarefa":              hoje,
                "dt_entrou_coluna_msg":     now_iso if bucket == "mensagem" else None,
                "dt_entrou_coluna_ligacao": now_iso if bucket == "ligacao"  else None,
                "mensagem_enviada":         False,
                "ligacao_feita":            False,
                "ligacao_atendida":         False,
            })
        try:
            client.insert_rows_json(_TAREFAS_TABLE, rows)
        except Exception:
            pass

    return buckets


def adicionar_tarefas_extras_bq(atendente: str, extra_ids: list, clientes: list | None = None):
    """Insere clientes extras (complemento do lote) na tabela de tarefas diárias.
    Mantida para compatibilidade — o lote do dia é estático e não usa mais este caminho."""
    client = get_bq_client()
    if not client or not extra_ids:
        return
    hoje = hoje_lote()
    cliente_by_id = {c["id"]: c for c in (clientes or [])}
    now_iso = datetime.now(timezone.utc).isoformat()
    rows = []
    for cid in extra_ids:
        c = cliente_by_id.get(cid)
        cls = _classificar_lote(c) if c else None
        bucket = cls[0] if cls else "mensagem"
        rows.append({
            "id_sacado_sac":            cid,
            "atendente":                atendente,
            "data_tarefa":              hoje,
            "dt_entrou_coluna_msg":     now_iso if bucket == "mensagem" else None,
            "dt_entrou_coluna_ligacao": now_iso if bucket == "ligacao"  else None,
            "mensagem_enviada":         False,
            "ligacao_feita":            False,
            "ligacao_atendida":         False,
        })
    try:
        client.insert_rows_json(_TAREFAS_TABLE, rows)
    except Exception:
        pass


def fetch_regularizados_do_dia(ids_lote: set) -> list:
    """Pra IDs do lote que pagaram os atrasos durante o dia (mas ainda têm cobranças
    futuras), retorna info básica + valor pago hoje + flag _regularizado_hoje=True.
    Esses clientes saem da lista normal de inadimplentes (valor em atraso = 0) mas
    devem permanecer no kanban como REGULARIZADO pra atendente não perder a meta.
    """
    if not ids_lote:
        return []
    client = get_bq_client()
    if not client:
        return []
    ids_str = ", ".join(f"'{cid}'" for cid in ids_lote)
    try:
        df = client.query(f"""
            WITH base AS (
                SELECT
                    c.id_sacado_sac AS id,
                    MAX(c.st_nome_sac) AS nome,
                    MAX(c.st_cgc_sac)  AS cnpj,
                    MAX(COALESCE(NULLIF(cli.st_fax_sac, ''), c.st_telefone_sac)) AS telefone,
                    MAX(u.nm_grupo) AS grupo,
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
                WHERE CAST(c.id_sacado_sac AS STRING) IN ({ids_str})
                GROUP BY c.id_sacado_sac
            ),
            pago_hoje AS (
                SELECT CAST(id_sacado_sac AS STRING) AS id, SUM(comp_valor) AS valor_pago
                FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
                WHERE fl_status_recb = '1'
                  AND DATE(dt_liquidacao_recb, "America/Sao_Paulo") = CURRENT_DATE("America/Sao_Paulo")
                  AND CAST(id_sacado_sac AS STRING) IN ({ids_str})
                GROUP BY id_sacado_sac
            )
            SELECT base.*, COALESCE(pago_hoje.valor_pago, 0) AS valor_pago_hoje
            FROM base LEFT JOIN pago_hoje ON CAST(base.id AS STRING) = pago_hoje.id
        """).to_dataframe()
    except Exception:
        return []

    out = []
    for _, row in df.iterrows():
        out.append({
            "id":                 str(row["id"]),
            "cod":                str(row["id"]),
            "nome":               str(row.get("nome") or ""),
            "cnpj":               str(row.get("cnpj") or ""),
            "telefone":           fmt_tel(row.get("telefone")),
            "valor":              0.0,
            "vencimento":         "",
            "dias_atraso":        0,
            "parcelas":           0,
            "_grupo":             str(row.get("grupo") or "—"),
            "_tem_acordo":        False,
            "_inativo":           bool(row.get("inativo", False)),
            "_cobracas":          [],
            "_regularizado_hoje": True,
            "_valor_pago_hoje":   float(row.get("valor_pago_hoje") or 0),
        })
    return out


def get_lote_buckets_bq(atendente: str, clientes: list) -> dict:
    """Retorna {id: bucket} do lote do dia consultando o BQ — bucket DIRETO do BQ
    (autoritativo, gravado na geração inicial). Não reclassifica em tempo de
    leitura pra evitar divergência com os bools (msg=T num cliente que viraria
    bucket=lig na reclassificação não contaria em lugar nenhum).
    """
    client = get_bq_client()
    if not client:
        return {}
    hoje = hoje_lote()
    try:
        df = client.query(f"""
            SELECT id_sacado_sac, dt_entrou_coluna_msg, dt_entrou_coluna_ligacao
            FROM `{_TAREFAS_TABLE}`
            WHERE atendente = '{atendente}'
              AND data_tarefa = '{hoje}'
        """).to_dataframe()
        if df.empty:
            return {}
        buckets = {}
        for _, row in df.iterrows():
            cid = row["id_sacado_sac"]
            buckets[cid] = "mensagem" if pd.notna(row.get("dt_entrou_coluna_msg")) else "ligacao"
        return buckets
    except Exception:
        return {}


def atualizar_tarefas_bq(atendente: str, status_map: dict, clientes: list):
    """Atualiza bools na tabela de tarefas com base no status n8n do dia.
    Usa um único MERGE em vez de 80 UPDATEs individuais.
    """
    client = get_bq_client()
    if not client:
        return
    hoje = hoje_lote()

    import re
    def _norm(phone):
        p = re.sub(r'\D', '', phone or '')
        if p.startswith('55') and len(p) > 11:
            p = p[2:]
        return (p[:2] + p[-8:]) if len(p) >= 10 else p

    # Filtra só interações de HOJE (não contamina com status do cache de 3 dias)
    ultimo_contato_dias = st.session_state.get("_msg_ultimo_contato_dias", {})
    concluida_dias      = st.session_state.get("_msg_concluida_dias", {})

    rows = []
    for c in clientes:
        tel = _norm(c.get("telefone", ""))
        if not tel:
            continue
        st_n8n = status_map.get(tel)
        if not st_n8n:
            continue

        interacao_hoje = (ultimo_contato_dias.get(tel) == 0)
        concluida_hoje = (concluida_dias.get(tel) == 0)

        # mensagem_enviada=TRUE em qualquer interação do bot (inclui pré-ligação,
        # "não estava disponível", etc). Atendente sabe que houve msg.
        # A separação entre meta-msg e meta-lig é feita na contagem do card,
        # filtrando por bucket: msg só conta bucket=mensagem.
        msg_env   = interacao_hoje
        lig_feit  = concluida_hoje or (interacao_hoje and st_n8n in ("ligacao_pendente", "tentar_novamente"))
        lig_atend = concluida_hoje

        if msg_env or lig_feit or lig_atend:
            rows.append((c["id"], msg_env, lig_feit, lig_atend))

    if not rows:
        return

    values_str = ", ".join(
        f"('{cid}', {str(me).upper()}, {str(lf).upper()}, {str(la).upper()})"
        for cid, me, lf, la in rows
    )
    try:
        client.query(f"""
            MERGE `{_TAREFAS_TABLE}` T
            USING (
                SELECT id_sacado_sac, msg_env, lig_feit, lig_atend
                FROM UNNEST(ARRAY<STRUCT<id_sacado_sac STRING, msg_env BOOL, lig_feit BOOL, lig_atend BOOL>>[
                    {values_str}
                ])
            ) S
            ON  T.id_sacado_sac = S.id_sacado_sac
            AND T.atendente     = '{atendente}'
            AND T.data_tarefa   = '{hoje}'
            WHEN MATCHED AND (
                (S.msg_env   AND NOT COALESCE(T.mensagem_enviada, FALSE)) OR
                (S.lig_feit  AND NOT COALESCE(T.ligacao_feita,    FALSE)) OR
                (S.lig_atend AND NOT COALESCE(T.ligacao_atendida, FALSE))
            ) THEN UPDATE SET
                -- bools registram QUALQUER ação real do bot, independente do bucket.
                -- Isso ativa o cooldown correto (pré-ligação ativa cooldown msg).
                -- A separação entre meta-msg e meta-lig é feita no card e no _canal,
                -- filtrando por bucket — bool ≠ conclusão da tarefa.
                mensagem_enviada    = COALESCE(T.mensagem_enviada, FALSE) OR S.msg_env,
                ligacao_feita       = COALESCE(T.ligacao_feita,    FALSE) OR S.lig_feit,
                ligacao_atendida    = COALESCE(T.ligacao_atendida, FALSE) OR S.lig_atend,
                dt_mensagem_enviada = CASE
                    WHEN S.msg_env AND NOT COALESCE(T.mensagem_enviada, FALSE)
                    THEN CURRENT_TIMESTAMP() ELSE T.dt_mensagem_enviada END,
                dt_ligacao_feita = CASE
                    WHEN S.lig_feit AND NOT COALESCE(T.ligacao_feita, FALSE)
                    THEN CURRENT_TIMESTAMP() ELSE T.dt_ligacao_feita END,
                dt_ligacao_atendida = CASE
                    WHEN S.lig_atend AND NOT COALESCE(T.ligacao_atendida, FALSE)
                    THEN CURRENT_TIMESTAMP() ELSE T.dt_ligacao_atendida END
        """)  # fire-and-forget: dt_entrou_coluna_* só é gravado no INSERT inicial
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

    # +1/dia até 90d, +0.5/dia até 360d, 0 acima de 360d
    dias_atraso = cliente.get("dias_atraso") or 0
    if dias_atraso <= 90:
        score += dias_atraso
    elif dias_atraso <= 360:
        score += 90 + (dias_atraso - 90) * 0.5
    else:
        score += 90 + 270 * 0.5  # teto: 225 pts nessa componente

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


def _dias_sem_contato(telefone: str = "") -> int | None:
    """Retorna dias desde o último contato registrado pelo N8N."""
    from helpers import get_ultimo_contato_n8n_dias
    return get_ultimo_contato_n8n_dias(telefone) if telefone else None


def recomendar_acao(cliente) -> list[str]:
    """Retorna ações elegíveis para o cliente. Cooldown via painel_tarefas_diarias.
    Regras:
      1. Acordo vencido ≥7d + cooldown LIG OK   → ['ligar', 'urgente']
      2. Inadimplência ≥15d + sem contato ≥3d   → ['ligar']  (só ligação, sem msg)
      3. Inadimplência ≥7d + cooldown LIG OK    → 'ligar'
      4. Inadimplência ≥5d + cooldown MSG OK    → 'mensagem'

    Cooldown LIG = 5 dias desde a última ligação ATENDIDA (não conta tentativas).
    Cooldown MSG = 3 dias desde a última mensagem enviada.
    "Sem contato" = nem msg nem tentativa de ligação nos últimos 3 dias (painel).
    """
    from helpers import get_painel_dias_lig, get_painel_dias_lig_tentada, get_painel_dias_msg

    cobracas = [c for c in cliente.get("_cobracas", []) if (c.get("dias_atraso") or 0) > 0]
    if cobracas:
        dias = max(int(c.get("dias_atraso") or 0) for c in cobracas)
    else:
        dias = cliente.get("dias_atraso") or 0

    cid = cliente.get("id")
    dias_lig      = get_painel_dias_lig(cid)          # ligação atendida (cooldown 5d)
    dias_lig_tent = get_painel_dias_lig_tentada(cid)  # qualquer tentativa de lig
    dias_msg      = get_painel_dias_msg(cid)          # mensagem enviada (cooldown 3d)

    cooldown_lig_ok = dias_lig is None or dias_lig >= 5
    cooldown_msg_ok = dias_msg is None or dias_msg >= 3
    sem_contato_3d  = (
        (dias_msg is None or dias_msg >= 3)
        and (dias_lig_tent is None or dias_lig_tent >= 3)
    )

    # 1. Acordo: SEMPRE só ligação (regra do Davi).
    #    - dias < 7: nenhuma ação (espera completar 7d, regra "vencida há 7 dias")
    #    - dias ≥ 7 + cooldown LIG OK: ligação urgente
    #    - dias ≥ 7 + cooldown LIG ativo: aguarda cooldown
    if cliente.get("_tem_acordo"):
        if dias < 7:
            return []
        return ["ligar", "urgente"] if cooldown_lig_ok else []

    # 2. Inadimplência ≥15d + sem contato 3d → só ligação (não dispersar com msg)
    if dias >= 15 and sem_contato_3d and cooldown_lig_ok:
        return ["ligar"]

    # 3 e 4: regras genéricas
    acoes = []
    if dias >= 7 and cooldown_lig_ok:
        acoes.append("ligar")
    if dias >= 5 and cooldown_msg_ok:
        acoes.append("mensagem")
    return acoes


def calcular_pendencias(clientes):
    pendencias = []
    hoje       = date.today()
    for c in clientes:
        h = get_hist(c["id"])
        s = h.get("status", "pending")
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
