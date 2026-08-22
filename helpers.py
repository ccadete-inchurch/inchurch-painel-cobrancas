from datetime import date, datetime, timedelta, timezone
import pandas as pd

_BRT = timezone(timedelta(hours=-3))


def hoje_brt() -> str:
    """Data de hoje no fuso BRT (America/Sao_Paulo) em ISO. Usar como chave de
    'dia útil' em vez de date.today(), que segue o timezone do servidor (UTC)."""
    return datetime.now(_BRT).date().isoformat()


def hoje_lote() -> str:
    """Data do 'dia operacional' do lote. Vira às 08:15 BRT, não à meia-noite.
    Antes das 08:15, ainda retorna o dia anterior — pra dar tempo da base do BQ
    refletir os pagamentos da noite e evitar gerar lote com dados desatualizados.
    """
    agora = datetime.now(_BRT)
    if agora.hour < 8 or (agora.hour == 8 and agora.minute < 15):
        return (agora.date() - timedelta(days=1)).isoformat()
    return agora.date().isoformat()


def carimbo_dia_cache() -> str:
    """Carimbo do 'dia do cache' — vira 08:30 BRT, DEPOIS do cron gerar lote
    e snapshot. Serve como chave de cache pra invalidar dados 1×/dia com
    garantia de que o BQ está completamente atualizado no momento do refetch.

    Diferença vs hoje_lote() (que vira 08:15): esperamos os 15min extras
    pra o cron GH Action terminar de escrever lote + snapshot no BQ.
    Assim, quando o cache invalida (08:30+), o próximo fetch pesado pega
    tudo consistente — sem risco de popular cache com lote de ontem no meio
    da execução do cron.

    Usado como arg _dia=carimbo_dia_cache() nas queries pesadas do BQ.
    """
    agora = datetime.now(_BRT)
    if agora.hour < 8 or (agora.hour == 8 and agora.minute < 30):
        return (agora.date() - timedelta(days=1)).isoformat()
    return agora.date().isoformat()

from auth import current_uid, get_store
from pathlib import Path
import json


# ── Telefone ──────────────────────────────────────────────────────────────────

def fmt_tel(valor) -> str:
    """Retorna o primeiro telefone (legado — preservado pra compat)."""
    if not valor:
        return "—"
    return str(valor).split(";")[0].strip() or "—"


def fmt_tel_lista(valor) -> list[str]:
    """Retorna todos os telefones válidos do cliente (separados por ; no banco).
    Filtra entradas vazias e duplicadas, mantendo a ordem original."""
    if not valor:
        return []
    seen = set()
    out = []
    for raw in str(valor).split(";"):
        tel = raw.strip()
        if tel and tel not in seen:
            seen.add(tel)
            out.append(tel)
    return out


def formatar_telefone(tel: str) -> str:
    """Formata telefone pra exibicao. Detecta BR vs internacional.

    Internacionais suportados (identificados na base real do BQ):
    - Portugal (351)
    - Luxemburgo (352)
    - Italia (39)
    - Argentina (54, 12 digitos)
    - Chile (56, 11 digitos)
    - Paraguai (595)
    - Bolivia (591)
    - Uruguai (598)
    - UK (44, 12 digitos)
    - EUA/Canada (1, com + ou parenteses)

    Ordem de deteccao: prefixos de 3 digitos (mais especificos) -> 2 digitos
    -> BR fallback. Desambiguacao chave e' o TAMANHO: DDD BR mais movel tem
    11 digitos; codigos pais internacionais geralmente ficam em 12-13.

    Exemplos:
      31992368305    -> (31) 99236-8305      (BR)
      3132345678     -> (31) 3234-5678       (BR fixo)
      351917797169   -> +351 917 797 169     (Portugal)
      352691674091   -> +352 691 674 091     (Luxemburgo)
      393663448118   -> +39 366 344 8118     (Italia)
      541160501954   -> +54 11 6050-1954     (Argentina, 12d)
      56998174547    -> +56 9 9817-4547      (Chile)
      59598562408    -> +595 98 562 408      (Paraguai)
      447724609205   -> +44 7724 609 205     (UK)
      1(470)661-1101 -> +1 470 661-1101      (EUA)
    """
    import re as _re
    if not tel:
        return "—"
    tel_str = str(tel).strip()
    tem_mais = tel_str.startswith("+")
    tem_parenteses_eua = tel_str.startswith("1(") or tel_str.startswith("1 (")
    digits = _re.sub(r"\D", "", tel_str)
    if not digits:
        return tel_str
    # Cadastro incompleto: menos de 8 digitos NAO consegue ser um telefone
    # real (fixo mais curto do mundo tem ~7-8). Antes caia no fallback
    # 'return f"+{digits}"' e virava lixo tipo "+55" quando so o DDI era
    # cadastrado. Marca como invalido pra ser filtrado na exibicao.
    if len(digits) < 8:
        return ""

    # ─── Codigos de 3 digitos (mais especificos primeiro) ─────────────
    if digits.startswith("351") and len(digits) == 12:  # Portugal
        n = digits[3:]
        return f"+351 {n[:3]} {n[3:6]} {n[6:]}"
    if digits.startswith("352") and len(digits) == 12:  # Luxemburgo
        n = digits[3:]
        return f"+352 {n[:3]} {n[3:6]} {n[6:]}"
    if digits.startswith("595") and len(digits) in (11, 12):  # Paraguai
        n = digits[3:]
        if len(n) == 9:
            return f"+595 {n[:3]} {n[3:6]} {n[6:]}"
        return f"+595 {n[:2]} {n[2:5]} {n[5:]}"
    if digits.startswith("591") and len(digits) == 11:  # Bolivia
        n = digits[3:]
        return f"+591 {n[:4]}-{n[4:]}"
    if digits.startswith("598") and len(digits) in (11, 12):  # Uruguai
        n = digits[3:]
        return f"+598 {n[:2]} {n[2:5]} {n[5:]}"

    # ─── Codigos de 2 digitos ─────────────────────────────────────────
    # Italia (39 + 9-10 digitos)
    if digits.startswith("39") and len(digits) in (11, 12):
        n = digits[2:]
        return f"+39 {n[:3]} {n[3:6]} {n[6:]}"
    # Argentina (54 + 10 = 12 total; BR DDD 54 tem 11)
    if digits.startswith("54") and len(digits) == 12:
        n = digits[2:]
        return f"+54 {n[:2]} {n[2:6]}-{n[6:]}"
    # Chile (56 + 9 = 11 total; sem DDD 56 no BR)
    if digits.startswith("56") and len(digits) == 11:
        n = digits[2:]
        return f"+56 {n[:1]} {n[1:5]}-{n[5:]}"
    # UK (44 + 10 = 12 total; BR DDD 44 tem 11)
    if digits.startswith("44") and len(digits) == 12:
        n = digits[2:]
        return f"+44 {n[:4]} {n[4:7]} {n[7:]}"
    # Japao (81 + 10 = 12 total; BR DDD 81 tem 11)
    if digits.startswith("81") and len(digits) == 12:
        n = digits[2:]
        return f"+81 {n[:2]} {n[2:6]}-{n[6:]}"

    # Cadastro BR antigo com '0' na frente (formato pre-portabilidade):
    # 0XXXXXXXXXX (12 digitos comecando com 0). Remove o 0 e formata como BR.
    if digits.startswith("0") and len(digits) == 12:
        digits = digits[1:]  # remove o 0 inicial

    # EUA/Canada (1 + 10 digitos)
    # Detecta em 3 cenarios:
    # 1. '+' explicito no original
    # 2. Parenteses tipico '1(...)'
    # 3. HEURISTICA: 11 digitos comecando com '1' onde o 3o digito NAO e' 9.
    #    Justificativa: movel BR SEMPRE tem 9 no 3o digito (nono digito
    #    obrigatorio desde 2016). Se nao tem 9 ali, nao pode ser movel BR
    #    valido — provavel US (1 + area + numero).
    parece_eua_heuristica = (
        digits.startswith("1") and len(digits) == 11 and digits[2] != "9"
    )
    if (tem_mais or tem_parenteses_eua or parece_eua_heuristica) and digits.startswith("1") and len(digits) == 11:
        n = digits[1:]
        return f"+1 {n[:3]} {n[3:6]}-{n[6:]}"

    # ─── BR com DDI 55 (12 ou 13 digitos) ─────────────────────────────
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]

    # ─── BR sem DDI (10 = fixo, 11 = movel com 9) ─────────────────────
    if len(digits) in (10, 11):
        ddd = digits[:2]
        resto = digits[2:]
        if len(resto) == 9:  # movel
            return f"({ddd}) {resto[:5]}-{resto[5:]}"
        return f"({ddd}) {resto[:4]}-{resto[4:]}"  # fixo

    # ─── Fallback: numero raw com + ────────────────────────────────────
    # Rejeita numeros suspeitos (< 10 digitos) — nao bateu nenhuma regra
    # e nao tem digitos suficientes pra ser um telefone real (mesmo fixo
    # BR precisa de DDD+8=10). Retorna vazio pra filtro na exibicao.
    if len(digits) < 10:
        return ""
    return f"+{digits}"


def telefone_wa_link(tel: str) -> str:
    """Retorna so os digitos com DDI (formato wa.me). Detecta internacional
    (Portugal, Luxemburgo, Italia, Argentina, Chile, Paraguai, Bolivia,
    Uruguai, UK, EUA/Canada) e preserva o codigo pais.

    BR sem DDI (10-11 digitos) recebe prefixo 55 automaticamente.
    Retorna string vazia se invalido.
    """
    import re as _re
    if not tel:
        return ""
    tel_str = str(tel).strip()
    tem_mais = tel_str.startswith("+")
    tem_parenteses_eua = tel_str.startswith("1(") or tel_str.startswith("1 (")
    digits = _re.sub(r"\D", "", tel_str)
    if not digits:
        return ""

    # Internacionais explicitos — preserva codigo pais
    # Portugal / Luxemburgo (3 digits)
    if digits.startswith(("351", "352")) and len(digits) == 12:
        return digits
    # Paraguai / Bolivia / Uruguai (3 digits)
    if digits.startswith(("595", "591", "598")) and len(digits) in (11, 12):
        return digits
    # Italia (39 + 9-10)
    if digits.startswith("39") and len(digits) in (11, 12):
        return digits
    # Argentina (54 + 10 = 12; BR 54 tem 11)
    if digits.startswith("54") and len(digits) == 12:
        return digits
    # Chile (56 + 9 = 11)
    if digits.startswith("56") and len(digits) == 11:
        return digits
    # UK (44 + 10 = 12; BR 44 tem 11)
    if digits.startswith("44") and len(digits) == 12:
        return digits
    # Japao (81 + 10 = 12; BR 81 tem 11)
    if digits.startswith("81") and len(digits) == 12:
        return digits
    # Suica (41 + 9 = 11; BR 41 tem 11 tb, mas movel BR obriga 3o dig = 9)
    if digits.startswith("41") and len(digits) == 11 and digits[2] != "9":
        return digits
    # Belgica (32 + 9 = 11; BR 32 tem 11 tb, movel BR obriga 3o dig = 9)
    if digits.startswith("32") and len(digits) == 11 and digits[2] != "9":
        return digits
    # Mexico (52 + 10 = 12 padrao; 52 nao e' DDD BR, entao 11 dig tb assume MX)
    if digits.startswith("52") and len(digits) in (11, 12):
        return digits
    # BR antigo com '0' na frente (12 digitos) — remove 0 e prefixa 55
    if digits.startswith("0") and len(digits) == 12:
        return "55" + digits[1:]
    # EUA/Canada — 3 sinais possiveis:
    # 1. '+' explicito
    # 2. Parenteses '1(...)'
    # 3. Heuristica: 11 digitos comecando com 1 SEM 9 no 3o digito
    parece_eua_heuristica = (
        digits.startswith("1") and len(digits) == 11 and digits[2] != "9"
    )
    if (tem_mais or tem_parenteses_eua or parece_eua_heuristica) and digits.startswith("1") and len(digits) == 11:
        return digits

    # BR com DDI 55 (12 ou 13 digitos) — mantem
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits

    # BR sem DDI (10 ou 11 digitos) — prefixa 55
    if len(digits) in (10, 11):
        return "55" + digits

    return digits


# ── Painel de tarefas (cooldowns autoritativos) ──────────────────────────────

def get_painel_dias_msg(cliente_id: str):
    """Dias desde a última mensagem registrada em painel_tarefas_diarias, ou None."""
    import streamlit as st
    return st.session_state.get("_painel_dias_msg", {}).get(str(cliente_id))


def get_painel_dias_lig(cliente_id: str):
    """Dias desde a última ligação ATENDIDA (concluída) em painel_tarefas_diarias, ou None.
    Cooldown de 5 dias só conta ligação atendida — tentativas não atendidas não bloqueiam."""
    import streamlit as st
    return st.session_state.get("_painel_dias_lig", {}).get(str(cliente_id))


def get_painel_dias_lig_tentada(cliente_id: str):
    """Dias desde a última tentativa de ligação (atendida OU não), ou None.
    Usado pra badge 'Não atendeu ligação há Xd' — informativo, não afeta cooldown."""
    import streamlit as st
    return st.session_state.get("_painel_dias_lig_tentada", {}).get(str(cliente_id))


def get_painel_acoes_hoje(cliente_id: str) -> dict:
    """Bools do dia atual em painel_tarefas_diarias: {'msg': bool, 'lig': bool, 'atend': bool}."""
    import streamlit as st
    return st.session_state.get("_painel_acoes_hoje", {}).get(str(cliente_id), {})


def get_streak_cooldown_dias(cliente_id: str):
    """Dias UTEIS restantes de cooldown (7 dias uteis) por 2 tentativas falhadas
    consecutivas (lig sem atend). Conta seg-sex sem feriados nacionais.
    Retorna None se cooldown não está ativo. Bloqueia só ligação — mensagem segue regra normal."""
    import streamlit as st
    return st.session_state.get("_streak_cooldown_dias", {}).get(str(cliente_id))


# ── Datas ─────────────────────────────────────────────────────────────────────

def calc_dias(venc):
    if not venc:
        return None
    try:
        d = (
            date(*map(int, reversed(str(venc).split("/"))))
            if "/" in str(venc)
            else pd.to_datetime(venc).date()
        )
        return max((date.today() - d).days, 0)
    except Exception:
        return None


def parse_date_br(s):
    """Converte string 'dd/mm/yyyy' para date. Retorna None se inválido."""
    try:
        p = s.split("/")
        return date(int(p[2]), int(p[1]), int(p[0]))
    except Exception:
        return None


def dias_uteis_entre(d_inicio, d_fim) -> int:
    """Conta dias uteis (seg-sex, excluindo feriados nacionais) entre 2 datas.
    Exclui o dia inicial (d_inicio), inclui o dia final (d_fim).
    Retorna 0 se d_inicio >= d_fim.

    Usado pelo cooldown 'Tentar Novamente' (7 dias uteis apos 2 falhas) —
    semantica de 'dias operacionais de oportunidade' alinhada com o ciclo
    do lote (gerado so de segunda a sexta, sem feriados).
    """
    if d_inicio >= d_fim:
        return 0
    from data import eh_feriado
    count = 0
    d = d_inicio + timedelta(days=1)  # exclui o dia inicial
    while d <= d_fim:
        if d.weekday() < 5 and not eh_feriado(d):  # 0=Seg ... 4=Sex
            count += 1
        d += timedelta(days=1)
    return count


# ── HTML helpers ──────────────────────────────────────────────────────────────

def dias_html(dias):
    if dias is None or (isinstance(dias, float) and pd.isna(dias)):
        return '<span style="color:#6b7280;font-size:12px">—</span>'
    if dias == 0:
        return '<span class="da da-ok">Hoje</span>'
    if dias <= 30:
        return f'<span class="da da-30">{int(dias)}d</span>'
    if dias <= 60:
        return f'<span class="da da-60">{int(dias)}d</span>'
    if dias <= 90:
        return f'<span class="da da-90">{int(dias)}d</span>'
    return f'<span class="da da-max">{int(dias)}d</span>'


# ── Formatação de moeda ───────────────────────────────────────────────────────

def fmt_moeda(v):
    try:
        f = float(v)
        fmt = f"R$ {f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if f >= 5000:
            return f'<span style="font-weight:700;color:#ff6b6b">{fmt}</span>'
        if f >= 1000:
            return f'<span style="font-weight:600;color:#f59e0b">{fmt}</span>'
        return f'<span style="font-weight:500">{fmt}</span>'
    except Exception:
        return "—"


def fmt_moeda_plain(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "—"


# ── Utilitários de dados ──────────────────────────────────────────────────────

def get_hist(cid):
    return get_store()["historico"].get(current_uid(), {}).get(cid, {})


def get_hist_unificado(cid: str) -> dict:
    """Histórico efetivo do cliente respeitando o role:
      - Atendente (Ana/Priscila): só o próprio histórico
      - Admin: união dos historicos das atendentes — escolhe estado
        mais 'ativo' quando duas marcaram o mesmo cliente
        (promise > negotiating > contacted > pending). Também anota
        `_atendentes_origem` (lista de nomes) pra UI mostrar de quem veio.

    O histórico do próprio admin é ignorado pra evitar poluição.
    """
    import hashlib
    from auth import current_role
    role = current_role()
    if role != "admin":
        return get_hist(cid)

    # Lazy import pra evitar ciclo helpers ↔ data
    from data import _EMAIL_GRUPO as _EG
    nome_por_uid = {hashlib.md5(e.encode()).hexdigest(): nome for e, nome in _EG.items()}
    historicos = get_store().get("historico", {}) or {}
    atendente_uids = set(nome_por_uid.keys())
    melhor = {}
    origens = []
    ordem = {"promise": 3, "negotiating": 2, "contacted": 1, "pending": 0}
    for uid, ch in historicos.items():
        if uid not in atendente_uids:
            continue
        h = ch.get(cid)
        if not h:
            continue
        origens.append(nome_por_uid[uid])
        if not melhor:
            melhor = dict(h)
            continue
        if ordem.get(h.get("status", "pending"), 0) > ordem.get(melhor.get("status", "pending"), 0):
            melhor.update(h)
        elif h.get("retorno") and not melhor.get("retorno"):
            melhor["retorno"] = h["retorno"]
        elif h.get("promiseDate") and not melhor.get("promiseDate"):
            melhor["promiseDate"] = h["promiseDate"]
    if origens:
        melhor["_atendentes_origem"] = origens
    return melhor


# ── Status efetivo (combina histórico manual + painel_tarefas_diarias) ────────
# Garante que a tela Inadimplência reflete a mesma fonte de verdade do kanban,
# independente de quem está logado. Painel_tarefas_diarias é o source-of-truth
# pra ações do bot; historico manual prevalece pra promise/negotiating/paid.

def _any_atendente_engaged(cid, except_uid=None) -> bool:
    """True se QUALQUER atendente (_EMAIL_GRUPO) marcou o cliente com algum
    status != 'pending' (i.e., houve interação manual). Opcionalmente
    exclui um uid específico (pra checar 'algum COLEGA', não a própria).
    """
    import hashlib
    from data import _EMAIL_GRUPO as _EG
    historicos = get_store().get("historico", {}) or {}
    uids = {hashlib.md5(e.encode()).hexdigest() for e in _EG.keys()}
    if except_uid:
        uids.discard(except_uid)
    for uid in uids:
        h = historicos.get(uid, {}).get(str(cid), {})
        s = h.get("status", "")
        if s and s != "pending":
            return True
    return False


def is_grupo_nao_cobrar(cid) -> bool:
    """True se o cliente está no grupo SL id=55 'NÃO COBRAR!' (via API
    Superlógica — não existe no BQ). Populado por aplicar_grupo_nao_cobrar_no_store
    (data.py) em session_state['_grupo_nao_cobrar_ids']."""
    import streamlit as st
    return str(cid) in st.session_state.get("_grupo_nao_cobrar_ids", set())


def get_effective_status(cid) -> str:
    """Status visível na tela. Regra:
    - Status INTENCIONAIS (promise/negotiating/telefone_errado/igreja_fechada):
      escolha manual da atendente sempre vence. Sao status que carregam
      informacao especifica que o bot nao consegue inferir.
    - Grupo SL 'NÃO COBRAR!': bloqueio administrativo vindo direto da API —
      vence sobre contacted/pending (bot ja pode ter agido antes do cliente
      entrar nesse grupo), mas nao sobre uma decisao manual mais especifica
      (ex: atendente marcou 'promise' por algum motivo).
    - Contacted: se o BOT agiu OU outra ATENDENTE marcou algo — reflete
      que o time tocou no cliente.
    - Pending: ninguém tocou.

    Pra atendente, 'contacted' agora também inclui clientes que a colega
    cuidou — assim os cards Contactados/Não Contactados refletem trabalho
    do time, enquanto Promessas/Negociando permanecem individuais.
    """
    h = get_hist_unificado(cid)
    manual_st = h.get("status", "")
    # Status intencionais: escolha da atendente vence o auto-update por bot.
    # promise/negotiating: decisao pessoal sobre o estado da negociacao.
    # telefone_errado/igreja_fechada/nao_cobrar: marcacao de impossibilidade
    # ou bloqueio de contato — se o bot agiu antes (ex: bot mandou msg que
    # nao foi respondida), ainda assim o status real deve prevalecer.
    if manual_st in ("promise", "negotiating", "telefone_errado", "igreja_fechada", "nao_cobrar"):
        return manual_st
    if is_grupo_nao_cobrar(cid):
        return "nao_cobrar"
    import streamlit as st
    from auth import current_role, current_uid
    cid_str = str(cid)
    # Bot agiu (painel_tarefas_diarias) → contacted
    if st.session_state.get("_painel_ultimo_contato_dias", {}).get(cid_str) is not None:
        return "contacted"
    # Atendente: checa se uma COLEGA marcou algo (admin já vê união acima)
    role = current_role()
    if role != "admin":
        if _any_atendente_engaged(cid, except_uid=current_uid()):
            return "contacted"
    return manual_st or "pending"


def get_effective_atendente(cid) -> str:
    """Atendente dono do cliente. Prioridade:
    1. Manual do histórico unificado (admin vê das atendentes; atendente vê próprio)
       — só vale se for nome de atendente REAL (Ana/Priscila). Filtra fora
       qualquer outro nome legado.
    2. Grupo do cliente em splgc-grupo (fonte primária — cobertura ampla)
    3. Atendente atual em painel_tarefas_diarias (fallback — só clientes do lote)
    """
    import streamlit as st
    from data import _EMAIL_GRUPO
    h = get_hist_unificado(cid)
    manual = (h.get("atendente") or "").strip()
    if manual and manual in _EMAIL_GRUPO.values():
        return manual
    cid_s = str(cid)
    grupo = st.session_state.get("_grupo_atendente", {}).get(cid_s, "")
    if grupo:
        return grupo
    return st.session_state.get("_painel_atendente_atual", {}).get(cid_s, "")


def get_effective_lastContact(cid) -> str:
    """Último contato (formato DD/MM/AAAA). Mais recente entre:
    - lastContact manual (do histórico unificado — admin vê das atendentes)
    - última ação do bot em painel_tarefas_diarias (sem janela temporal)
    """
    import streamlit as st
    h = get_hist_unificado(cid)
    manual_lc = h.get("lastContact", "") or ""
    cid_str = str(cid)

    dias_painel = st.session_state.get("_painel_ultimo_contato_dias", {}).get(cid_str)
    if dias_painel is None:
        return manual_lc

    painel_d = date.today() - timedelta(days=int(dias_painel))
    painel_lc = painel_d.strftime("%d/%m/%Y")

    if not manual_lc:
        return painel_lc

    m_d = parse_date_br(manual_lc)
    if m_d is None:
        return painel_lc
    return (m_d if m_d > painel_d else painel_d).strftime("%d/%m/%Y")


def save_hist(cid, data):
    store = get_store()
    uid   = current_uid()
    if uid not in store["historico"]:
        store["historico"][uid] = {}
    store["historico"][uid][cid] = data
    try:
        from data import save_hist_to_bq
        save_hist_to_bq(uid, cid, data)
    except Exception:
        pass
    _persistir_historico(store)


def _persistir_historico(store):
    cache_file = Path(__file__).parent / "cache_dados.json"
    if not cache_file.exists():
        return
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)
        cache["historico"] = store.get("historico", {})
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
