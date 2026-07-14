import json
import time
from datetime import datetime, date, time as _dt_time, timezone, timedelta
from pathlib import Path

# ── OAuth popup: armazenamento temporário compartilhado entre sessões ─────────
_pending_oauth: dict = {}

# ── Presença online: dict em memória compartilhado entre sessões ──────────────
# email → {"ts": timestamp_da_ultima_atividade, "nome": "Nome do Usuário"}
# Cada sessão ativa pinga a cada 30s; consideramos online quem pingou nos
# últimos 90s. Sem persistência — reinicialização do processo zera.
_online_sessions: dict = {}


def ping_online(email: str, nome: str = "") -> None:
    """Marca sessão como ativa agora. Chamado por fragment de heartbeat."""
    if email:
        _online_sessions[email] = {"ts": time.time(), "nome": nome or email}


def get_online_users(janela_s: int = 90) -> list[dict]:
    """Retorna usuários que pingaram nos últimos N segundos.
    Cada item: {email, nome, ago_s}. Ordenado por mais recente primeiro."""
    agora = time.time()
    out = [
        {"email": e, "nome": d.get("nome") or e, "ago_s": int(agora - d["ts"])}
        for e, d in _online_sessions.items()
        if (agora - d["ts"]) < janela_s
    ]
    out.sort(key=lambda x: x["ago_s"])
    return out


def precisa_processar_bq(store: dict) -> bool:
    """Decide se precisa rodar processar_dados_bigquery agora.

    Retorna True quando:
      - store['clientes'] está vazio (primeira carga)
      - ultima_atualizacao é de um dia anterior (cache de ontem)
      - ultima_atualizacao é de hoje cedo (antes das 08:00 BRT, pré-pipeline)
        E o horário atual já passou das 08:00 (pipeline já terminou)

    O check de 08:00 BRT é defensivo: pipelines normalmente terminam até as
    07:30. Se cache foi populado antes disso (ex: admin logando 4 da manhã),
    fica stale até o painel detectar via esse check e re-puxar.
    """
    if not store.get("clientes"):
        return True
    ultima_str = store.get("ultima_atualizacao") or ""
    if not ultima_str:
        return True
    try:
        ultima_dt = datetime.strptime(ultima_str, "%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return True

    _BRT = timezone(timedelta(hours=-3))
    agora = datetime.now(_BRT).replace(tzinfo=None)

    # Cache de dia anterior → sempre stale
    if ultima_dt.date() < agora.date():
        return True

    # Cache de hoje cedo (pre-08:00) — re-processa quando passar das 08:00
    if ultima_dt.date() == agora.date():
        hoje_8h = datetime.combine(agora.date(), _dt_time(8, 0))
        if ultima_dt < hoje_8h and agora >= hoje_8h:
            return True

    return False

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
import requests
import streamlit as st
from google.cloud import bigquery

from auth import get_store, current_nome
from helpers import calc_dias, parse_date_br, get_hist, fmt_tel, fmt_tel_lista, hoje_lote, hoje_brt, dias_uteis_entre


# ── Feriados nacionais ────────────────────────────────────────────────────────
# FIXOS (não dependem da Páscoa). Fallback quando BrasilAPI está fora.
# Móveis (Carnaval, Sexta-feira Santa, Corpus Christi) ficam de fora —
# preferimos gerar lote num desses dias raros a marcar dia normal como
# feriado por engano.
_FERIADOS_FIXOS_MMDD = {
    "01-01",  # Confraternização Universal
    "21-04",  # Tiradentes
    "01-05",  # Dia do Trabalho
    "07-09",  # Independência
    "12-10",  # Nossa Senhora Aparecida
    "02-11",  # Finados
    "15-11",  # Proclamação da República
    "25-12",  # Natal
}


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_feriados_ano(ano: int) -> set:
    """Set de feriados nacionais do ano (strings ISO YYYY-MM-DD).

    Primária: BrasilAPI (https://brasilapi.com.br/api/feriados/v1/{ano}).
    Fallback (timeout/erro): só feriados FIXOS. Cache TTL 24h.
    """
    try:
        r = requests.get(
            f"https://brasilapi.com.br/api/feriados/v1/{ano}",
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        return {f["date"] for f in data if "date" in f}
    except Exception:
        return {f"{ano}-{mmdd}" for mmdd in _FERIADOS_FIXOS_MMDD}


def eh_feriado(d) -> bool:
    """True se a data é feriado nacional. d: date | str ISO YYYY-MM-DD."""
    if hasattr(d, "isoformat"):
        d_str = d.isoformat()
    else:
        d_str = str(d)
    try:
        ano = int(d_str[:4])
    except (ValueError, IndexError):
        return False
    return d_str in fetch_feriados_ano(ano)


# ── Superlógica API ──────────────────────────────────────────────────────────
# Fonte real-time do Splgc (banco original). BQ é replica diária; a API permite
# consultar estado atual de clientes/cobranças/pagamentos sem defasagem.
# Docs: https://apiassinaturas.superlogica.com/

_SUPERLOGICA_BASE = "https://api.superlogica.net/v2/financeiro"


@st.cache_resource
def _superlogica_session():
    """Sessão HTTP com headers de auth do Superlógica. Cacheada como recurso
    (igual conn PG/BQ) — reusa entre requests dentro da sessão Streamlit."""
    if "superlogica" not in st.secrets:
        return None
    s = st.secrets["superlogica"]
    sess = requests.Session()
    sess.headers.update({
        "Content-Type": "application/x-www-form-urlencoded",
        "app_token":    s.get("app_token", ""),
        "access_token": s.get("access_token", ""),
    })
    return sess


def _superlogica_get(path: str, params: dict | None = None) -> tuple[int, dict | list | None, str]:
    """Helper genérico de GET na API. Retorna (status_code, json_body, error_msg).

    Centraliza tratamento de erro pra debug ficar fácil — qualquer falha (sem
    sessão, timeout, status != 200, JSON inválido) retorna mensagem clara."""
    sess = _superlogica_session()
    if sess is None:
        return 0, None, "Sessão não disponível — secrets[superlogica] ausente"
    url = f"{_SUPERLOGICA_BASE}{path}"
    try:
        r = sess.get(url, params=params or {}, timeout=15)
    except requests.RequestException as e:
        return 0, None, f"Erro de rede: {type(e).__name__}: {e}"
    try:
        body = r.json()
    except ValueError:
        return r.status_code, None, f"Resposta não-JSON: {r.text[:200]}"
    if r.status_code != 200:
        return r.status_code, body, f"HTTP {r.status_code}"
    return 200, body, ""


@st.cache_data(ttl=300, show_spinner=False)
def fetch_pagamentos_hoje_api() -> dict:
    """Delta real-time: agrega cobranças liquidadas nos últimos 3 dias via API
    Superlógica, contornando o lag entre liquidação e crédito (compensação
    bancária D+1, D+2). Pagina até esgotar (limite 200/pg).
    Cache TTL 5min — atualiza automaticamente sem precisar de refresh manual.

    Por que 3 dias e não 1: cliente paga sex, crédito chega ter/qua. Sem essa
    janela, o sistema só "vê" o pagamento quando crédito entra — atendente
    fica cobrando quem já pagou por 1-3 dias úteis.

    Retorno: {cliente_id (str): {valor_total, nome, cnpj, dt_liquidacao,
    dt_liquidacao_date (date), cobrancas_ids, foi_hoje (bool)}}.
    `foi_hoje` indica se a liquidação foi exatamente hoje (importante pra
    distinguir comportamento de UI — pago hoje mostra badge "PAGOU R$ HOJE";
    pago em dia passado fica silencioso).
    """
    from datetime import date as _date, datetime as _datetime, timezone as _tz, timedelta as _td
    from helpers import hoje_lote as _hoje_lote
    # Alinhamos 'hoje' com o ciclo operacional do lote (vira 08:15 BRT),
    # não com a meia-noite. Evita que contadores resetem às 00:00 enquanto
    # cards do lote do dia anterior ainda estão em CONCLUÍDA.
    _BRT = _tz(_td(hours=-3))
    hoje = _date.fromisoformat(_hoje_lote())
    janela_dias = 3  # cobre fim de semana + feriados curtos
    dt_inicio = hoje - _td(days=janela_dias - 1)
    dt_inicio_iso = dt_inicio.strftime("%Y-%m-%d")
    hoje_iso = hoje.strftime("%Y-%m-%d")

    agg: dict[str, dict] = {}
    pagina = 1
    while True:
        # apenasColunasPrincipais=1 omitia o id_recebimento_recb em alguns
        # casos, forçando a usar heurística por valor pra identificar qual
        # cobrança foi paga. Sem essa flag, IDs vêm consistentes e dá pra
        # matchar exato. Custo do payload extra: irrelevante (~10-15 KB).
        status, body, _ = _superlogica_get("/cobranca", {
            "filtrarpor": "liquidacao",
            "dtInicio":   dt_inicio_iso,
            "dtFim":      hoje_iso,
            "itensPorPagina": 200,
            "pagina": pagina,
        })
        if status != 200 or not isinstance(body, list) or not body:
            break
        for item in body:
            cid = str(item.get("id_sacado_sac") or "")
            if not cid:
                continue
            # Validação defensiva: filtra dt_liq dentro da janela [hoje-2d, hoje].
            # A API SL não filtra estritamente por dtInicio/dtFim — retorna
            # itens fora da janela (provavelmente por dt_recebimento_recb).
            dt_liq_str = str(item.get("dt_liquidacao_recb") or "")
            dt_liq = None
            # Tenta múltiplos formatos — SL às vezes retorna US (MM/DD/YYYY),
            # outras vezes BR (DD/MM/YYYY) ou ISO (YYYY-MM-DD). Cron de
            # 2026-06-17 marcou 0 clientes — provável que o formato mudou
            # e o parse %m/%d/%Y antigo rejeitava silenciosamente tudo.
            # Ordem: ISO (sempre não-ambíguo) → BR (SL é brasileiro) → US
            # (fallback histórico). Datas tipo "05/06/2026" são ambíguas mas
            # BR é a hipótese mais provável.
            for _fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
                try:
                    dt_liq = _datetime.strptime(dt_liq_str[:10], _fmt).date()
                    break
                except (ValueError, TypeError):
                    continue
            if dt_liq is None or dt_liq < dt_inicio or dt_liq > hoje:
                continue
            try:
                valor = float(item.get("vl_total_recb") or 0)
            except (TypeError, ValueError):
                valor = 0.0
            id_receb = str(item.get("id_recebimento_recb") or "")
            foi_hoje = (dt_liq == hoje)
            if cid in agg:
                agg[cid]["valor_total"] += valor
                if id_receb:
                    agg[cid]["cobrancas_ids"].append(id_receb)
                # Se alguma liquidação foi hoje, marca foi_hoje=True
                # (cliente que teve pagamento parcial passado + total hoje
                # deve ser tratado como pagou hoje pra fins de badge)
                if foi_hoje:
                    agg[cid]["foi_hoje"] = True
                # Guarda a data mais recente (pra exibir em store["regularizados"])
                if dt_liq > agg[cid]["dt_liquidacao_date"]:
                    agg[cid]["dt_liquidacao_date"] = dt_liq
                    agg[cid]["dt_liquidacao"] = dt_liq_str
            else:
                agg[cid] = {
                    "valor_total":        valor,
                    "nome":               str(item.get("st_nome_sac") or ""),
                    "cnpj":               str(item.get("st_cgc_sac") or ""),
                    "dt_liquidacao":      dt_liq_str,
                    "dt_liquidacao_date": dt_liq,
                    "foi_hoje":           foi_hoje,
                    "cobrancas_ids":      [id_receb] if id_receb else [],
                }
        if len(body) < 200:
            break
        pagina += 1
        if pagina > 20:  # ~4k pagamentos/dia — limite de segurança, jamais alcançado
            break
    return agg


def aplicar_pagamentos_hoje_no_store():
    """Overlay real-time no store atual a partir do delta da API Superlógica.
    Idempotente — pode ser chamado a cada render (fetch é cacheado).

    Distingue pagamento TOTAL (todas cobranças vencidas pagas → regularizado)
    de PARCIAL (algumas pagas → continua na inadimplência com valor reduzido).

    Efeitos:
      - _regularizado_hoje=True só pra quem quitou TODOS os atrasos hoje
      - _pago_parcial_hoje=True pra quem pagou só parte
      - _valor_pago_hoje sempre populado pra exibição
      - 'valor' ajustado pra refletir o saldo após pagamento parcial
      - Adiciona em store['regularizados'] TODOS os que pagaram (parcial+total)
    """
    from datetime import date as _date
    from helpers import hoje_lote as _hoje_lote

    try:
        pagamentos = fetch_pagamentos_hoje_api()
    except Exception:
        return

    if not pagamentos:
        return

    store = get_store()
    ids_pagos = set(pagamentos.keys())

    # 1) Marcar clientes que pagaram — match exato por id_recebimento.
    # Com apenasColunasPrincipais removido, a API retorna id_recebimento_recb
    # de cada pagamento. Matchamos com c["_cobracas"][i]["id_recebimento"]
    # diretamente — sem heurística, sem ambiguidade.
    for c in store["clientes"]:
        cid = str(c.get("id") or "")
        if cid not in ids_pagos:
            continue

        info = pagamentos[cid]
        foi_hoje = bool(info.get("foi_hoje"))
        c["_valor_pago_hoje"] = info["valor_total"]
        # Data da liquidação pro badge "PAGOU R$ X EM dd/mm" quando não foi hoje
        # E pra atribuir o pagamento ao dia REAL nos gráficos do Especialista
        # (em vez de "hoje" pra todos, que enviesa a barra do dia atual).
        _dt_liq_d = info.get("dt_liquidacao_date")
        if _dt_liq_d:
            c["_dt_pagamento_recente"] = _dt_liq_d.strftime("%d/%m")
            c["_dt_liquidacao_real"] = _dt_liq_d
        c["_pagamento_foi_hoje"] = foi_hoje

        if c.get("_cobracas_ajustadas"):
            continue  # já foi ajustado em invocação anterior

        # Set de IDs pagos vindo da API
        paid_ids = {str(x) for x in info.get("cobrancas_ids", []) if x}

        # Tentativa de match por ID — preciso e sem ambiguidade
        matched_any = False
        if paid_ids:
            for cob in c.get("_cobracas", []):
                cob_id = str(cob.get("id_recebimento") or "")
                if cob_id and cob_id in paid_ids:
                    # Cobrança paga — zera valor e atraso (some do filtro
                    # de vencidas em todas as telas)
                    cob["valor"] = 0
                    cob["dias_atraso"] = 0
                    matched_any = True

        if matched_any:
            # Match por ID funcionou — recalcula agregados do cliente
            vencidas_restantes = [
                cob for cob in c.get("_cobracas", [])
                if (cob.get("dias_atraso") or 0) > 0
            ]
            c["valor"] = sum(float(cob.get("valor", 0)) for cob in vencidas_restantes)
            c["dias_atraso"] = max(
                (cob.get("dias_atraso") or 0 for cob in vencidas_restantes),
                default=0,
            )
            c["parcelas"] = len(vencidas_restantes)

            # Decisão total vs parcial baseada no que SOBROU.
            # Parcial é marcado independente de foi_hoje — o badge usa
            # _pagamento_foi_hoje pra decidir entre "HOJE" e "EM dd/mm".
            if not vencidas_restantes or c["valor"] <= 0.5:
                c["_regularizado_hoje"] = True
            else:
                c["_pago_parcial_hoje"] = True
        elif paid_ids:
            # API retornou IDs mas nenhum bate com _cobracas. Significa
            # que cliente pagou uma cobrança QUE NÃO ESTÁ na lista de
            # vencidas — provavelmente uma futura antecipada (BQ filtra
            # fl_status='0', cobrança paga sai da lista).
            #
            # Caso real: Igreja Evangélica Ministério Somar pagou cobrança
            # 124395 (vence 06/07, antecipada). _cobracas só tem 122582
            # (vence 05/06, vencida). Subtrair 329,80 do saldo de 783,33
            # estaria errado — esse pagamento NÃO é parcial da vencida.
            #
            # Resultado: NÃO mexe no saldo, NÃO marca _pago_parcial_hoje.
            # O cliente continua inadimplente normalmente. O pagamento
            # ainda aparece na tela Pagamentos via _valor_pago_hoje.
            pass
        elif not c.get("_cobracas_ajustadas"):
            # FALLBACK SÓ se API não retornou IDs (caso raro). Sem IDs
            # não temos como saber qual cobrança foi paga, então assumimos
            # que foi vencida e usamos lógica antiga (compara pago vs saldo).
            saldo_vencido = sum(
                float(cob.get("valor") or 0)
                for cob in c.get("_cobracas", [])
                if (cob.get("dias_atraso") or 0) > 0
            )
            pago = float(info["valor_total"])
            quitou_tudo = pago + 0.5 >= saldo_vencido

            if quitou_tudo:
                c["_regularizado_hoje"] = True
                # Marca todas vencidas como pagas (não sabe quais, mas se
                # pago >= saldo então prática significa "pagou tudo")
                for cob in c.get("_cobracas", []):
                    if (cob.get("dias_atraso") or 0) > 0:
                        cob["valor"] = 0
                        cob["dias_atraso"] = 0
                c["valor"] = 0
                c["dias_atraso"] = 0
                c["parcelas"] = 0
            else:
                c["_pago_parcial_hoje"] = True
                # Subtrai pago do valor total (saldo aproximado)
                try:
                    saldo_antigo = float(c.get("valor") or 0)
                    c["valor"] = max(0.0, saldo_antigo - pago)
                except (TypeError, ValueError):
                    pass

        c["_cobracas_ajustadas"] = True

    # ANTES: havia uma seção "2) Adicionar a regularizados" que appendava
    # entries em store["regularizados"] pra alimentar a tela Pagamentos.
    # REMOVIDO porque causava acúmulo descontrolado via cache_dados.json
    # (sessões e dias se sobrepunham, dedup imperfeito). A tela Pagamentos
    # agora rebuilda do zero a cada render via _build_regularizados_fresh
    # em views/historico.py — BQ + overlay com dedup limpo, sem persistência.


# ── Grupo 'Não cobrar' via API Superlógica ────────────────────────────────────
# BQ (Splgc.splgc-grupo) só replica os grupos Ana/Priscila — o pipeline de
# ETL filtra por nome (grupos_desejados = ["Ana Carolina", "Priscila
# Oliveira"]) antes de carregar a tabela. O grupo id=55 'NÃO COBRAR!' nunca
# chega no BQ. Buscamos direto da API (endpoint /clientes, mesmo usado pelo
# pipeline) pra excluir esses clientes da fila de cobrança automaticamente,
# sem depender de marcação manual da atendente.
_GRUPO_ID_NAO_COBRAR = "55"


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ids_nao_cobrar_api() -> set:
    """Pagina /clientes (comDadosDoGrupo=1) e retorna o set de id_sacado_sac
    de quem está no grupo SL id=55 ('NÃO COBRAR!'). Cache 1h — grupo muda raro.
    """
    ids = set()
    pagina = 1
    while True:
        status, body, _ = _superlogica_get("/clientes", {
            "apenasColunasPrincipais": 1,
            "comDadosDoGrupo": 1,
            "status": 2,
            "itensPorPagina": 200,
            "pagina": pagina,
        })
        if status != 200 or not isinstance(body, list) or not body:
            break
        for item in body:
            for g in (item.get("sacado_grupo") or []):
                if str(g.get("id_grupo_grp")) == _GRUPO_ID_NAO_COBRAR:
                    cid = str(item.get("id_sacado_sac") or "")
                    if cid:
                        ids.add(cid)
                    break
        if len(body) < 200:
            break
        pagina += 1
        if pagina > 50:  # ~10k clientes, limite de segurança (jamais alcançado)
            break
    return ids


def aplicar_grupo_nao_cobrar_no_store():
    """Marca/desmarca c['_grupo_nao_cobrar'] nos clientes conforme presença
    atual no grupo SL 'NÃO COBRAR!', e espelha o set em session_state pra
    get_effective_status (helpers.py) enxergar sem precisar varrer
    store['clientes']. Overlay real-time — roda a cada render, fetch é
    cacheado (TTL 1h). Seta True OU False explicitamente (nunca só True):
    store['clientes'] só é reconstruído do zero 1x/dia (reprocessamento do
    BQ), então se não desmarcar aqui, um cliente que saiu do grupo ficaria
    preso como 'não cobrar' até o próximo reprocessamento, mesmo depois do
    cache da API expirar."""
    try:
        ids = fetch_ids_nao_cobrar_api()
    except Exception:
        return
    st.session_state["_grupo_nao_cobrar_ids"] = ids
    store = get_store()
    for c in store["clientes"]:
        c["_grupo_nao_cobrar"] = str(c.get("id") or "") in ids


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

# Mensagens da IA/saudação automática — não devem contar como ação real do atendente.
# Substring matching em LOWER(message). Se aparecer qualquer um desses padrões,
# a mensagem é IGNORADA pelo load/MERGE (não vira interacao_hoje, não marca bools).
_MSG_IA_IGNORAR = (
    "atendente glória",
    "oii, aqui é a priscila da inchurch. como posso te ajudar?",
    "oii, aqui é a ana carolina da inchurch. como posso te ajudar?",
)

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
    """Conexão direta ao Postgres do N8N. Substitui o BQ Data Transfer (atrasado 30min).
    Caching pelo Streamlit pode reter conexão morta após timeout do servidor —
    use _pg_n8n_conn_alive() pra garantir conn viva (faz health check e reconecta).
    """
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


def _pg_n8n_conn_alive():
    """Retorna conn PG garantidamente viva. Faz health check (SELECT 1) e, se
    a cached conn estiver morta (psycopg2.InterfaceError/OperationalError ou
    conn.closed != 0), limpa o cache e tenta reconectar uma vez.

    Use sempre que for usar a conn pra evitar 'connection already closed'
    quando Streamlit segura conn idle por muito tempo."""
    try:
        import psycopg2
    except ImportError:
        return None

    conn = get_pg_n8n_conn()
    if conn is None:
        return None

    try:
        if getattr(conn, "closed", 0) != 0:
            raise psycopg2.InterfaceError("conn closed")
        with conn.cursor() as _cur:
            _cur.execute("SELECT 1")
        return conn
    except (psycopg2.InterfaceError, psycopg2.OperationalError, AttributeError):
        try:
            get_pg_n8n_conn.clear()
        except Exception:
            pass
        return get_pg_n8n_conn()


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
        MAX(CASE WHEN c.dt_desativacao_sac IS NOT NULL THEN TRUE ELSE FALSE END) AS inativo,
        MAX(c.comp_st_conta_cont)                                         AS tipo
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` c
    LEFT JOIN (
        SELECT CAST(id_sacado_sac AS STRING) AS id_sacado_sac, MAX(grupo) AS nm_grupo
        FROM `business-intelligence-467516.Splgc.splgc-grupo`
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
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_evolucao_saldo_mensal(cliente_id: str) -> pd.DataFrame:
    """Saldo devedor ao FIM DE CADA MÊS nos últimos 12 meses.

    Reconstrói o saldo a partir das tabelas de competência + liquidação:
    pra cada fim de mês EOM, soma as cobranças do cliente que:
      - tinham vencimento <= EOM (já estavam vencidas) E
      - não tinham sido pagas até EOM (em aberto naquela data)

    Retorna DataFrame com colunas: mes (YYYY-MM), saldo (float)
    """
    client = get_bq_client()
    if not client:
        return pd.DataFrame()
    query = f"""
    WITH abertas AS (
      SELECT
        id_recebimento_recb,
        SUM(comp_valor) AS valor,
        MIN(DATE(dt_vencimento_recb)) AS dt_venc,
        CAST(NULL AS DATE) AS dt_pag
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE id_sacado_sac = '{cliente_id}' AND fl_status_recb = '0'
      GROUP BY id_recebimento_recb
    ),
    pagas AS (
      SELECT
        id_recebimento_recb,
        SUM(comp_valor) AS valor,
        MIN(DATE(dt_vencimento_recb)) AS dt_venc,
        MIN(DATE(dt_liquidacao_recb)) AS dt_pag
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
      WHERE id_sacado_sac = '{cliente_id}' AND fl_status_recb = '1'
      GROUP BY id_recebimento_recb
    ),
    todas AS (
      SELECT * FROM abertas
      UNION ALL
      SELECT * FROM pagas
    ),
    meses AS (
      SELECT LAST_DAY(DATE_SUB(CURRENT_DATE('America/Sao_Paulo'), INTERVAL n MONTH)) AS eom
      FROM UNNEST(GENERATE_ARRAY(0, 11)) AS n
    )
    SELECT
      FORMAT_DATE('%Y-%m', m.eom) AS mes,
      ROUND(COALESCE(SUM(t.valor), 0), 2) AS saldo
    FROM meses m
    LEFT JOIN todas t
      ON t.dt_venc <= m.eom
      AND (t.dt_pag IS NULL OR t.dt_pag > m.eom)
    GROUP BY mes
    ORDER BY mes ASC
    """
    try:
        return client.query(query).to_dataframe()
    except Exception:
        return pd.DataFrame()


def fetch_historico_atrasos(cliente_id: str) -> pd.DataFrame:
    client = get_bq_client()
    if not client:
        return pd.DataFrame()
    # IMPORTANTE: a tabela splgc-cobrancas_liquidacao-all tem MÚLTIPLAS linhas
    # por cobrança (uma por evento de liquidação — juros, ajustes, split de
    # pagamento). Por isso dedupe via id_recebimento_recb ANTES de contar/somar.
    # Sem isso, 1 cobrança paga em 3 eventos virava "3 pagos" na grade —
    # cliente parecia ter pago mais do que pagou de verdade.
    query = f"""
    WITH em_atraso_unique AS (
      SELECT id_recebimento_recb, dt_vencimento_recb,
             SUM(comp_valor) AS comp_valor
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE fl_status_recb = '0'
        AND id_sacado_sac = '{cliente_id}'
        AND dt_vencimento_recb <= CURRENT_TIMESTAMP()
      GROUP BY id_recebimento_recb, dt_vencimento_recb
    ),
    pago_unique AS (
      SELECT id_recebimento_recb, dt_vencimento_recb,
             SUM(comp_valor) AS comp_valor
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
      WHERE fl_status_recb = '1'
        AND id_sacado_sac = '{cliente_id}'
        AND dt_vencimento_recb >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 365 DAY)
        AND dt_vencimento_recb <= CURRENT_TIMESTAMP()
      GROUP BY id_recebimento_recb, dt_vencimento_recb
    ),
    unificado AS (
      SELECT id_recebimento_recb, dt_vencimento_recb, comp_valor, 'atraso' AS situacao FROM em_atraso_unique
      UNION ALL
      SELECT id_recebimento_recb, dt_vencimento_recb, comp_valor, 'pago' AS situacao FROM pago_unique
    )
    SELECT
      FORMAT_TIMESTAMP('%Y-%m', dt_vencimento_recb) AS mes,
      COUNTIF(situacao = 'atraso') AS parcelas_atraso,
      COUNTIF(situacao = 'pago')   AS parcelas_pagas,
      ROUND(SUM(CASE WHEN situacao = 'atraso' THEN comp_valor ELSE 0 END), 2) AS valor_atraso,
      ROUND(SUM(CASE WHEN situacao = 'pago'   THEN comp_valor ELSE 0 END), 2) AS valor_pago
    FROM unificado
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
        FROM `business-intelligence-467516.Splgc.splgc-grupo`
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


_SNAPSHOT_TABLE = f"{_BQ_PROJECT}.{_BQ_DATASET}.cobrancas_snapshot_diario"


def ensure_snapshot_table():
    """Cria a tabela de snapshot diário de inadimplentes no BQ se não existir.
    Estrutura mínima: data + id_sacado + valor + dias_atraso. Particionada por
    data_snapshot pra query barata por mês."""
    client = get_bq_client()
    if not client:
        return
    from google.cloud import bigquery
    schema = [
        bigquery.SchemaField("data_snapshot", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("id_sacado_sac", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("valor_saldo",   "FLOAT64"),
        bigquery.SchemaField("dias_atraso",   "INT64"),
        bigquery.SchemaField("inativo",       "BOOL"),
    ]
    table = bigquery.Table(_SNAPSHOT_TABLE, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY, field="data_snapshot"
    )
    try:
        client.create_table(table, exists_ok=True)
    except Exception:
        pass


def salvar_snapshot_inadimplentes_hoje(clientes: list | None = None):
    """Grava snapshot dos inadimplentes em cobrancas_snapshot_diario.

    Frequência: 1 vez por DIA. O cron roda diariamente às 08:30 BRT via
    gerar_lote_cron.py. Idempotência diária — se já tem snapshot de hoje,
    pula. Permite comparações finas (hoje vs ontem, hoje vs 7d atrás).

    O card 'Variação no Mês' continua usando só o snapshot do início do
    mês como referência. Snapshots intermediários ficam disponíveis pra
    métricas adicionais (Hoje, Semana) e auditorias futuras.

    Volume: ~700 clientes × 365 dias = ~255k linhas/ano. ~13MB/ano —
    custo desprezível no BQ."""
    client = get_bq_client()
    if not client:
        return
    if clientes is None:
        clientes = get_store().get("clientes", [])
    if not clientes:
        return

    ensure_snapshot_table()
    _BRT = timezone(timedelta(hours=-3))
    hoje = datetime.now(_BRT).date().isoformat()

    # Idempotência DIÁRIA: se já existe snapshot de HOJE, pula. Múltiplos
    # snapshots por dia seriam redundantes (cron roda 1x/dia mas a função
    # pode ser chamada por outros caminhos).
    try:
        df_check = client.query(f"""
            SELECT COUNT(*) AS cnt
            FROM `{_SNAPSHOT_TABLE}`
            WHERE data_snapshot = DATE '{hoje}'
        """).to_dataframe()
        if int(df_check["cnt"].iloc[0]) > 0:
            return
    except Exception:
        pass  # tabela acabou de ser criada — segue

    rows = [{
        "data_snapshot": hoje,
        "id_sacado_sac": str(c.get("id", "")),
        "valor_saldo":   float(c.get("valor", 0) or 0),
        "dias_atraso":   int(c.get("dias_atraso") or 0),
        "inativo":       bool(c.get("_inativo", False)),
    } for c in clientes if c.get("id")]

    try:
        client.insert_rows_json(_SNAPSHOT_TABLE, rows)
    except Exception:
        pass


def detectar_reincidentes(clientes_hoje: list) -> set:
    """Retorna IDs de clientes que estão na inadimplência HOJE mas NÃO
    estavam no snapshot mais recente disponível (últimos 7 dias).

    Por que 7 dias: cobre fim de semana + feriado + eventual falha do cron
    no(s) dia(s) anterior(es). Se não houver baseline em 7 dias, retorna
    set vazio (safety — sem comparação, não sabe quem é reincidente).
    """
    ids_hoje = {str(c["id"]) for c in clientes_hoje if c.get("id")}
    if not ids_hoje:
        return set()
    client = get_bq_client()
    if not client:
        return set()
    try:
        df = client.query(f"""
            WITH ult AS (
                SELECT data_snapshot
                FROM `{_SNAPSHOT_TABLE}`
                WHERE data_snapshot < CURRENT_DATE('America/Sao_Paulo')
                  AND data_snapshot >= DATE_SUB(
                      CURRENT_DATE('America/Sao_Paulo'), INTERVAL 7 DAY)
                ORDER BY data_snapshot DESC
                LIMIT 1
            )
            SELECT DISTINCT id_sacado_sac
            FROM `{_SNAPSHOT_TABLE}`
            WHERE data_snapshot = (SELECT data_snapshot FROM ult)
        """).to_dataframe()
    except Exception:
        return set()
    ids_anteriores = {str(x) for x in df.get("id_sacado_sac", []).tolist()} if not df.empty else set()
    if not ids_anteriores:
        return set()
    return ids_hoje - ids_anteriores


def resetar_status_reincidentes(clientes_hoje: list) -> int:
    """Reseta status/promiseDate/retorno pra clientes que voltaram à
    inadimplência. Preserva notes e lastContact (contexto histórico vale).

    Motivo: status (promessa, retorno, negociando) e datas se referem à
    dívida ANTERIOR — que foi paga. Manter polui o painel da atendente com
    info obsoleta. Notes e lastContact ficam pra atendente saber que já
    tinha trabalhado com esse cliente antes.

    Roda no cron diário antes de gerar_tarefas_do_dia. Consulta BQ direto
    (não depende do store em memória, que no cron headless não tem
    historicos carregados).

    Retorna número de historicos resetados (pra logging do cron).
    """
    voltaram = detectar_reincidentes(clientes_hoje)
    if not voltaram:
        return 0
    client = get_bq_client()
    if not client:
        return 0

    ids_str = ", ".join(f"'{cid}'" for cid in voltaram)
    try:
        df = client.query(f"""
            WITH ranked AS (
                SELECT uid, cliente_id, historico_json,
                       ROW_NUMBER() OVER (
                           PARTITION BY uid, cliente_id
                           ORDER BY updated_at DESC
                       ) AS rn
                FROM `{_HIST_TABLE}`
                WHERE cliente_id IN ({ids_str})
            )
            SELECT uid, cliente_id, historico_json
            FROM ranked WHERE rn = 1
        """).to_dataframe()
    except Exception:
        return 0

    n_resets = 0
    for _, row in df.iterrows():
        try:
            h = json.loads(row["historico_json"]) if row["historico_json"] else {}
        except (ValueError, TypeError):
            continue
        tem_sujeira = (
            (h.get("status") and h["status"] not in ("pending", ""))
            or h.get("promiseDate")
            or h.get("retorno")
        )
        if not tem_sujeira:
            continue
        h["status"] = "pending"
        h.pop("promiseDate", None)
        h.pop("retorno", None)
        try:
            save_hist_to_bq(str(row["uid"]), str(row["cliente_id"]), h)
            n_resets += 1
        except Exception:
            pass
    return n_resets


@st.cache_data(ttl=3600)
def fetch_snapshot_inicio_mes() -> set:
    """IDs dos clientes do PRIMEIRO snapshot do mês atual.
    Usado pra calcular NOVOS no mês: atuais − inicio = entraram no mês.
    """
    client = get_bq_client()
    if not client:
        return set()
    try:
        df = client.query(f"""
            WITH primeiro AS (
                SELECT MIN(data_snapshot) AS dt
                FROM `{_SNAPSHOT_TABLE}`
                WHERE data_snapshot >= DATE_TRUNC(CURRENT_DATE("America/Sao_Paulo"), MONTH)
            )
            SELECT DISTINCT s.id_sacado_sac, p.dt AS data_inicio
            FROM `{_SNAPSHOT_TABLE}` s
            CROSS JOIN primeiro p
            WHERE s.data_snapshot = p.dt
        """).to_dataframe()
        if df.empty:
            return set()
        try:
            dt = df["data_inicio"].iloc[0]
            st.session_state["_snapshot_inicio_mes_data"] = (
                dt.strftime("%d/%m/%Y") if hasattr(dt, "strftime") else str(dt)
            )
        except Exception:
            pass
        return {str(r["id_sacado_sac"]) for _, r in df.iterrows()}
    except Exception:
        return set()


@st.cache_data(ttl=3600)
def fetch_inadimplentes_uniao_mes() -> set:
    """IDs DISTINTOS de clientes que estiveram inadimplentes em ALGUM dia
    do mês atual — UNIÃO de todos os snapshots desde 01/mês até hoje.

    Usado pra calcular REGULARIZADOS no mês:
        regularizados = uniao_mes − atuais
    Captura cliente que virou inadimplente no MEIO do mês e regularizou
    (que o snapshot único do dia 01 perdia).
    """
    client = get_bq_client()
    if not client:
        return set()
    try:
        df = client.query(f"""
            SELECT DISTINCT id_sacado_sac
            FROM `{_SNAPSHOT_TABLE}`
            WHERE data_snapshot >= DATE_TRUNC(CURRENT_DATE("America/Sao_Paulo"), MONTH)
        """).to_dataframe()
        if df.empty:
            return set()
        return {str(r["id_sacado_sac"]) for _, r in df.iterrows()}
    except Exception:
        return set()


@st.cache_data(ttl=3600)
def fetch_snapshot_inicio_semana() -> set:
    """IDs do snapshot no INÍCIO DA SEMANA ATUAL (segunda-feira), com cap
    no início do mês — baseline = MAX(seg da semana, dia 1 do mês).

    Usado pra calcular NOVOS desta semana:
        novos = atuais − inicio_semana

    Cap garante que 'Esta semana' nunca cruza fronteira de mês.
    Quando dia 1 cai no meio da semana (ex: quinta 01/05), baseline é
    capada em 01/05 — 'Esta semana' fica igual a 'Mês' temporariamente.
    """
    client = get_bq_client()
    if not client:
        return set()
    try:
        df = client.query(f"""
            WITH bound AS (
                SELECT GREATEST(
                    DATE_TRUNC(CURRENT_DATE("America/Sao_Paulo"), WEEK(MONDAY)),
                    DATE_TRUNC(CURRENT_DATE("America/Sao_Paulo"), MONTH)
                ) AS dt_min
            ),
            primeiro AS (
                SELECT MIN(data_snapshot) AS dt
                FROM `{_SNAPSHOT_TABLE}`
                WHERE data_snapshot >= (SELECT dt_min FROM bound)
            )
            SELECT DISTINCT s.id_sacado_sac, p.dt AS data_ref
            FROM `{_SNAPSHOT_TABLE}` s
            CROSS JOIN primeiro p
            WHERE s.data_snapshot = p.dt
        """).to_dataframe()
        if df.empty:
            return set()
        try:
            dt = df["data_ref"].iloc[0]
            st.session_state["_snapshot_semana_data"] = (
                dt.strftime("%d/%m/%Y") if hasattr(dt, "strftime") else str(dt)
            )
        except Exception:
            pass
        return {str(r["id_sacado_sac"]) for _, r in df.iterrows()}
    except Exception:
        return set()


@st.cache_data(ttl=3600)
def fetch_inadimplentes_uniao_esta_semana() -> set:
    """IDs DISTINTOS de clientes inadimplentes em ALGUM dia desta semana
    (segunda → hoje), capada no início do mês.

    Usado pra calcular REGULARIZADOS desta semana:
        regularizados = uniao_esta_semana − atuais

    Garantia: Esta semana ⊆ Mês sempre (cap no início do mês).
    """
    client = get_bq_client()
    if not client:
        return set()
    try:
        df = client.query(f"""
            SELECT DISTINCT id_sacado_sac
            FROM `{_SNAPSHOT_TABLE}`
            WHERE data_snapshot >= GREATEST(
                DATE_TRUNC(CURRENT_DATE("America/Sao_Paulo"), WEEK(MONDAY)),
                DATE_TRUNC(CURRENT_DATE("America/Sao_Paulo"), MONTH)
            )
        """).to_dataframe()
        if df.empty:
            return set()
        return {str(r["id_sacado_sac"]) for _, r in df.iterrows()}
    except Exception:
        return set()


@st.cache_data(ttl=3600)
def fetch_snapshot_ontem() -> set:
    """IDs do snapshot MAIS RECENTE disponível antes de hoje. Usado pra
    calcular novos/regularizados comparando com a referência mais próxima.

    Estratégia atual: pega o snapshot mais recente que NÃO seja de hoje.
    Robusto a gaps (fim de semana, feriado, falha do cron).

    Trade-off aceito: na segunda compara com sexta (3 dias) em vez de
    domingo. A UI usa _snapshot_ontem_data (session_state) pra mostrar
    label dinâmico — 'Hoje' se ontem = 1 dia atrás, 'Desde DD/MM' se
    a referência for mais antiga.
    """
    client = get_bq_client()
    if not client:
        return set()
    try:
        df = client.query(f"""
            WITH ref AS (
                SELECT MAX(data_snapshot) AS dt
                FROM `{_SNAPSHOT_TABLE}`
                WHERE data_snapshot < CURRENT_DATE("America/Sao_Paulo")
            )
            SELECT DISTINCT s.id_sacado_sac, r.dt AS data_ref
            FROM `{_SNAPSHOT_TABLE}` s
            CROSS JOIN ref r
            WHERE s.data_snapshot = r.dt
        """).to_dataframe()
        if df.empty:
            return set()
        # Salva a data de referência usada — UI usa pra mostrar label dinâmico
        try:
            dt = df["data_ref"].iloc[0]
            st.session_state["_snapshot_ontem_data"] = (
                dt.strftime("%d/%m/%Y") if hasattr(dt, "strftime") else str(dt)
            )
        except Exception:
            pass
        return {str(r["id_sacado_sac"]) for _, r in df.iterrows()}
    except Exception:
        return set()


@st.cache_data(ttl=3600)
def fetch_npl_metrics(atendente: str = None, situacao: str = "todos") -> dict:
    """Métricas NPL da carteira (Non-Performing Loans), com buckets exclusivos:
    - TOTAL: % clientes com qualquer cobrança vencida (atraso >= 1 dia)
    - 30d:   % com atraso ENTRE 1 e 30 dias (bucket recente)
    - 90d:   % com atraso >= 90 dias (bucket crítico / NPL ratio)

    Buckets 30d e 90d são EXCLUSIVOS (não cumulativos). A faixa de 30-89 dias
    fica oculta entre os dois — convenção padrão de dashboards de cobrança.

    Para cada uma: % da carteira, n. clientes, R$ em aberto, delta p.p. vs 30d.

    Denominador: clientes únicos. Inclui desativados por padrão (a
    inadimplência antiga é passivo real, mesmo do cliente já saído do
    produto — sem isso, 90D+ fica zerado porque o Splgc desativa
    automaticamente atrasos longos).

    Numerador: só clientes que já pagaram pelo menos 1 boleto na história
    (`EXISTS dt_liquidacao_recb IS NOT NULL`). Exclui novos em onboarding/
    disputa comercial — esses são CS/vendas, não cobrança operacional.

    Parâmetros:
        atendente:  Nome do grupo (ex: 'Ana Carolina'). Filtra via splgc-grupo.
                    "__SEM_ESPECIALISTA__" para clientes sem grupo atribuído.
                    None para carteira global.
        situacao:   'todos' (default), 'ativos' (dt_desativacao_sac IS NULL),
                    ou 'inativos' (dt_desativacao_sac IS NOT NULL).

    Delta: mesma fórmula aplicada ao "snapshot virtual" de 30 DIAS atrás
    (cobrança estava aberta em D-30 se status='0' agora OU paga depois de D-30).
    Janela MoM (Month over Month) — padrão da indústria financeira, alinha
    com o ciclo mensal de assinatura inChurch e dá deltas mais legíveis
    (2-4 p.p. típicos vs 0-0,5 p.p. de WoW em carteiras pequenas).
    """
    client = get_bq_client()
    if not client:
        return {}

    # Usar BRT, não UTC — date.today() do servidor pode adiantar 1 dia
    # (UTC 02:00 = BRT 23:00 do dia anterior), inflando inadimplência.
    today_str = hoje_brt()
    today_dt  = date.fromisoformat(today_str)
    ref_str   = (today_dt - timedelta(days=30)).isoformat()

    # ── Filtro de atendente (via splgc-grupo) ─────────────────────────────
    contacts_cte = ""
    cond_carteira_atend = ""
    cond_cobrs_atend = ""
    if atendente == "__SEM_ESPECIALISTA__":
        contacts_cte = """contacts AS (
          SELECT DISTINCT CAST(id_sacado_sac AS STRING) AS cid
          FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
          WHERE CAST(id_sacado_sac AS STRING) NOT IN (
            SELECT DISTINCT CAST(id_sacado_sac AS STRING)
            FROM `business-intelligence-467516.Splgc.splgc-grupo`
            WHERE grupo IS NOT NULL
          )
        ),
        """
        cond_carteira_atend = "CAST(id_sacado_sac AS STRING) IN (SELECT cid FROM contacts)"
        cond_cobrs_atend = "CAST(c.id_sacado_sac AS STRING) IN (SELECT cid FROM contacts)"
    elif atendente:
        ate_safe = atendente.replace("'", "''")
        contacts_cte = f"""contacts AS (
          SELECT DISTINCT CAST(id_sacado_sac AS STRING) AS cid
          FROM `business-intelligence-467516.Splgc.splgc-grupo`
          WHERE grupo = '{ate_safe}'
        ),
        """
        cond_carteira_atend = "CAST(id_sacado_sac AS STRING) IN (SELECT cid FROM contacts)"
        cond_cobrs_atend = "CAST(c.id_sacado_sac AS STRING) IN (SELECT cid FROM contacts)"

    # ── Filtro de situação (dt_desativacao_sac) ───────────────────────────
    cond_carteira_sit = ""
    cond_cobrs_sit = ""
    if situacao == "ativos":
        cond_carteira_sit = "dt_desativacao_sac IS NULL"
        cond_cobrs_sit = "c.dt_desativacao_sac IS NULL"
    elif situacao == "inativos":
        cond_carteira_sit = "dt_desativacao_sac IS NOT NULL"
        cond_cobrs_sit = "c.dt_desativacao_sac IS NOT NULL"

    # ── Combina condições em WHERE ────────────────────────────────────────
    # Filtro de tipo: só Setup (1.2.1) + Mensalidade (1.2.2). Alinhamento
    # com a metodologia "por receita" do outro dashboard. SQL level apenas.
    cond_carteira_tipo = "comp_st_conta_cont IN ('1.2.1', '1.2.2')"
    cond_cobrs_tipo    = "c.comp_st_conta_cont IN ('1.2.1', '1.2.2')"

    # Filtro #4 no DENOMINADOR (carteira): exclui onboarding. Quem nunca
    # pagou nao e' inadimplente — e' cliente novo / disputa. Sem isso, o
    # % saia subestimado (denom inflado por onboarding).
    cond_carteira_jp = (
        "CAST(id_sacado_sac AS STRING) "
        "IN (SELECT cid FROM clientes_com_pagamento)"
    )

    conds_c = [c for c in [cond_carteira_atend, cond_carteira_sit, cond_carteira_tipo, cond_carteira_jp] if c]
    conds_b = [c for c in [cond_cobrs_atend,    cond_cobrs_sit,    cond_cobrs_tipo]    if c]
    carteira_filter = "WHERE " + " AND ".join(conds_c) if conds_c else ""
    cobrs_filter    = "WHERE " + " AND ".join(conds_b) if conds_b else ""

    query = f"""
    WITH {contacts_cte}
    -- Clientes que já pagaram pelo menos 1 boleto na história — exclui
    -- novos em onboarding / disputa comercial sem pagamento prévio.
    -- Inadimplência "operacional": só conta quem já pagou antes e agora
    -- parou. Cliente novo com primeiro boleto vencido NÃO é inadimplência
    -- da régua de cobrança, é onboarding/CS.
    clientes_com_pagamento AS (
      SELECT DISTINCT CAST(id_sacado_sac AS STRING) AS cid
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
      WHERE dt_liquidacao_recb IS NOT NULL
    ),
    -- Denominador: exclui onboarding (clientes que nunca pagaram).
    -- Razão: quem nunca pagou não pode ser considerado inadimplente — é
    -- cliente novo / disputa comercial, escopo de CS, não da cobrança.
    -- Sem essa exclusão, o numerador (que tem ja_pagou=1) e o denominador
    -- (que incluía todos) divergiam — % saía subestimada.
    -- Filtro de ja_pagou ja vem dentro do {carteira_filter}.
    carteira AS (
      SELECT COUNT(DISTINCT id_sacado_sac) AS n
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      {carteira_filter}
    ),
    cobrs AS (
      SELECT
        c.id_sacado_sac                  AS cid,
        c.id_recebimento_recb            AS rid,
        DATE(MAX(c.dt_vencimento_recb))  AS venc,
        SUM(c.comp_valor)                AS valor,
        MAX(c.fl_status_recb)            AS status,
        DATE(MAX(l.dt_liquidacao_recb))  AS liq,
        MAX(IF(jp.cid IS NOT NULL, 1, 0)) AS ja_pagou
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` c
      LEFT JOIN `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all` l
        ON c.id_recebimento_recb = l.id_recebimento_recb
      LEFT JOIN clientes_com_pagamento jp
        ON CAST(c.id_sacado_sac AS STRING) = jp.cid
      {cobrs_filter}
      GROUP BY c.id_sacado_sac, c.id_recebimento_recb
    ),
    hoje AS (
      SELECT
        COUNT(DISTINCT IF(status = '0' AND venc < DATE('{today_str}') AND ja_pagou = 1, cid, NULL)) AS total_n,
        COUNT(DISTINCT IF(status = '0' AND DATE_DIFF(DATE('{today_str}'), venc, DAY) BETWEEN 1 AND 30 AND ja_pagou = 1, cid, NULL)) AS d30_n,
        COUNT(DISTINCT IF(status = '0' AND DATE_DIFF(DATE('{today_str}'), venc, DAY) >= 90 AND ja_pagou = 1, cid, NULL)) AS d90_n,
        SUM(IF(status = '0' AND venc < DATE('{today_str}') AND ja_pagou = 1, valor, 0)) AS total_r,
        SUM(IF(status = '0' AND DATE_DIFF(DATE('{today_str}'), venc, DAY) BETWEEN 1 AND 30 AND ja_pagou = 1, valor, 0)) AS d30_r,
        SUM(IF(status = '0' AND DATE_DIFF(DATE('{today_str}'), venc, DAY) >= 90 AND ja_pagou = 1, valor, 0)) AS d90_r
      FROM cobrs
    ),
    ref AS (
      SELECT
        COUNT(DISTINCT IF(venc < DATE('{ref_str}') AND (status = '0' OR liq >= DATE('{ref_str}')) AND ja_pagou = 1, cid, NULL)) AS total_n,
        COUNT(DISTINCT IF(DATE_DIFF(DATE('{ref_str}'), venc, DAY) BETWEEN 1 AND 30 AND (status = '0' OR liq >= DATE('{ref_str}')) AND ja_pagou = 1, cid, NULL)) AS d30_n,
        COUNT(DISTINCT IF(DATE_DIFF(DATE('{ref_str}'), venc, DAY) >= 90 AND (status = '0' OR liq >= DATE('{ref_str}')) AND ja_pagou = 1, cid, NULL)) AS d90_n
      FROM cobrs
    )
    SELECT
      c.n AS carteira,
      h.total_n, h.d30_n, h.d90_n,
      h.total_r, h.d30_r, h.d90_r,
      r.total_n AS r_total_n, r.d30_n AS r_d30_n, r.d90_n AS r_d90_n
    FROM carteira c, hoje h, ref r
    """
    try:
        df = client.query(query).to_dataframe()
    except Exception:
        return {}
    if df.empty:
        return {}

    r = df.iloc[0]
    carteira = int(r["carteira"]) or 1
    return {
        "carteira": carteira,
        # Hoje (BQ snapshot — pode estar 1 dia atrasado, replicação 04:00 BRT).
        # Pra valores "live" (overlay aplicado), usar compute_npl_today_overlay
        # em atividades.py e sobrescrever total_n/d30_n/d90_n/total_r/d30_r/d90_r.
        "total_pct":   float(r["total_n"]) / carteira * 100,
        "total_n":     int(r["total_n"]),
        "total_r":     float(r["total_r"] or 0),
        "d30_pct":     float(r["d30_n"]) / carteira * 100,
        "d30_n":       int(r["d30_n"]),
        "d30_r":       float(r["d30_r"] or 0),
        "d90_pct":     float(r["d90_n"]) / carteira * 100,
        "d90_n":       int(r["d90_n"]),
        "d90_r":       float(r["d90_r"] or 0),
        # D-30 reference (sempre BQ — 30 dias atrás já tem todas liquidações
        # replicadas). Não precisa de overlay aqui.
        "r_total_n":   int(r["r_total_n"]),
        "r_d30_n":     int(r["r_d30_n"]),
        "r_d90_n":     int(r["r_d90_n"]),
        # Delta MoM com base no BQ snapshot. Caso queira "delta live", recalcule
        # em atividades.py usando (overlay.total_n - r_total_n) / carteira.
        "delta_total": (float(r["total_n"]) - float(r["r_total_n"])) / carteira * 100,
        "delta_d30":   (float(r["d30_n"])   - float(r["r_d30_n"]))   / carteira * 100,
        "delta_d90":   (float(r["d90_n"])   - float(r["r_d90_n"]))   / carteira * 100,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_carteira_count(atendente: str = None, situacao: str = "todos") -> int:
    """Total de clientes da carteira SEM filtro de tipo (1.2.1/1.2.2).

    Usado pelo card 'X CLIENTES' do indicador — diferente de _npl['carteira']
    que aplica filtro Setup+Mensalidade. Aqui contamos TODOS os clientes do
    atendente, refletindo o universo que aparece no kanban/painel (qualquer
    tipo de cobrança).

    Args:
        atendente: nome do grupo (ex: 'Ana Carolina'), '__SEM_ESPECIALISTA__'
                   ou None (todos)
        situacao: 'todos' (default), 'ativos' (dt_desativ NULL) ou 'inativos'

    Returns:
        int: contagem de id_sacado_sac únicos
    """
    client = get_bq_client()
    if not client:
        return 0

    # Filtro de atendente via splgc-grupo
    if atendente == "__SEM_ESPECIALISTA__":
        atend_filter = """
        WHERE CAST(id_sacado_sac AS STRING) NOT IN (
          SELECT DISTINCT CAST(id_sacado_sac AS STRING)
          FROM `business-intelligence-467516.Splgc.splgc-grupo`
          WHERE grupo IS NOT NULL
        )
        """
    elif atendente:
        ate_safe = atendente.replace("'", "''")
        atend_filter = f"""
        WHERE CAST(id_sacado_sac AS STRING) IN (
          SELECT DISTINCT CAST(id_sacado_sac AS STRING)
          FROM `business-intelligence-467516.Splgc.splgc-grupo`
          WHERE grupo = '{ate_safe}'
        )
        """
    else:
        atend_filter = ""

    # Filtro de situação
    sit_cond = ""
    if situacao == "ativos":
        sit_cond = "dt_desativacao_sac IS NULL"
    elif situacao == "inativos":
        sit_cond = "dt_desativacao_sac IS NOT NULL"

    if sit_cond:
        atend_filter = (
            f"{atend_filter} AND {sit_cond}" if atend_filter
            else f"WHERE {sit_cond}"
        )

    query = f"""
    SELECT COUNT(DISTINCT id_sacado_sac) AS n
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
    {atend_filter}
    """
    try:
        df = client.query(query).to_dataframe()
        if df.empty:
            return 0
        return int(df.iloc[0]["n"])
    except Exception:
        return 0


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_clientes_com_pagamento_set() -> frozenset:
    """Set frozenset de cids (string) que já pagaram pelo menos 1 boleto.
    Usado pelo filtro #4 do NPL — exclui clientes em onboarding sem pagamento prévio.

    Retorna frozenset (em vez de set) pra ser hashable, importante pro
    @st.cache_data não dar erro de serialização.
    """
    client = get_bq_client()
    if not client:
        return frozenset()
    try:
        df = client.query("""
            SELECT DISTINCT CAST(id_sacado_sac AS STRING) AS cid
            FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
            WHERE dt_liquidacao_recb IS NOT NULL
        """).to_dataframe()
        return frozenset(str(row["cid"]) for _, row in df.iterrows())
    except Exception:
        return frozenset()


def compute_npl_today_overlay(
    clientes_full: list,
    atendente: str = None,
    situacao: str = "todos",
    ja_pagou_set: frozenset = None,
) -> dict:
    """Computa métricas NPL de HOJE a partir de store['clientes'] (overlay aplicado).

    Por que existe: fetch_npl_metrics consulta BQ direto, que tem replicação
    diária às 04:00 BRT. Entre BQ sync e agora, pagamentos confirmados na API
    Superlógica não estão no BQ ainda — o overlay (em aplicar_pagamentos_hoje_no_store)
    marca esses clientes com _regularizado_hoje=True. Esta função usa essa
    informação pra dar contagens "live" em vez do snapshot BQ stale.

    Aplicação:
        - Pula clientes com _regularizado_hoje=True (já pagou TODOS atrasos)
        - Mantém clientes com _pago_parcial_hoje=True (ainda tem cobrança vencida)
        - Soma R$ apenas das cobranças com dias_atraso > 0 (vencidas mesmo)

    Buckets (aging exclusivo):
        - d30: cobranças com atraso BETWEEN 1 AND 30 dias
        - d90: cobranças com atraso >= 90 dias
        - faixa 31-89 fica oculta (não tem card próprio)

    Args:
        clientes_full:  store['clientes'] já com overlay aplicado
        atendente:      nome do grupo (ex: 'Ana Carolina'), '__SEM_ESPECIALISTA__'
                        ou None (todos)
        situacao:       'todos', 'ativos' (_inativo=False) ou 'inativos'
        ja_pagou_set:   frozenset de cids com pagamento prévio (filtro #4).
                        Se None, não aplica filtro #4.

    Returns:
        dict {total_n, d30_n, d90_n, total_r, d30_r, d90_r}
        Contagens são de CLIENTES distintos por bucket (cliente pode estar em
        múltiplos buckets se tiver cobranças em faixas diferentes).
        Valores R$ são soma das cobranças por bucket.
    """
    # ── Filtro de atendente ────────────────────────────────────────────────
    if atendente == "__SEM_ESPECIALISTA__":
        filtered = [
            c for c in clientes_full
            if not c.get("_grupo") or str(c.get("_grupo")) in ("—", "", "nan", "NaN")
        ]
    elif atendente:
        filtered = [c for c in clientes_full if c.get("_grupo") == atendente]
    else:
        filtered = list(clientes_full)

    # ── Filtro de situação (ativos/inativos) ───────────────────────────────
    if situacao == "ativos":
        filtered = [c for c in filtered if not c.get("_inativo")]
    elif situacao == "inativos":
        filtered = [c for c in filtered if c.get("_inativo")]

    # ── Filtro #4: cliente já pagou alguma vez ─────────────────────────────
    if ja_pagou_set is not None:
        filtered = [c for c in filtered if str(c.get("id") or "") in ja_pagou_set]

    # ── Overlay: pula clientes que pagaram tudo nos últimos 3 dias ─────────
    filtered = [c for c in filtered if not c.get("_regularizado_hoje")]

    # ── Agrega buckets ─────────────────────────────────────────────────────
    total_n = d30_n = d90_n = 0
    total_r = d30_r = d90_r = 0.0

    # Tipos válidos pra alinhar com SQL: só Setup (1.2.1) + Mensalidade (1.2.2).
    # PERMISSIVO: se a cobrança não tem tipo populado (cache stale do store
    # carregado antes do deploy desta feature), inclui mesmo assim. Quando
    # store recarregar com tipo (TTL 1h), filtro fica estrito.
    _TIPOS_VALIDOS = {"1.2.1", "1.2.2"}

    def _tipo_ok(cob):
        t = str(cob.get("tipo") or "")
        return (not t) or (t in _TIPOS_VALIDOS)

    for c in filtered:
        cobr_vencidas = [
            cob for cob in (c.get("_cobracas") or [])
            if (cob.get("dias_atraso") or 0) > 0
            and float(cob.get("valor") or 0) > 0
            and _tipo_ok(cob)
        ]
        if not cobr_vencidas:
            continue

        total_n += 1
        has_1_30 = has_90 = False

        for cob in cobr_vencidas:
            dias = cob.get("dias_atraso") or 0
            valor = float(cob.get("valor") or 0)
            total_r += valor
            if 1 <= dias <= 30:
                d30_r += valor
                has_1_30 = True
            if dias >= 90:
                d90_r += valor
                has_90 = True

        if has_1_30:
            d30_n += 1
        if has_90:
            d90_n += 1

    return {
        "total_n": total_n,
        "d30_n":   d30_n,
        "d90_n":   d90_n,
        "total_r": total_r,
        "d30_r":   d30_r,
        "d90_r":   d90_r,
    }


@st.cache_data(ttl=3600)
def fetch_npl_rolling(atendente: str = None, situacao: str = "todos") -> dict:
    """Métricas NPL "por receita" — % por R$ com janela rolante.

    Espelha 100% a metodologia da Página 4 do outro dashboard:
    - Janela rolante:
        - Total: boletos vencidos em [D-365, D] (12 meses TTM)
        - 30d:   boletos vencidos em [D-30, D]
        - 90d:   boletos vencidos em [D-90, D]
    - % por R$: % = R$ aberto / R$ emitido × 100

    Critério "em aberto em data D" (NÃO usa fl_status_recb):
        dt_liquidacao_recb IS NULL OR dt_liquidacao_recb > D

    Filtros padrão (sempre aplicados):
    - Tipo: comp_st_conta_cont IN ('1.2.1', '1.2.2') — Setup + Mensalidade
    - Onboarding: EXISTS dt_liquidacao_recb IS NOT NULL (já pagou ≥1)
    - Desativação por DATA DO VENCIMENTO:
        dt_desativacao_sac IS NULL OR dt_desativacao_sac > venc
      → cliente conta se estava ATIVO no momento em que cada boleto venceu.
        Diferente do filtro global de situacao=ativos (que olha status HOJE),
        esse respeita a história — cliente ativo em D-90 mas desativado em
        D-30 ainda gera inadimplência no bucket 90d.

    Filtros adicionais opcionais:
    - atendente: via splgc-grupo (Todos / Ana / Priscila / __SEM_ESPECIALISTA__)
    - situacao: filtro de status ATUAL aplicado por cima da metodologia padrão
        - "todos" (default): comportamento da Página 4 puro
        - "ativos": apenas clientes ativos HOJE
        - "inativos": apenas clientes inativos HOJE

    Delta MoM: mesma métrica em D-30. Janelas no D-30:
        Total ref: [D-395, D-30]
        30d ref:   [D-60, D-30]
        90d ref:   [D-120, D-30]

    NÃO usa overlay live — só BQ snapshot. Lag de ~1 dia tem impacto < 5%
    em janelas de 30/90/365 dias.

    Returns dict com:
        total_pct, total_aberto, total_emitido, delta_total_pp
        d30_pct, d30_aberto, d30_emitido, delta_d30_pp
        d90_pct, d90_aberto, d90_emitido, delta_d90_pp
    """
    client = get_bq_client()
    if not client:
        return {}

    today_str = hoje_brt()
    today_dt = date.fromisoformat(today_str)

    # ── Filtro de atendente ────────────────────────────────────────────────
    contacts_cte = ""
    cond_atend = ""
    if atendente == "__SEM_ESPECIALISTA__":
        contacts_cte = """contacts AS (
          SELECT DISTINCT CAST(id_sacado_sac AS STRING) AS cid
          FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
          WHERE CAST(id_sacado_sac AS STRING) NOT IN (
            SELECT DISTINCT CAST(id_sacado_sac AS STRING)
            FROM `business-intelligence-467516.Splgc.splgc-grupo`
            WHERE grupo IS NOT NULL
          )
        ),
        """
        cond_atend = "CAST(c.id_sacado_sac AS STRING) IN (SELECT cid FROM contacts)"
    elif atendente:
        ate_safe = atendente.replace("'", "''")
        contacts_cte = f"""contacts AS (
          SELECT DISTINCT CAST(id_sacado_sac AS STRING) AS cid
          FROM `business-intelligence-467516.Splgc.splgc-grupo`
          WHERE grupo = '{ate_safe}'
        ),
        """
        cond_atend = "CAST(c.id_sacado_sac AS STRING) IN (SELECT cid FROM contacts)"

    # ── Filtro de situação ─────────────────────────────────────────────────
    cond_sit = ""
    if situacao == "ativos":
        cond_sit = "c.dt_desativacao_sac IS NULL"
    elif situacao == "inativos":
        cond_sit = "c.dt_desativacao_sac IS NOT NULL"

    # ── Filtro de tipo (Setup/Mensalidade) ─────────────────────────────────
    # Filtro #4 (ja pagou) agora e' aplicado no CTE 'boletos' apos a agregacao,
    # nao mais aqui (era 'jp.cid IS NOT NULL', mas jp nao existe em boletos_agg).
    cond_tipo = "c.comp_st_conta_cont IN ('1.2.1', '1.2.2')"

    # Combina as condições aplicáveis em boletos_agg (sem referência a jp.cid)
    conds = [c for c in [cond_atend, cond_sit, cond_tipo] if c]
    where_clause = "WHERE " + " AND ".join(conds) if conds else ""

    # Espelhar 100% a metodologia da Pagina 4:
    # 1) 'Aberto' usa puro dt_liquidacao_recb IS NULL OR > D
    #    (NAO usa fl_status_recb, que reflete estado atual e nao historico)
    # 2) Filtro de desativacao por DATA DO VENCIMENTO de cada boleto:
    #    dt_desativacao_sac IS NULL OR dt_desativacao_sac > venc
    # 3) AGREGAR liquidacao ANTES do JOIN pra evitar fan-out:
    #    A tabela liquidacao-all tem ~4.3 linhas por boleto (pagamentos
    #    parciais, refundos, etc). Fazer LEFT JOIN direto inflava o SUM
    #    de comp_valor em 4-5x, gerando denominador errado e % falsa.
    #    Mesma logica pra cobrancas_competencia-all (~3 linhas/boleto):
    #    cada linha e' uma rubrica (Setup, Mensalidade, modulos).
    #    Agregamos cada uma 1x antes de juntar.
    query = f"""
    WITH {contacts_cte}
    clientes_com_pagamento AS (
      SELECT DISTINCT CAST(id_sacado_sac AS STRING) AS cid
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
      WHERE dt_liquidacao_recb IS NOT NULL
    ),
    liquidacao_agg AS (
      SELECT
        id_recebimento_recb,
        MAX(DATE(dt_liquidacao_recb)) AS liq
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
      WHERE dt_liquidacao_recb IS NOT NULL
      GROUP BY id_recebimento_recb
    ),
    boletos_agg AS (
      SELECT
        CAST(c.id_sacado_sac AS STRING) AS cid,
        c.id_recebimento_recb AS rid,
        DATE(MAX(c.dt_vencimento_recb)) AS venc,
        DATE(MAX(c.dt_desativacao_sac)) AS desat,
        SUM(c.comp_valor) AS valor
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` c
      {where_clause}
      GROUP BY c.id_sacado_sac, c.id_recebimento_recb
    ),
    boletos AS (
      SELECT
        b.cid, b.rid, b.venc, b.desat, b.valor,
        la.liq
      FROM boletos_agg b
      LEFT JOIN liquidacao_agg la ON b.rid = la.id_recebimento_recb
      LEFT JOIN clientes_com_pagamento jp ON b.cid = jp.cid
      WHERE jp.cid IS NOT NULL
    )
    SELECT
      -- HOJE: Total TTM (12 meses) — boletos vencidos em [D-365, D]
      SUM(IF(venc BETWEEN DATE_SUB(DATE('{today_str}'), INTERVAL 365 DAY) AND DATE('{today_str}')
             AND (desat IS NULL OR desat > venc), valor, 0)) AS total_emitido_hoje,
      SUM(IF(venc BETWEEN DATE_SUB(DATE('{today_str}'), INTERVAL 365 DAY) AND DATE('{today_str}')
             AND (desat IS NULL OR desat > venc)
             AND (liq IS NULL OR liq > DATE('{today_str}')), valor, 0)) AS total_aberto_hoje,

      -- HOJE: 30d — boletos vencidos em [D-30, D]
      SUM(IF(venc BETWEEN DATE_SUB(DATE('{today_str}'), INTERVAL 30 DAY) AND DATE('{today_str}')
             AND (desat IS NULL OR desat > venc), valor, 0)) AS d30_emitido_hoje,
      SUM(IF(venc BETWEEN DATE_SUB(DATE('{today_str}'), INTERVAL 30 DAY) AND DATE('{today_str}')
             AND (desat IS NULL OR desat > venc)
             AND (liq IS NULL OR liq > DATE('{today_str}')), valor, 0)) AS d30_aberto_hoje,

      -- HOJE: 90d — boletos vencidos em [D-90, D]
      SUM(IF(venc BETWEEN DATE_SUB(DATE('{today_str}'), INTERVAL 90 DAY) AND DATE('{today_str}')
             AND (desat IS NULL OR desat > venc), valor, 0)) AS d90_emitido_hoje,
      SUM(IF(venc BETWEEN DATE_SUB(DATE('{today_str}'), INTERVAL 90 DAY) AND DATE('{today_str}')
             AND (desat IS NULL OR desat > venc)
             AND (liq IS NULL OR liq > DATE('{today_str}')), valor, 0)) AS d90_aberto_hoje,

      -- D-30 REF: Total TTM [D-395, D-30]
      SUM(IF(venc BETWEEN DATE_SUB(DATE('{today_str}'), INTERVAL 395 DAY) AND DATE_SUB(DATE('{today_str}'), INTERVAL 30 DAY)
             AND (desat IS NULL OR desat > venc), valor, 0)) AS total_emitido_ref,
      SUM(IF(venc BETWEEN DATE_SUB(DATE('{today_str}'), INTERVAL 395 DAY) AND DATE_SUB(DATE('{today_str}'), INTERVAL 30 DAY)
             AND (desat IS NULL OR desat > venc)
             AND (liq IS NULL OR liq > DATE_SUB(DATE('{today_str}'), INTERVAL 30 DAY)), valor, 0)) AS total_aberto_ref,

      -- D-30 REF: 30d [D-60, D-30]
      SUM(IF(venc BETWEEN DATE_SUB(DATE('{today_str}'), INTERVAL 60 DAY) AND DATE_SUB(DATE('{today_str}'), INTERVAL 30 DAY)
             AND (desat IS NULL OR desat > venc), valor, 0)) AS d30_emitido_ref,
      SUM(IF(venc BETWEEN DATE_SUB(DATE('{today_str}'), INTERVAL 60 DAY) AND DATE_SUB(DATE('{today_str}'), INTERVAL 30 DAY)
             AND (desat IS NULL OR desat > venc)
             AND (liq IS NULL OR liq > DATE_SUB(DATE('{today_str}'), INTERVAL 30 DAY)), valor, 0)) AS d30_aberto_ref,

      -- D-30 REF: 90d [D-120, D-30]
      SUM(IF(venc BETWEEN DATE_SUB(DATE('{today_str}'), INTERVAL 120 DAY) AND DATE_SUB(DATE('{today_str}'), INTERVAL 30 DAY)
             AND (desat IS NULL OR desat > venc), valor, 0)) AS d90_emitido_ref,
      SUM(IF(venc BETWEEN DATE_SUB(DATE('{today_str}'), INTERVAL 120 DAY) AND DATE_SUB(DATE('{today_str}'), INTERVAL 30 DAY)
             AND (desat IS NULL OR desat > venc)
             AND (liq IS NULL OR liq > DATE_SUB(DATE('{today_str}'), INTERVAL 30 DAY)), valor, 0)) AS d90_aberto_ref
    FROM boletos
    """
    try:
        df = client.query(query).to_dataframe()
    except Exception:
        return {}
    if df.empty:
        return {}

    r = df.iloc[0]

    def _pct(aberto, emitido):
        if not emitido or emitido == 0:
            return 0.0
        return float(aberto) / float(emitido) * 100

    total_pct_hoje = _pct(r["total_aberto_hoje"], r["total_emitido_hoje"])
    d30_pct_hoje   = _pct(r["d30_aberto_hoje"],   r["d30_emitido_hoje"])
    d90_pct_hoje   = _pct(r["d90_aberto_hoje"],   r["d90_emitido_hoje"])
    total_pct_ref  = _pct(r["total_aberto_ref"],  r["total_emitido_ref"])
    d30_pct_ref    = _pct(r["d30_aberto_ref"],    r["d30_emitido_ref"])
    d90_pct_ref    = _pct(r["d90_aberto_ref"],    r["d90_emitido_ref"])

    return {
        # Total (12 meses TTM)
        "total_pct":        total_pct_hoje,
        "total_aberto":     float(r["total_aberto_hoje"] or 0),
        "total_emitido":    float(r["total_emitido_hoje"] or 0),
        "delta_total_pp":   total_pct_hoje - total_pct_ref,
        # 30d (janela rolante)
        "d30_pct":          d30_pct_hoje,
        "d30_aberto":       float(r["d30_aberto_hoje"] or 0),
        "d30_emitido":      float(r["d30_emitido_hoje"] or 0),
        "delta_d30_pp":     d30_pct_hoje - d30_pct_ref,
        # 90d (janela rolante)
        "d90_pct":          d90_pct_hoje,
        "d90_aberto":       float(r["d90_aberto_hoje"] or 0),
        "d90_emitido":      float(r["d90_emitido_hoje"] or 0),
        "delta_d90_pp":     d90_pct_hoje - d90_pct_ref,
    }


@st.cache_data(ttl=3600)
def fetch_regularizados_mes_atual() -> set:
    """IDs distintos de clientes que pagaram pelo menos uma cobrança EM ATRASO
    no mês atual. Filtra dt_liquidacao_recb > dt_vencimento_recb pra capturar
    só os que estavam de fato em inadimplência quando quitaram.

    Usado pelo card 'Variação no Mês' do dashboard — evita contar pagamentos
    regulares (no prazo) como 'regularização'.
    """
    client = get_bq_client()
    if not client:
        return set()
    try:
        df = client.query("""
            SELECT DISTINCT id_sacado_sac
            FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
            WHERE fl_status_recb = '1'
              AND DATE(dt_liquidacao_recb) >= DATE_TRUNC(CURRENT_DATE("America/Sao_Paulo"), MONTH)
              AND dt_liquidacao_recb <= CURRENT_TIMESTAMP()
              AND dt_liquidacao_recb > dt_vencimento_recb
        """).to_dataframe()
        return {str(row["id_sacado_sac"]) for _, row in df.iterrows()}
    except Exception:
        return set()


@st.cache_data(ttl=1800)
def fetch_eficacia_por_especialista(dt_inicio_iso: str, dt_fim_iso: str) -> pd.DataFrame:
    """Eficácia REAL de contato por especialista no período.

    Eficácia REAL = clientes_contactados_que_pagaram_no_período /
                    clientes_contactados_no_período

    Antes a fórmula usava o snapshot atual ('cliente NÃO está mais
    inadimplente hoje') no numerador, o que misturava janelas: o
    denominador era do período, o numerador era 'até hoje'. Pra
    'Mês atual' funcionava por coincidência (período termina hoje),
    mas pra qualquer período histórico (mês anterior, últimos 30 dias,
    etc.) inflava com pagamentos feitos DEPOIS do fim do período.

    Agora ambos respeitam a janela do filtro: 'contactados no período E
    pagaram em atraso no período'. Comparação entre meses fica honesta
    — cada mês fecha com sua eficácia.

    Denominador (total de contactados) inclui clientes que nem pagaram —
    reflete o esforço real, não só o que converteu.
    """
    client = get_bq_client()
    if not client:
        return pd.DataFrame()
    try:
        df = client.query(f"""
            WITH contatos_periodo AS (
                -- Clientes contactados no período. Usa PRIMEIRO contato pra
                -- saber a data a partir de qual pagamento conta como conversão.
                SELECT
                    CAST(id_sacado_sac AS STRING) AS cid,
                    atendente,
                    MIN(data_tarefa) AS primeiro_contato
                FROM `{_TAREFAS_TABLE}`
                WHERE data_tarefa >= DATE('{dt_inicio_iso}')
                  AND data_tarefa <= DATE('{dt_fim_iso}')
                  AND (
                      mensagem_enviada = TRUE
                      OR ligacao_feita = TRUE
                      OR ligacao_atendida = TRUE
                  )
                GROUP BY cid, atendente
            ),
            pagamentos_apos_contato AS (
                -- Cliente que pagou EM ATRASO no período E o pagamento foi
                -- DEPOIS do primeiro contato (causalidade temporal).
                -- Sem essa condição, pagamentos antigos (antes do contato)
                -- contavam como conversão — inflavam eficácia em períodos
                -- longos onde contatos começaram recentemente.
                SELECT DISTINCT CAST(p.id_sacado_sac AS STRING) AS cid
                FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all` p
                JOIN contatos_periodo c
                  ON CAST(p.id_sacado_sac AS STRING) = c.cid
                WHERE p.fl_status_recb = '1'
                  AND p.dt_liquidacao_recb > p.dt_vencimento_recb
                  AND DATE(p.dt_liquidacao_recb) >= DATE('{dt_inicio_iso}')
                  AND DATE(p.dt_liquidacao_recb) <= DATE('{dt_fim_iso}')
                  AND DATE(p.dt_liquidacao_recb) >= c.primeiro_contato
            )
            SELECT
                c.atendente,
                COUNT(DISTINCT c.cid) AS clientes_contactados,
                COUNT(DISTINCT IF(p.cid IS NOT NULL, c.cid, NULL)) AS regularizaram,
                COUNT(DISTINCT IF(p.cid IS NULL, c.cid, NULL)) AS ainda_inadimplentes
            FROM contatos_periodo c
            LEFT JOIN pagamentos_apos_contato p ON p.cid = c.cid
            GROUP BY c.atendente
        """).to_dataframe()
        if df.empty:
            return df
        df["eficacia_real"] = (
            df["regularizaram"] / df["clientes_contactados"].replace(0, pd.NA) * 100
        ).fillna(0).round(0).astype(int)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=1800)
def fetch_eventos_regularizacao() -> set:
    """Retorna set de (id_sacado_sac, data_dd_mm_aaaa) — eventos de
    REGULARIZAÇÃO detectados via analise direta de liquidações.

    Critério per-pagamento: para cada pagamento em atraso (cid, data_pag),
    verifica se APOS esse pagamento o cliente ainda tinha algum outro
    boleto vencido em aberto. Se nao tinha, esse pagamento REGULARIZOU
    o cliente naquela data.

    Vantagem sobre "cliente nao esta na carteira hoje" (metodo antigo):
    - Cada pagamento fica classificado no SEU CONTEXTO temporal
    - Cliente que regularizou em maio + reincidiu em julho conta como
      REG em maio (correto — foi regularizacao legitima), NAO parcial
    - Cliente que pagou parcial em maio + completou em julho conta como
      PARCIAL em maio + REG em julho (nao 2x reg)

    Vantagem sobre metodo baseado em snapshot:
    - Nao depende de snapshot ter sido populado consistentemente
    - Sem gaps de fim de semana / feriado / falhas do cron
    - Definicao per-evento pura (nao per-dia agregado)

    Usado por:
    - views/historico.py (tela Pagamentos)
    - views/especialista.py (ranking por atendente)
    """
    client = get_bq_client()
    if not client:
        return set()
    try:
        df = client.query("""
            WITH pagamentos_atraso AS (
                SELECT
                    CAST(id_sacado_sac AS STRING) AS cid,
                    DATE(dt_liquidacao_recb) AS data_pag
                FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
                WHERE fl_status_recb = '1'
                  AND dt_liquidacao_recb > dt_vencimento_recb
                GROUP BY id_sacado_sac, data_pag
            ),
            classificado AS (
                SELECT
                    p.cid,
                    p.data_pag,
                    -- Ha OUTRO boleto do cliente em aberto APOS o pagamento?
                    (
                      SELECT COUNT(*)
                      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` c
                      LEFT JOIN `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all` l
                        ON c.id_recebimento_recb = l.id_recebimento_recb
                      WHERE CAST(c.id_sacado_sac AS STRING) = p.cid
                        AND c.comp_st_conta_cont IN ('1.2.1', '1.2.2')
                        AND DATE(c.dt_vencimento_recb) <= p.data_pag
                        AND (l.dt_liquidacao_recb IS NULL
                             OR DATE(l.dt_liquidacao_recb) > p.data_pag)
                    ) AS boletos_em_aberto_pos
                FROM pagamentos_atraso p
            )
            SELECT
                cid AS id,
                FORMAT_DATE('%d/%m/%Y', data_pag) AS data
            FROM classificado
            WHERE boletos_em_aberto_pos = 0
        """).to_dataframe()
        if df.empty:
            return set()
        return {(str(r["id"]), str(r["data"])) for _, r in df.iterrows()}
    except Exception:
        return set()


@st.cache_data(ttl=1800)
def fetch_pagamentos_creditados(dt_inicio_iso: str, dt_fim_iso: str) -> pd.DataFrame:
    """Pagamentos com atraso no período, agrupados POR CLIENTE+DIA, com:
      - atendente_credito: HÍBRIDO em ordem de prioridade:
          1. Último especialista com contato efetivo antes do pgto (msg/lig)
          2. Grupo atual do cliente no splgc-grupo (Ana/Priscila)
          3. 'Sem especialista' (raro — cliente sem grupo nenhum)
      - eh_regularizacao: cliente NÃO está mais inadimplente hoje
      - eh_parcial: cliente AINDA está inadimplente hoje

    A lógica híbrida elimina a categoria 'Sem contato registrado' que era
    confusa — todo cliente faz parte de algum grupo, então o crédito vai
    pra quem é dono dele se não houve contato registrado.

    Trade-off: pagamento espontâneo de cliente da Ana credita a Ana mesmo
    que ela não tenha feito nada. Aceito porque ela tem a 'responsabilidade'
    daquele cliente.

    Retorna DataFrame com:
      id_sacado_sac, dt_pagamento, valor, atendente_credito,
      eh_regularizacao (bool), eh_parcial (bool)
    """
    client = get_bq_client()
    if not client:
        return pd.DataFrame()
    try:
        df = client.query(f"""
            WITH liq AS (
                SELECT
                    CAST(id_sacado_sac AS STRING) AS id_sacado_sac,
                    DATE(dt_liquidacao_recb) AS dt_pagamento,
                    SUM(comp_valor) AS valor
                FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
                WHERE fl_status_recb = '1'
                  AND dt_liquidacao_recb > dt_vencimento_recb
                  AND DATE(dt_liquidacao_recb) >= DATE('{dt_inicio_iso}')
                  AND DATE(dt_liquidacao_recb) <= DATE('{dt_fim_iso}')
                GROUP BY id_sacado_sac, dt_pagamento
            ),
            contatos AS (
                SELECT cid, atendente, data_tarefa,
                    ROW_NUMBER() OVER (PARTITION BY cid ORDER BY data_tarefa DESC) AS rn
                FROM (
                    SELECT CAST(id_sacado_sac AS STRING) AS cid, atendente, data_tarefa
                    FROM `{_TAREFAS_TABLE}`
                    WHERE mensagem_enviada = TRUE
                       OR ligacao_feita = TRUE
                       OR ligacao_atendida = TRUE
                )
            ),
            grupos AS (
                -- Grupo atual do cliente (Ana/Priscila). Fallback se sem contato.
                SELECT CAST(id_sacado_sac AS STRING) AS cid, MAX(grupo) AS grupo
                FROM `business-intelligence-467516.Splgc.splgc-grupo`
                WHERE grupo IN (
                    'Ana Carolina', 'Priscila Oliveira'
                )
                GROUP BY id_sacado_sac
            ),
            inad_hoje AS (
                SELECT DISTINCT CAST(id_sacado_sac AS STRING) AS cid
                FROM `{_SNAPSHOT_TABLE}`
                WHERE data_snapshot = (
                    SELECT MAX(data_snapshot) FROM `{_SNAPSHOT_TABLE}`
                )
            )
            SELECT
                liq.id_sacado_sac,
                liq.dt_pagamento,
                liq.valor,
                -- Híbrido: contato efetivo > grupo atual > 'Sem especialista'
                COALESCE(c.atendente, g.grupo, 'Sem especialista') AS atendente_credito,
                -- Transparência: como esse crédito foi atribuído?
                CASE
                  WHEN c.atendente IS NOT NULL THEN 'via_contato'
                  WHEN g.grupo IS NOT NULL THEN 'via_grupo'
                  ELSE 'sem_atribuicao'
                END AS tipo_atribuicao,
                (i.cid IS NULL) AS eh_regularizacao,
                (i.cid IS NOT NULL) AS eh_parcial
            FROM liq
            -- Janela de 60 dias: contato precisa ter sido nos 60 dias antes
            -- do pagamento. Sem isso, "via contato" incluía contatos de meses
            -- atrás pra faturas diferentes — atribuição imprecisa.
            LEFT JOIN contatos c
              ON c.cid = liq.id_sacado_sac
              AND c.data_tarefa <= liq.dt_pagamento
              AND DATE_DIFF(liq.dt_pagamento, c.data_tarefa, DAY) <= 60
              AND c.rn = 1
            LEFT JOIN grupos g
              ON g.cid = liq.id_sacado_sac
            LEFT JOIN inad_hoje i
              ON i.cid = liq.id_sacado_sac
        """).to_dataframe()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_cobrancas_liquidacao():
    """Pagamentos com atraso (dt_liquidacao > dt_vencimento).

    Filtro intencional pra alinhar com o conceito da tela 'Pagamentos':
      - 'Pagamentos do dia'    = parciais + totais de inadimplentes
      - 'Regularizados do dia' = subset (quem zerou TUDO via flag overlay)
      - 'Pagamentos no mês'    = todos os pagamentos com atraso do mês

    Pagamentos em dia (sem atraso) NÃO entram — não são contexto de cobrança.
    """
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
      AND dt_liquidacao_recb > dt_vencimento_recb
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


@st.cache_data(ttl=300, show_spinner=False)
def fetch_meta_clientes_uid(uid: str) -> dict:
    """Le metadata (status + tel_fixo) por cliente, pra um uid.

    Diferente de get_hist() que precisa de session_state populado,
    essa funcao consulta BQ direto — funciona tambem no cron headless.

    Usado em 2 contextos:
    - Filtrar lote diario (status em STATUS_SEM_CONTATO)
    - Forcar bucket=ligacao pra clientes com tel_fixo=true

    Retorna {cliente_id_str: {'status': str, 'tel_fixo': bool}}.
    """
    client = get_bq_client()
    if not client:
        return {}
    query = f"""
    SELECT
      cliente_id,
      JSON_EXTRACT_SCALAR(historico_json, '$.status') AS status,
      JSON_EXTRACT_SCALAR(historico_json, '$.tel_fixo') AS tel_fixo
    FROM (
      SELECT cliente_id, historico_json,
             ROW_NUMBER() OVER (PARTITION BY cliente_id ORDER BY updated_at DESC) AS rn
      FROM `{_HIST_TABLE}`
      WHERE uid = @uid
    )
    WHERE rn = 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("uid", "STRING", uid)]
    )
    try:
        df = client.query(query, job_config=job_config).to_dataframe()
        out = {}
        for _, r in df.iterrows():
            cid = str(r["cliente_id"])
            meta = {}
            if r.get("status"):
                meta["status"] = r["status"]
            # JSON_EXTRACT_SCALAR retorna string ("true"/"false"/null)
            if str(r.get("tel_fixo", "")).lower() == "true":
                meta["tel_fixo"] = True
            if meta:
                out[cid] = meta
        return out
    except Exception:
        return {}


# Alias retrocompativel — antes da feature 'tel_fixo', a funcao retornava
# so o status como string. Mantem chamadas antigas funcionando.
def fetch_status_clientes_uid(uid: str) -> dict:
    """Wrapper retrocompativel: retorna {cid: status_str}."""
    meta = fetch_meta_clientes_uid(uid)
    return {cid: m.get("status", "") for cid, m in meta.items() if m.get("status")}


def registrar_acao_manual(cid: str, atendente: str, atendeu: bool) -> bool:
    """Registra ligacao manual (telefone fixo) no painel_tarefas_diarias.

    Atualiza:
      - ligacao_feita    = TRUE (sempre — atendente tentou)
      - ligacao_atendida = atendeu (TRUE se atendeu, FALSE se nao)

    Pra cliente em telefone fixo, N8N nao detecta ligacao. Esta funcao
    e' chamada pelos botoes 'Atendeu' / 'Nao atendeu' do dialog quando
    cliente esta marcado com tel_fixo=true.

    Retorna True se atualizou ao menos 1 linha, False caso contrario.
    """
    client = get_bq_client()
    if not client:
        return False
    hoje = hoje_lote()
    try:
        job = client.query(f"""
            UPDATE `{_TAREFAS_TABLE}`
            SET ligacao_feita    = TRUE,
                ligacao_atendida = {str(bool(atendeu)).upper()}
            WHERE id_sacado_sac = '{cid}'
              AND atendente     = '{atendente}'
              AND data_tarefa   = '{hoje}'
        """)
        job.result()
        return (job.num_dml_affected_rows or 0) > 0
    except Exception:
        return False


def load_historico_from_bq():
    """Carrega historico do BQ para o session_state.

    Atendente: carrega só o próprio historico.
    Admin: carrega o próprio + o das atendentes (Ana/Priscila), pra
        que `_hist_pra_pendencias` consiga montar a união dos fixados.
    """
    import hashlib
    from auth import current_uid, current_role, get_store as _get_store
    uid_logado = current_uid()
    if not uid_logado:
        return
    client = get_bq_client()
    if not client:
        return
    ensure_historico_table()

    # Decide quais uids carregar: atendente carrega só o próprio; admin
    # carrega o próprio + Ana e Priscila (uids derivados via md5 do email).
    role = current_role()
    uids = {uid_logado}
    if role == "admin":
        for email in _EMAIL_GRUPO.keys():
            uids.add(hashlib.md5(email.encode()).hexdigest())

    query = """
    SELECT uid, cliente_id, historico_json
    FROM (
        SELECT uid, cliente_id, historico_json,
               ROW_NUMBER() OVER (PARTITION BY uid, cliente_id ORDER BY updated_at DESC) AS rn
        FROM `{table}`
        WHERE uid IN UNNEST(@uids)
    )
    WHERE rn = 1
    """.format(table=_HIST_TABLE)
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("uids", "STRING", list(uids))]
    )
    try:
        df = client.query(query, job_config=job_config).to_dataframe()
        store = _get_store()
        for u in uids:
            if u not in store["historico"]:
                store["historico"][u] = {}
        for _, row in df.iterrows():
            try:
                store["historico"][row["uid"]][row["cliente_id"]] = json.loads(row["historico_json"])
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

    # Garante conn viva — Streamlit @st.cache_resource pode reter conn morta
    # após timeout do servidor, causando 'cursor on closed connection'.
    conn = _pg_n8n_conn_alive()
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

        # Ignora mensagens de IA/saudação automática — não viram ação real.
        if any(p in msg for p in _MSG_IA_IGNORAR):
            continue

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

    # Último contato histórico completo (MAX por telefone, sem janela).
    # Filtra mensagens de IA/saudação automática pra ficar consistente com o loop acima.
    ia_filter_sql = " AND ".join(
        f"POSITION(LOWER('{p.replace(chr(39), chr(39)+chr(39))}') IN LOWER(message)) = 0"
        for p in _MSG_IA_IGNORAR
    )
    try:
        cur.execute(f"""
            SELECT telefone, MAX(created_at) AS ultimo_contato
            FROM {table}
            WHERE LOWER(fromme::text) = 'true'
              AND {ia_filter_sql}
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
    # Timestamps brutos (UTC) — usados pelo atualizar_tarefas_bq pra filtrar
    # interações fora da janela [criação do lote, meia-noite BRT da data do lote).
    st.session_state["_msg_concluida_ts"]        = concluida_ts
    st.session_state["_msg_ultimo_contato_ts"]   = ultimo_contato_ts


def load_cooldowns_from_painel():
    """Carrega cooldowns por id_sacado_sac via painel_tarefas_diarias.
    Fonte de verdade pra geração do lote (substitui cooldown N8N).
    Janela: 5 dias (cobre ligação 5d e mensagem 3d).
    Salva no session_state:
      _painel_dias_msg[id]            → dias desde dt_mensagem_enviada (None se nunca)
      _painel_dias_lig[id]            → dias desde dt_ligacao_atendida — cooldown 5d só conta atendida
      _painel_dias_lig_tentada[id]    → dias desde dt_ligacao_feita — qualquer tentativa (badge)
      _painel_acoes_hoje[id]          → {"msg": bool, "lig": bool, "atend": bool} do dia atual
      _streak_cooldown_dias[id]       → dias restantes de cooldown 7d por 2 tentativas falhadas
                                         consecutivas (None se cooldown não está ativo)
    """
    st.session_state.setdefault("_painel_dias_msg", {})
    st.session_state.setdefault("_painel_dias_lig", {})
    st.session_state.setdefault("_painel_dias_lig_tentada", {})
    st.session_state.setdefault("_painel_acoes_hoje", {})
    st.session_state.setdefault("_streak_cooldown_dias", {})

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
        # Sem janela temporal — badge "Última msg há Xd" precisa ver histórico completo
        # do painel pra não cair em fallback N8N por engano. Tabela é pequena
        # (~3.5k linhas/mês, scan <1MB). Revisar quando passar de ~1M linhas.
        df = client.query(f"""
            SELECT id_sacado_sac,
                   MAX(dt_mensagem_enviada) AS dt_msg,
                   MAX(dt_ligacao_atendida) AS dt_lig_atend,
                   MAX(dt_ligacao_feita)    AS dt_lig_tent
            FROM `{_TAREFAS_TABLE}`
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

    # 2-strikes cooldown: 2 tentativas falhadas consecutivas (lig_feita=TRUE,
    # lig_atendida=FALSE) → bloqueia ligação por 7 dias uteis a partir da última tentativa.
    # Janela 30 dias: cobre casos com falhas ligeiramente espaçadas (14d era muito
    # curto — perdia streak quando cliente caia esporadicamente no lote) sem custo
    # de full-scan. Cooldown ativo dura no máximo 7 úteis (~10 corridos), então
    # 30 dias sempre inclui a falha #1 quando a #2 ainda está no cooldown.
    streak_cooldown = {}
    try:
        df_streak = client.query(f"""
            WITH tentativas AS (
                SELECT
                    id_sacado_sac,
                    data_tarefa,
                    ligacao_atendida,
                    ROW_NUMBER() OVER (
                        PARTITION BY id_sacado_sac
                        ORDER BY data_tarefa DESC
                    ) AS rn
                FROM `{_TAREFAS_TABLE}`
                WHERE data_tarefa >= DATE_SUB(CURRENT_DATE("America/Sao_Paulo"), INTERVAL 30 DAY)
                  AND ligacao_feita = TRUE
            )
            SELECT
                id_sacado_sac,
                MAX(data_tarefa) AS ultima_tentativa
            FROM tentativas
            WHERE rn <= 2
            GROUP BY id_sacado_sac
            HAVING COUNT(*) >= 2
               AND COUNTIF(ligacao_atendida) = 0
        """).to_dataframe()

        for _, row in df_streak.iterrows():
            cid = str(row["id_sacado_sac"])
            ultima = row.get("ultima_tentativa")
            if ultima is None or pd.isna(ultima):
                continue
            try:
                ultima_d = ultima if isinstance(ultima, date) else pd.to_datetime(ultima).date()
                # Conta dias UTEIS (seg-sex, sem feriados) — alinha com o
                # ciclo de geracao do lote (segunda a sexta sem feriados).
                # Cooldown de 7 dias uteis = ~1.5 semana de calendario, mais
                # justo que 7 corridos (que so dava 5 dias uteis efetivos).
                dias_desde = dias_uteis_entre(ultima_d, hoje_brt_dt)
                restante = 7 - dias_desde
                if restante > 0:
                    streak_cooldown[cid] = restante
            except Exception:
                pass
    except Exception:
        pass

    st.session_state["_streak_cooldown_dias"] = streak_cooldown


def load_ultimo_contato_painel():
    """Lê última interação por cliente em painel_tarefas_diarias SEM janela temporal.

    Diferente de load_cooldowns_from_painel (que limita a 6 dias pra cooldown), aqui
    pegamos o MAX de qualquer ação histórica. Usado pra alimentar 'Último Contato' na
    tela Inadimplência — mesmo cliente tocado meses atrás aparece com a data correta.

    Salva em session_state:
      _painel_ultimo_contato_dias[cid] → dias desde a interação mais recente
                                          (msg enviada, ligação atendida ou tentada)
    """
    st.session_state.setdefault("_painel_ultimo_contato_dias", {})

    client = get_bq_client()
    if not client:
        return

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
                   GREATEST(
                       COALESCE(MAX(dt_mensagem_enviada), TIMESTAMP('1970-01-01')),
                       COALESCE(MAX(dt_ligacao_atendida), TIMESTAMP('1970-01-01')),
                       COALESCE(MAX(dt_ligacao_feita),    TIMESTAMP('1970-01-01'))
                   ) AS dt_ultimo
            FROM `{_TAREFAS_TABLE}`
            WHERE dt_mensagem_enviada IS NOT NULL
               OR dt_ligacao_atendida IS NOT NULL
               OR dt_ligacao_feita    IS NOT NULL
            GROUP BY id_sacado_sac
        """).to_dataframe()
    except Exception:
        return

    out = {}
    for _, row in df.iterrows():
        cid = str(row["id_sacado_sac"])
        d = _dias(row.get("dt_ultimo"))
        if d is not None:
            out[cid] = d
    st.session_state["_painel_ultimo_contato_dias"] = out


def load_grupo_atendente_map():
    """Lê splgc-grupo e mapeia cliente_id → grupo (que é o nome do atendente
    responsável). Fonte PRIMÁRIA de 'quem é dona desse cliente' — cobertura
    ampla (todos os clientes têm grupo). painel_tarefas_diarias é fallback.

    Salva em session_state:
      _grupo_atendente[cid] → 'Ana Carolina' | 'Priscila Oliveira'

    Filtra valores que não batem com atendentes conhecidos (_EMAIL_GRUPO)
    pra não vazar grupos genéricos (regiões, denominações).
    """
    st.session_state.setdefault("_grupo_atendente", {})

    client = get_bq_client()
    if not client:
        return

    try:
        df = client.query(f"""
            SELECT CAST(id_sacado_sac AS STRING) AS id, MAX(grupo) AS grupo
            FROM `business-intelligence-467516.Splgc.splgc-grupo`
            WHERE grupo IS NOT NULL
            GROUP BY id_sacado_sac
        """).to_dataframe()
    except Exception:
        return

    nomes_validos = set(_EMAIL_GRUPO.values())
    out = {}
    for _, row in df.iterrows():
        cid = str(row["id"]).strip()
        grupo = str(row.get("grupo") or "").strip()
        if cid and grupo in nomes_validos:
            out[cid] = grupo
    st.session_state["_grupo_atendente"] = out


def load_atendente_atual_painel():
    """Lê o atendente mais recente por cliente em painel_tarefas_diarias.
    FALLBACK (após splgc-grupo) — só tem clientes que entraram em algum lote.

    Salva em session_state:
      _painel_atendente_atual[cid] → 'Ana Carolina' | 'Priscila Oliveira'
    """
    st.session_state.setdefault("_painel_atendente_atual", {})

    client = get_bq_client()
    if not client:
        return

    try:
        df = client.query(f"""
            SELECT id_sacado_sac,
                   ARRAY_AGG(atendente ORDER BY data_tarefa DESC LIMIT 1)[OFFSET(0)] AS atendente_atual
            FROM `{_TAREFAS_TABLE}`
            WHERE atendente IS NOT NULL
            GROUP BY id_sacado_sac
        """).to_dataframe()
    except Exception:
        return

    out = {}
    for _, row in df.iterrows():
        cid = str(row["id_sacado_sac"])
        atend = row.get("atendente_atual")
        if atend is not None and not pd.isna(atend) and str(atend).strip():
            out[cid] = str(atend).strip()
    st.session_state["_painel_atendente_atual"] = out


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
    
    # Top 30 LIG: 2 passes pra dar prioridade a acordos.
    # Pass A: pega ACORDOS primeiro (respeitando o limit estrito de 10 inativos).
    # Pass B: completa LIG com NÃO-ACORDOS (respeitando o limit residual).
    # Acordos que não couberem no limit ficam fora do lote (entram outro dia).

    # ── Pass A: ACORDOS primeiro ─────────────────────────────────────
    for score, cid, c in cands_all:
        if len(ids_lig) >= _LOTE_META_LIG:
            break
        acoes = recomendar_acao(c)
        if "urgente" not in acoes:
            continue
        eh_inativo = bool(c.get("_inativo"))
        if eh_inativo and inat_lig >= _LOTE_MAX_INAT_LIG:
            continue  # respeita o limit estrito
        novos.append((cid, "ligacao"))
        ids_lig.add(cid)
        if eh_inativo:
            inat_lig += 1

    # ── Pass B: NÃO-ACORDOS completam ────────────────────────────────
    for score, cid, c in cands_all:
        if len(ids_lig) >= _LOTE_META_LIG:
            break
        if cid in ids_lig:
            continue
        acoes = recomendar_acao(c)
        if "ligar" not in acoes or "urgente" in acoes:
            continue  # só não-acordo
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

        # Pula clientes com tel_fixo=true — eles so devem cair em LIG
        # (N8N nao detecta mensagem em telefone fixo). Se nao couberam no
        # top 30 LIG, ficam fora do lote hoje, entram amanha.
        if c.get("_tel_fixo"):
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
    # FASE 2: Fallback Aleatório (SEM limites de inativos, MAS respeita cooldown)
    # ─────────────────────────────────────────────────────────────────
    # Pools separados por bucket — filtrados por recomendar_acao pra evitar
    # enviar msg/ligar pra cliente em cooldown ativo. Limit de 10/15 inativos
    # da FASE 1 não vale aqui (por desenho — fallback ignora caps mas mantém
    # integridade de cooldown).

    ids_selecionados = ids_lig | ids_msg

    inativos_pool_lig = []
    inativos_pool_msg = []
    for score, cid, c in cands_all:
        if cid in ids_selecionados or not c.get("_inativo"):
            continue
        if c.get("_tem_acordo") and (c.get("dias_atraso") or 0) >= 7:
            continue  # acordo nunca cai em msg, e se não coube em LIG fica fora
        acoes = recomendar_acao(c)
        if "ligar" in acoes:
            inativos_pool_lig.append(cid)
        # Tel_fixo: nunca entra no pool de MSG fallback (N8N nao detecta)
        if "mensagem" in acoes and not c.get("_tel_fixo"):
            inativos_pool_msg.append(cid)

    # Completar LIG até 30 com inativos cuja ligação não está em cooldown
    while len(ids_lig) < _LOTE_META_LIG and inativos_pool_lig:
        idx = random.randint(0, len(inativos_pool_lig) - 1)
        cid = inativos_pool_lig.pop(idx)
        if cid in ids_selecionados:
            continue  # foi sorteado em outro bucket antes
        novos.append((cid, "ligacao"))
        ids_lig.add(cid)
        ids_selecionados.add(cid)
        if cid in inativos_pool_msg:
            inativos_pool_msg.remove(cid)  # tira do pool MSG, já comprometido

    # Completar MSG até 50 com inativos cuja mensagem não está em cooldown
    while len(ids_msg) < _LOTE_META_MSG and inativos_pool_msg:
        idx = random.randint(0, len(inativos_pool_msg) - 1)
        cid = inativos_pool_msg.pop(idx)
        if cid in ids_selecionados:
            continue
        novos.append((cid, "mensagem"))
        ids_msg.add(cid)
        ids_selecionados.add(cid)

    return novos


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

    Bloqueia geração em sábado/domingo: cobrança não opera no fim de semana,
    então não polui BQ com lotes de dias que ninguém vai trabalhar.
    """
    atendente = _EMAIL_GRUPO.get(email_logado)
    if not atendente:
        # admin vê todos — bucket fake só pra render (não usado em filtro)
        return {c["id"]: "ligacao" for c in clientes}

    hoje = hoje_lote()

    # Bloqueia geração em fim de semana (sábado=5, domingo=6) e feriados
    # nacionais. Cobrança não opera nesses dias — não polui BQ com lote
    # de dias inativos.
    try:
        d_hoje = date.fromisoformat(hoje)
        if d_hoje.weekday() >= 5:
            return {}
        if eh_feriado(d_hoje):
            return {}
    except Exception:
        pass

    client = get_bq_client()

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
            # Falha ao checar se já existe lote hoje — NÃO prossegue pra gerar
            # um lote novo às cegas (risco real: duplicar o lote do dia caso já
            # exista mas essa query tenha falhado por contenção/timeout
            # passageiro). Fail-closed: retorna vazio, próxima tentativa
            # (rerun/relogin) refaz a checagem do zero.
            return {}

    # Vamos GERAR novo lote. Garante que store['clientes'] não está stale —
    # cache pode ter sido populado em sessão anterior antes do pipeline
    # terminar (ex: admin abriu painel às 04:00). Sem este check, lote pode
    # incluir clientes que já regularizaram durante a madrugada.
    # Pipeline normalmente termina ~07:00 BRT. Se cache é de antes das 08:00,
    # força refresh do BQ pra ter certeza que estamos pegando dados completos.
    _BRT_tz = timezone(timedelta(hours=-3))
    ultima_str = get_store().get("ultima_atualizacao") or ""
    cache_stale_pre_pipeline = True
    if ultima_str:
        try:
            ultima_dt = datetime.strptime(ultima_str, "%d/%m/%Y %H:%M")
            hoje_brt_date = datetime.now(_BRT_tz).date()
            hoje_8h_brt = datetime.combine(hoje_brt_date, _dt_time(8, 0))
            cache_stale_pre_pipeline = ultima_dt < hoje_8h_brt
        except Exception:
            pass
    if cache_stale_pre_pipeline:
        # Re-processa pra ter dados pós-pipeline
        try:
            processar_dados_bigquery()
            clientes = get_store().get("clientes", [])
        except Exception:
            pass  # Em caso de erro, segue com cache atual

    # Geração inicial: 4 fases (30 lig + 50 msg, ≤10/15 inativos, overflow B).
    # Exclui clientes já regularizados (pago via API hoje OU últimos 3 dias).
    # Sem essa filtragem, cliente que pagou sex aparecia no lote da seg porque
    # BQ ainda não tinha replicado a liquidação (compensação D+1/D+2).
    #
    # Tambem exclui clientes marcados como 'telefone_errado' ou 'igreja_fechada'
    # pela atendente (STATUS_SEM_CONTATO). Sem isso, cliente com telefone errado
    # voltaria pro lote todo dia, gerando trabalho zero (atendente nao consegue
    # contatar). Atendente desmarca quando o problema for resolvido (telefone
    # consertado no SL ou igreja reabriu) — proximo cron pega de novo.
    #
    # E marca os clientes com tel_fixo=true atribuindo c['_tel_fixo']=True.
    # Sera usado por _selecionar_top_30_50 pra forcar bucket=ligacao (cliente
    # so atende em telefone fixo, N8N nao detecta msg WhatsApp).
    import hashlib
    from config import STATUS_SEM_CONTATO
    uid_atendente = hashlib.md5(email_logado.encode()).hexdigest()
    meta_por_cid = fetch_meta_clientes_uid(uid_atendente)
    grupo_clientes = []
    for c in clientes:
        if c.get("_grupo") != atendente:
            continue
        if c.get("_regularizado_hoje"):
            continue
        if c.get("_grupo_nao_cobrar"):
            continue
        cid_str = str(c.get("id", ""))
        meta = meta_por_cid.get(cid_str, {})
        if meta.get("status") in STATUS_SEM_CONTATO:
            continue
        # Marca tel_fixo no dict do cliente — _selecionar_top_30_50 le
        c["_tel_fixo"] = bool(meta.get("tel_fixo", False))
        grupo_clientes.append(c)
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
    # Dia operacional (vira 08:15 BRT) — alinha 'hoje' com o ciclo do lote.
    from helpers import hoje_lote as _hoje_lote_fn
    hoje_op = _hoje_lote_fn()
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
                    FROM `business-intelligence-467516.Splgc.splgc-grupo`
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
                  -- DATE(dt_liquidacao_recb) SEM timezone: SL grava o timestamp
                  -- como 'YYYY-MM-DD 00:00:00 UTC' representando o dia BRT que
                  -- a liquidação aconteceu. Converter pra BRT volta pro dia
                  -- anterior às 21h e quebra o filtro.
                  -- Usa o dia OPERACIONAL (hoje_lote) em vez de CURRENT_DATE
                  -- pra alinhar com o ciclo do lote (vira 08:15 BRT).
                  AND DATE(dt_liquidacao_recb) = DATE '{hoje_op}'
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
        })
        # Distinguir quem pagou HOJE vs quem JÁ TINHA pago (saiu da
        # inadimplência só agora porque BQ atualizou). Ambos vão pra
        # coluna CONCLUÍDA mas com labels diferentes pra atendente
        # entender o contexto.
        vlr_hoje = float(row.get("valor_pago_hoje") or 0)
        if vlr_hoje > 0:
            out[-1]["_regularizado_hoje"] = True
            out[-1]["_valor_pago_hoje"] = vlr_hoje
        else:
            out[-1]["_regularizado_antes_hoje"] = True
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


@st.cache_data(ttl=120, show_spinner=False)
def fetch_ids_em_qualquer_lote_hoje() -> set:
    """IDs de TODOS os clientes que estão em algum lote (qualquer atendente)
    do dia operacional atual. Usado pelo admin em 'Todos os clientes' pra
    distinguir visualmente quem está sendo trabalhado vs quem está fora.
    Cache curto (2min) porque lote nasce de manhã e raramente muda no dia.
    """
    client = get_bq_client()
    if not client:
        return set()
    try:
        df = client.query(f"""
            SELECT DISTINCT id_sacado_sac
            FROM `{_TAREFAS_TABLE}`
            WHERE data_tarefa = '{hoje_lote()}'
        """).to_dataframe()
        if df.empty:
            return set()
        return {str(r["id_sacado_sac"]) for _, r in df.iterrows()}
    except Exception:
        return set()


def atualizar_tarefas_bq(atendente: str, status_map: dict, clientes: list):
    """Atualiza bools na tabela de tarefas com base no status n8n do dia.
    Usa um único MERGE em vez de 80 UPDATEs individuais.

    Janela temporal: só conta interações N8N que aconteceram **depois** do cliente
    entrar no lote (`dt_entrou_coluna_*`) e **antes da meia-noite BRT** do dia do lote.
    Isso garante:
      • Bot/automação que dispara antes do lote ser criado não infla métricas
      • Atividade depois das 24:00 BRT não atualiza mais o lote do dia anterior
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

    # Timestamps das interações N8N (UTC) — filtra por janela do lote.
    ultimo_contato_ts = st.session_state.get("_msg_ultimo_contato_ts", {})
    concluida_ts      = st.session_state.get("_msg_concluida_ts", {})

    # Lê o horário em que cada cliente do lote entrou na coluna (criação do lote).
    # Janela = [dt_entrou_coluna_*, meia-noite BRT da data do lote).
    try:
        df_lote = client.query(f"""
            SELECT id_sacado_sac,
                   COALESCE(dt_entrou_coluna_msg, dt_entrou_coluna_ligacao) AS dt_entrada
            FROM `{_TAREFAS_TABLE}`
            WHERE atendente   = '{atendente}'
              AND data_tarefa = '{hoje}'
        """).to_dataframe()
    except Exception:
        return
    if df_lote.empty:
        return
    dt_lote = {str(row["id_sacado_sac"]): row["dt_entrada"] for _, row in df_lote.iterrows()}

    # Cutoff superior: meia-noite BRT do dia seguinte ao lote (= fim do dia operacional)
    _BRT_TZ = timezone(timedelta(hours=-3))
    try:
        data_lote = datetime.strptime(hoje, "%Y-%m-%d").date()
    except Exception:
        return
    dt_cutoff_fim = datetime.combine(data_lote + timedelta(days=1), datetime.min.time(), tzinfo=_BRT_TZ)

    def _dentro_da_janela(ts, dt_entrada):
        """ts (UTC) deve estar entre [dt_entrada, dt_cutoff_fim)."""
        if ts is None or dt_entrada is None:
            return False
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if hasattr(dt_entrada, "tzinfo") and dt_entrada.tzinfo is None:
            dt_entrada = dt_entrada.replace(tzinfo=timezone.utc)
        return dt_entrada <= ts < dt_cutoff_fim

    rows = []
    for c in clientes:
        cid = str(c.get("id", ""))
        if cid not in dt_lote:
            continue  # cliente não está no lote do dia

        # Cliente pode ter múltiplos telefones — checa TODOS os números.
        # Se qualquer um teve interação N8N, o cliente conta (cooldown
        # e métricas são por id_sacado, então sem dupla contagem).
        tels = [_norm(t) for t in (c.get("telefones") or [c.get("telefone", "")]) if t]
        tels = [t for t in tels if t]
        if not tels:
            continue

        # Pega o ts mais recente entre todos os telefones do cliente
        ts_contato_best = None
        ts_concluida_best = None
        st_n8n = None
        for tel in tels:
            st_aqui = status_map.get(tel)
            if st_aqui and not st_n8n:
                st_n8n = st_aqui
            ts_c = ultimo_contato_ts.get(tel)
            if ts_c and (ts_contato_best is None or ts_c > ts_contato_best):
                ts_contato_best = ts_c
            ts_co = concluida_ts.get(tel)
            if ts_co and (ts_concluida_best is None or ts_co > ts_concluida_best):
                ts_concluida_best = ts_co
        if not st_n8n:
            continue

        dt_entrada    = dt_lote[cid]
        # Usa os timestamps mais recentes entre os múltiplos telefones do cliente
        interacao_post = _dentro_da_janela(ts_contato_best,   dt_entrada)
        concluida_post = _dentro_da_janela(ts_concluida_best, dt_entrada)

        msg_env   = interacao_post
        lig_feit  = concluida_post or (interacao_post and st_n8n in ("ligacao_pendente", "tentar_novamente"))
        lig_atend = concluida_post

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
                    # comp_st_conta_cont: 1.2.1=Setup, 1.2.2=Mensalidade.
                    # Usado SÓ pelos cards NPL (filtro por receita). Outras
                    # telas (kanban, indicador) ignoram esse campo.
                    "tipo":           str(row.get("tipo") or ""),
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
                "telefones":        fmt_tel_lista(row["telefone"]),
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


def recomendar_acao(cliente) -> list[str]:
    """Retorna ações elegíveis para o cliente. Cooldown via painel_tarefas_diarias.
    Regras:
      1. Acordo vencido ≥7d + cooldown LIG OK   → ['ligar', 'urgente']
      2. Inadimplência ≥7d + cooldown LIG OK    → 'ligar'
      3. Inadimplência ≥5d + cooldown MSG OK    → 'mensagem'

    Cooldown LIG = 5 dias desde a última ligação ATENDIDA (não conta tentativas).
    Cooldown MSG = 3 dias desde a última mensagem enviada.
    
    Nota: Ranking por score (2-fase) decide qual bucket (LIG ou MSG) o cliente cai.
    Clientes com 15d+ sem contato ≥3d são elegíveis, mas podem cair em MSG se score for menor.
    """
    from helpers import get_painel_dias_lig, get_painel_dias_lig_tentada, get_painel_dias_msg, get_streak_cooldown_dias

    # Grupo SL 'NÃO COBRAR!' (id=55) — bloqueio administrativo vindo direto
    # da Superlógica. Sempre vence, antes de qualquer outra regra (acordo
    # inclusive) — igreja marcada assim não deve ser contatada.
    if cliente.get("_grupo_nao_cobrar"):
        return []

    cobracas = [c for c in cliente.get("_cobracas", []) if (c.get("dias_atraso") or 0) > 0]
    if cobracas:
        dias = max(int(c.get("dias_atraso") or 0) for c in cobracas)
    else:
        dias = cliente.get("dias_atraso") or 0

    cid = cliente.get("id")
    dias_lig      = get_painel_dias_lig(cid)          # ligação atendida (cooldown 5d)
    dias_lig_tent = get_painel_dias_lig_tentada(cid)  # qualquer tentativa de lig
    dias_msg      = get_painel_dias_msg(cid)          # mensagem enviada (cooldown 3d)
    streak_lig    = get_streak_cooldown_dias(cid)     # 2 tentativas falhadas → cooldown 7d (só lig)

    cooldown_lig_ok = (dias_lig is None or dias_lig >= 5) and (streak_lig is None or streak_lig <= 0)
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

    # 2. Regras genéricas: ranking por score decide o bucket
    #    Não há restrição: cliente com 15d pode cair em MSG se score for menor
    acoes = []
    if dias >= 7 and cooldown_lig_ok:
        acoes.append("ligar")
    if dias >= 5 and cooldown_msg_ok:
        acoes.append("mensagem")
    return acoes


def _hist_pra_pendencias(cid: str) -> dict:
    """Wrapper legado — agora delega pra get_hist_unificado em helpers.py.
    Mantido pra manter calcular_pendencias intacto sem mais ajustes.
    """
    from helpers import get_hist_unificado
    return get_hist_unificado(cid)


def calcular_pendencias(clientes):
    # "Sem contato há X dias" foi removido: esse fluxo é do kanban (Atividades),
    # não dos Clientes Fixados. Aqui ficam só compromissos explícitos da atendente.
    # Admin vê fixados das duas atendentes (união); cada atendente vê só
    # os próprios. Decidido via _hist_pra_pendencias.
    # Retorna tupla (cliente, hist, tipo, mensagem, dias_atraso) ordenada por
    # dias_atraso ASC pra mostrar os compromissos mais recentes primeiro
    # (atendente prioriza o que acabou de vencer; cauda antiga fica no fim).
    pendencias = []
    hoje       = date.today()
    for c in clientes:
        h = _hist_pra_pendencias(c["id"])
        s = h.get("status", "pending")
        if s == "promise" and h.get("promiseDate"):
            dt = parse_date_br(h["promiseDate"])
            if dt and dt <= hoje:
                dias = (hoje - dt).days
                pendencias.append((c, h, "promise", f"Prometeu pagar em {h['promiseDate']}", dias))
                continue
        if h.get("retorno"):
            dt = parse_date_br(h["retorno"])
            if dt and dt <= hoje:
                dias = (hoje - dt).days
                pendencias.append((c, h, "retorno", f"Retorno para {h['retorno']}", dias))
                continue
    pendencias.sort(key=lambda x: x[4])
    return pendencias


def concluir_pendencia(cid: str):
    """Marca compromisso (promise/retorno) como concluído.

    Comportamento:
      - Apaga promiseDate e retorno (cliente sai da lista de Fixados)
      - Se status era 'promise', rebaixa pra 'contacted' (promessa perdeu
        a data → não faz sentido manter como promise; cliente foi contactado
        no passado, então 'contacted' é o estado natural). Outros statuses
        (negotiating, etc.) ficam intactos.
      - lastContact NÃO é atualizado — atendente clicar botão não significa
        que falou com cliente. Update de lastContact vem só de mensagem ou
        ligação real (na tela Atividades).
      - Notes intactas.

    Regra de quem modifica o quê:
      - Atendente (Ana/Priscila): modifica só o próprio historico
      - Admin: modifica TODAS as atendentes que têm o cliente marcado
        (limpa o fixado da tela de todo mundo que estava vendo)
    """
    import hashlib
    from auth import current_role, current_uid, get_store as _gs

    role     = current_role()
    store    = _gs()
    historicos = store.get("historico", {}) or {}

    if role == "admin":
        atendente_uids = {hashlib.md5(e.encode()).hexdigest() for e in _EMAIL_GRUPO.keys()}
        uids_modificar = [u for u in atendente_uids if cid in historicos.get(u, {})]
    else:
        uids_modificar = [current_uid()]

    for uid in uids_modificar:
        if not uid or uid not in historicos or cid not in historicos[uid]:
            continue
        h = dict(historicos[uid][cid])
        h.pop("promiseDate", None)
        h.pop("retorno", None)
        if h.get("status") == "promise":
            h["status"] = "contacted"
        store["historico"][uid][cid] = h
        try:
            save_hist_to_bq(uid, cid, h)
        except Exception:
            pass

    try:
        from helpers import _persistir_historico
        _persistir_historico(store)
    except Exception:
        pass


# ── Cache local ───────────────────────────────────────────────────────────────

# Versão do schema/filtros dos dados em cache. Bump quando mudar query
# do BQ (ex: filtro novo) — cache local com versão diferente é descartado,
# forçando re-fetch fresh no próximo login.
_CACHE_VERSION = 3  # v3: overlay também filtra clientes em contexto de inadimplência


def salvar_cache_local():
    store      = get_store()
    cache_file = Path(__file__).parent / "cache_dados.json"
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({
                "_version":           _CACHE_VERSION,
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
        # Versão diferente = schema/filtros mudaram → descarta cache, force
        # re-fetch via processar_dados_bigquery (store fica vazio).
        if data.get("_version") != _CACHE_VERSION:
            return None
        store                       = get_store()
        store["clientes"]           = data.get("clientes",           [])
        store["regularizados"]      = data.get("regularizados",      [])
        store["ultima_atualizacao"] = data.get("ultima_atualizacao", "")
        store["historico"]          = data.get("historico",          {})
        return True
    except Exception:
        return False
