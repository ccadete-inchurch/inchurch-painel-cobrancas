from datetime import date, datetime, timedelta, timezone
import pandas as pd

_BRT = timezone(timedelta(hours=-3))


def carimbo_curto() -> str:
    """Chave de cache das consultas de atualização rápida: muda a cada 2 min
    das 08:00 às 23:59 e a cada 1 h das 00:00 às 07:59.

    Por que: uma aba esquecida aberta mantinha o fragment consultando o BQ a
    cada 1-2 min a noite toda, sem ninguém olhando e sem dado novo (o
    pipeline só roda às 04:00). Passa de ~30 consultas/hora pra ~1.
    """
    agora = datetime.now(_BRT)
    if agora.hour < 8:
        return agora.strftime("%Y-%m-%dT%H")
    return f'{agora.strftime("%Y-%m-%dT%H")}-{agora.minute // 2:02d}'


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

    Usado como arg dia=carimbo_dia_cache() nas queries pesadas do BQ. O nome
    NAO pode comecar com "_": st.cache_data ignora esses args na chave do cache
    e o resultado de ontem seria reaproveitado (so renovava pelo ttl de 24h).
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
    """Retorna o primeiro telefone (legado — preservado pra compat).

    Pula o marcador 'ddd=XX' que o data.py manda junto: ele e' o st_ddd_sac
    do cadastro, nao um telefone."""
    if not valor:
        return "—"
    for parte in str(valor).split(";"):
        parte = parte.strip()
        if parte and parte[:4].lower() != "ddd=":
            return parte
    return "—"


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
    if digits.startswith("597") and len(digits) in (9, 10):  # Suriname
        # 597 + 6 (fixo) ou 7 (movel). Nao colide com DDD: 59 nao existe.
        n = digits[3:]
        return f"+597 {n[:3]} {n[3:]}" if len(n) == 7 else f"+597 {n[:3]}-{n[3:]}"
    if digits.startswith("591") and len(digits) == 11:  # Bolivia
        n = digits[3:]
        return f"+591 {n[:4]}-{n[4:]}"
    if digits.startswith("598") and len(digits) in (11, 12):  # Uruguai
        n = digits[3:]
        return f"+598 {n[:2]} {n[2:5]} {n[5:]}"

    if digits.startswith("353") and len(digits) == 12:  # Irlanda
        n = digits[3:]
        return f"+353 {n[:2]} {n[2:5]} {n[5:]}"
    if digits.startswith("244") and len(digits) == 12:  # Angola
        n = digits[3:]
        return f"+244 {n[:3]} {n[3:6]} {n[6:]}"
    if digits.startswith("258") and len(digits) == 12:  # Mocambique
        n = digits[3:]
        return f"+258 {n[:2]} {n[2:5]} {n[5:]}"

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
    # Franca (33 + 9). DDD 33 existe no BR (Gov. Valadares), entao so
    # aceita quando o nacional comeca com 6 ou 7 — movel frances. Um numero
    # brasileiro do DDD 33 comeca com 9 (movel) ou 2-5 (fixo), nunca 6/7.
    if digits.startswith("33") and len(digits) == 11 and digits[2] in "67":
        n = digits[2:]
        return f"+33 {n[:1]} {n[1:3]} {n[3:5]} {n[5:7]} {n[7:]}"
    # Espanha (34 + 9). Mesmo raciocinio: DDD 34 e Uberlandia.
    if digits.startswith("34") and len(digits) == 11 and digits[2] in "67":
        n = digits[2:]
        return f"+34 {n[:3]} {n[3:6]} {n[6:]}"
    # Holanda (31 + 9, movel comeca com 6). DDD 31 e Belo Horizonte.
    if digits.startswith("31") and len(digits) == 11 and digits[2] == "6":
        n = digits[2:]
        return f"+31 {n[:1]} {n[1:5]} {n[5:]}"
    # Japao (81 + 10 = 12 total; BR DDD 81 tem 11)
    if digits.startswith("81") and len(digits) == 12:
        n = digits[2:]
        return f"+81 {n[:2]} {n[2:6]}-{n[6:]}"

    # Cadastro BR antigo com '0' na frente (formato pre-portabilidade):
    # 0XXXXXXXXXX (12 digitos comecando com 0). Remove o 0 e formata como BR.
    # Vale para 10, 11 e 12 digitos: o cadastro antigo grava 0 + DDD + numero,
    # e com 10/11 a leitura sem tirar o zero inventa DDD inexistente
    # (06992588451 virava "(06) 99258-8451"; o certo e "(69) 9258-8451").
    if digits.startswith("0") and len(digits) in (10, 11, 12):
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
    # Suriname (597 + 6 ou 7)
    if digits.startswith("597") and len(digits) in (9, 10):
        return digits
    # Irlanda / Angola / Mocambique (3 digits + 9 = 12)
    if digits.startswith(("353", "244", "258")) and len(digits) == 12:
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
    # Franca / Espanha (2 + 9 = 11). DDD 33 e 34 existem no BR, entao so
    # valem quando o nacional comeca com 6 ou 7 (movel la); numero BR do
    # mesmo DDD comeca com 9 (movel) ou 2-5 (fixo).
    if digits.startswith(("33", "34")) and len(digits) == 11 and digits[2] in "67":
        return digits
    # Holanda (31 + 9, movel comeca com 6). DDD 31 e Belo Horizonte.
    if digits.startswith("31") and len(digits) == 11 and digits[2] == "6":
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
    # BR antigo com '0' na frente — remove 0 e prefixa 55. Vale para 10, 11
    # e 12 digitos: com 10/11 o zero era lido como parte do DDD e gerava
    # link para DDD inexistente (06992588451 -> wa.me/5506992588451).
    if digits.startswith("0") and len(digits) in (10, 11, 12):
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


def get_ultimo_login(cid) -> dict:
    """Ultimo login da igreja no painel de controle.

    Tres estados possiveis, e nenhum deles e' "nao sei":
      com_login  -> dias/data reais (93,8% da carteira)
      sem_login  -> tem tenant no produto mas nao loga desde o inicio do log.
                    Nao e' ausencia de dado: e' piso real (hoje ~853 dias).
      sem_tenant -> convencao/federacao, nao e' igreja no produto (o 6648 e'
                    o caso relevante). Ai sim nao ha o que mostrar.

    `ordem` e' o que a tabela ordena: dias reais pra quem tem, o piso pra quem
    nao loga (ordena junto dos piores, que e' onde ele pertence), NaN pra quem
    nao tem tenant (o na_position="last" do sort joga pro fim).
    """
    import streamlit as st

    reg = st.session_state.get("_painel_ultimo_login", {}).get(str(cid))
    if reg is None:
        return {"estado": "sem_tenant", "dias": None, "data": None,
                "curto": "—", "ordem": float("nan")}

    piso = st.session_state.get("_painel_login_piso_dias")
    if reg["dias"] is None:
        curto = f"+{piso}d" if piso else "+2a"
        return {"estado": "sem_login", "dias": None, "data": None,
                "curto": curto, "ordem": float(piso) if piso else 9999.0}

    d = int(reg["dias"])
    return {"estado": "com_login", "dias": d, "data": reg["data"],
            "curto": "hoje" if d == 0 else f"{d}d", "ordem": float(d)}


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


# ─── diagnostico do numero (usado pra marcar em vermelho no card) ──────
# Tamanho do numero NACIONAL (sem o DDI) por pais, so para DDIs de 3
# digitos: os de 1-2 digitos coincidem com DDD brasileiro ("1" e EUA mas
# tambem DDD 11/12/13; "33" e Franca mas tambem Gov. Valadares) e a
# leitura fica ambigua demais pra afirmar que o numero esta cortado.
_TAM_NACIONAL_DDI3 = {"351": (9,), "352": (9,), "353": (9,), "244": (9,),
                      "258": (9,), "591": (8,), "595": (9,), "598": (8,),
                      "597": (6, 7)}   # Suriname: fixo 6, movel 7

_DDD_VALIDOS = {11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28,
                31, 32, 33, 34, 35, 37, 38, 41, 42, 43, 44, 45, 46, 47, 48, 49,
                51, 53, 54, 55, 61, 62, 63, 64, 65, 66, 67, 68, 69,
                71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85, 86, 87, 88, 89,
                91, 92, 93, 94, 95, 96, 97, 98, 99}


def problema_telefone(tel: str) -> str:
    """Por que o numero nao serve pra discar. String vazia = esta ok.

    So aponta o que da pra afirmar com certeza:
      - numero com DDI de 3 digitos e menos digitos que o pais usa
        (a mascara do campo de celular no Superlogica corta em 11)
      - DDD que nao existe no Brasil
      - digito repetido (00000000000)

    NAO usa regra generica por quantidade de digitos: nos EUA 1+10=11 e o
    tamanho certo, na Franca/Espanha/Suica/Belgica/Italia 2+9=11 tambem.
    """
    import re as _re
    d = _re.sub(r"\D", "", str(tel or ""))
    if not d:
        return ""
    if len(d) > 6 and len(set(d)) <= 2:
        return "número repetido"
    # A regra de DDI so vale quando o proprio formatador leu o numero como
    # estrangeiro. Olhar so o prefixo marcava fixo legitimo de Minas como
    # cortado: (35) 3830-4361 comeca com "353", que tambem e a Irlanda.
    if formatar_telefone(d).startswith("+"):
        for ddi, tams in _TAM_NACIONAL_DDI3.items():
            if d.startswith(ddi):
                nac = len(d) - len(ddi)
                if nac in tams:
                    return ""
                faltam = max(tams) - nac
                if faltam > 0:
                    return f"faltam {faltam} dígito{'s' if faltam > 1 else ''}"
                return ""
        return ""
    wa = telefone_wa_link(d)
    if wa.startswith("55") and not d.startswith("55"):
        n = wa[2:]
        if len(n) in (10, 11) and int(n[:2]) not in _DDD_VALIDOS:
            return f"DDD {n[:2]} não existe"
        if len(n) == 11 and n[2] != "9":
            # Fato, sem chutar a direcao do erro: todo celular brasileiro
            # tem 9 no 3o digito. Quem cai aqui pode ser um fixo com digito
            # a MAIS — (35) 3598-8372 cadastrado como 35359883724, cliente
            # 6553 — ou um numero estrangeiro cortado pela mascara, que e o
            # caso do 72 (353 8761 8609, Irlanda). Dizer "incompleto"
            # afirmava o segundo caso e errava o primeiro.
            return "tem 11 dígitos mas não é celular"
    return ""


def _numero_de_enchimento(d: str) -> bool:
    """Numero digitado so pra fechar o cadastro, nao pra ligar pra alguem.

    Sao os de um digito so repetido — 99999999999, 00000000000, 9999999999,
    a variante com o 55 na frente (5599999999999) — e os que tem DDD de
    verdade seguido de digito repetido: (21) 99999-9999, (21) 88888-8888.
    Esses nao aparecem na tela nem em vermelho: nao ha o que corrigir, nao
    e o telefone de ninguem.
    """
    nucleo = d[2:] if d.startswith("55") and len(d) > 11 else d
    if len(set(nucleo)) == 1:
        return True
    return (len(nucleo) in (10, 11) and nucleo[:2].isdigit()
            and int(nucleo[:2]) in _DDD_VALIDOS and len(set(nucleo[2:])) == 1)


def _mesmo_numero(a: str, b: str, a_ruim: bool = False, b_ruim: bool = False) -> bool:
    """Os dois so de digitos sao o MESMO telefone escrito de outro jeito.

    Tamanhos diferentes — da pra afirmar olhando so os digitos:
      1) identico
      2) um e o fim do outro: a diferenca e so prefixo, seja o 55 do Brasil
         ('5511954052870' x '11954052870'), o DDI ('351968173292' x
         '968173292') ou o DDD que faltava ('65999776677' x '999776677')
      3) o nono digito do celular: (48) 9601-4697 x (48) 99601-4697
      4) a versao cortada pela mascara, que corta no FIM 1 ou 2 digitos
         ('595985969416' x '59598596941')

    Mesmo tamanho — aqui so entra quando UM dos dois nao da pra discar, pra
    nunca esconder numero bom. Dois jeitos de o cadastro repetir o numero:
      5) difere so no 3o digito, que num celular e o 9 obrigatorio:
         99088270757 x 99988270757 (6677)
      6) digito a mais colado na frente e a mascara cortando o fim — o DDD
         digitado duas vezes (21219714553 x 21971455309, cliente 3491), o
         DDD errado na frente de um numero que ja tinha o seu (21659997766 x
         65999776677, cliente 636) ou um digito solto (64699922565 x
         64999225652, cliente 2631).

    Sem a trava do "um dos dois e ruim", a regra 5 fundia 11981675371 (Sao
    Paulo) com 17981675371 (Aracatuba), que sao numeros diferentes com o
    mesmo final.
    """
    if a == b:
        return True
    curto, longo = (a, b) if len(a) < len(b) else (b, a)
    if len(curto) != len(longo):
        if longo.endswith(curto):
            return True
        if {len(a), len(b)} == {10, 11} and longo[:2] == curto[:2]                 and longo[2] == "9" and longo[3:] == curto[2:]:
            return True
        return longo.startswith(curto) and 1 <= len(longo) - len(curto) <= 2
    if a_ruim == b_ruim:
        return False
    if a[:2] == b[:2] and a[-8:] == b[-8:]:
        return True
    for k in (1, 2):
        for i in range(3):
            if a[:i] + a[i + k:] == b[:len(b) - k]:
                return True
            if b[:i] + b[i + k:] == a[:len(a) - k]:
                return True
    return False


def telefones_cliente(valor) -> list[tuple[str, str, str]]:
    """Lista final de telefones do cliente: (bruto, formatado, problema).

    Recebe a string com os 4 campos do cadastro separados por ';' (ou a lista
    ja separada) e devolve o que a tela deve mostrar. Faz duas coisas que o
    fmt_tel_lista sozinho nao faz:

    1) tira repetido por DIGITO, nao por string. O mesmo numero chega escrito
       de formas diferentes — CONCAT(st_ddd_sac, st_telefone_sac) reproduz o
       que esta em st_celular_sac em 319 clientes, e o st_fax_sac guarda a
       versao com 55 na frente ('5521983368588' x '21983368588'). Sem isso o
       card mostrava o mesmo telefone duas e as vezes tres vezes.
    2) junta tambem o numero cortado com a versao inteira dele: a mascara do
       Superlogica corta no FIM, entao o final de 8 digitos nao coincide e a
       deduplicacao por final deixava os dois passarem (114 clientes).

    Quando dois numeros se juntam, fica o que da pra discar; empatados, fica
    o mais completo. Sem essa ordem um celular quebrado expulsava o numero bom
    (6677: 99088270757 expulsava 99988270757).

    'problema' vem do problema_telefone(): vazio = numero bom, texto = motivo
    pra pintar de vermelho e nao oferecer o WhatsApp.
    """
    import re as _re
    brutos = valor if isinstance(valor, (list, tuple)) else fmt_tel_lista(valor)

    # O data.py manda o st_ddd_sac marcado ('ddd=071'). Ele vale pra QUALQUER
    # campo, nao so pro st_telefone_sac: o cliente 4548 tem '982338073' no
    # st_fax_sac e '071' no st_ddd_sac, e juntos dao (71) 98233-8073 — um
    # celular de Salvador, que e onde o cliente fica.
    ddd = ""
    numeros = []
    for item in brutos:
        txt = str(item or "").strip()
        if txt[:4].lower() == "ddd=":
            ddd = _re.sub(r"\D", "", txt[4:])
            continue
        numeros.append(item)
    if ddd in ("0", "00"):
        ddd = ""

    saida: list[tuple[str, str, str, str]] = []   # (digitos, bruto, fmt, prob)
    for bruto in numeros:
        if not bruto:
            continue
        d = _re.sub(r"\D", "", str(bruto))
        if not d or _numero_de_enchimento(d):
            continue
        fmt = formatar_telefone(bruto)
        if (not fmt or fmt == "—") and ddd and not d.startswith(ddd):
            # sozinho nao vira telefone; com o DDD do cadastro, vira
            alt = formatar_telefone(ddd + d)
            if alt and alt != "—":
                bruto, d, fmt = ddd + d, ddd + d, alt
        if not fmt or fmt == "—":
            continue
        prob = problema_telefone(bruto)
        novo = (d, str(bruto), fmt, prob)
        pos = next((i for i, (dj, _b, _f, pj) in enumerate(saida)
                    if _mesmo_numero(dj, d, bool(pj), bool(prob))), None)
        if pos is None:
            saida.append(novo)
            continue
        atual = saida[pos]
        troca = (not prob and atual[3]) or (
            bool(prob) == bool(atual[3]) and len(d) > len(atual[0]))
        if troca:
            saida[pos] = novo
    return [(b, f, p) for _d, b, f, p in saida]


def telefones_texto(valor, sep: str = " · ") -> str:
    """Os telefones do cliente em texto simples, pra onde nao cabe HTML
    (subtitulo de card, celula de tabela, exportacao em CSV).

    Mesma montagem de telefones_cliente — DDD aplicado, repetido juntado —
    com os numeros bons na frente e o furado marcado entre parenteses, ja
    que aqui nao da pra pintar de vermelho.
    """
    itens = telefones_cliente(valor)
    if not itens:
        return "—"
    partes = [f for _b, f, p in itens if not p]
    partes += [f"{f} (verificar)" for _b, f, p in itens if p]
    return sep.join(partes)
