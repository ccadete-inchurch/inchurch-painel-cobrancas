---
date: 2026-05-14
updated: 2026-07-16
author: Davi Machado
type: documentacao
tags:
  - cobranca
  - inadimplencia
  - streamlit
  - bigquery
  - n8n
---

# Painel de Cobrança InChurch

App Streamlit de gestão operacional de inadimplência: organiza a carteira, prioriza ações de cobrança por score, registra interações com clientes e acompanha regularizações em tempo quase real.

**Hospedagem:** Streamlit Cloud (deploy contínuo via push no `main` do repositório GitHub `ccadete-inchurch/inchurch-painel-cobrancas`).
**Localização local do projeto:** `c:\Users\inChurch--1343\OneDrive\Desktop\painel-inadimplencia`

> **⚠ Nota importante sobre o N8N**
>
> As mensagens de cobrança são enviadas **pelas próprias atendentes (Ana Carolina e Priscila)** através do WhatsApp Business — não há bot enviando mensagens em nome delas.
>
> O **N8N atua apenas como observador**: monitora as conversas do WhatsApp, classifica cada evento (mensagem enviada, ligação atendida, cliente respondeu, etc.) usando palavras-chave/padrões, e grava no Postgres. O painel lê esses eventos e propaga pro BigQuery via `atualizar_tarefas_bq`.
>
> Sempre que a documentação menciona "detectado pelo N8N", significa "observado a partir da conversa real que a atendente teve no WhatsApp".

---

## Visão Estratégica

### SIPOC

| Suppliers | Inputs | Process | Outputs | Customers |
|---|---|---|---|---|
| BigQuery (Splgc) | Cobranças em aberto, liquidações, grupos, clientes | 1. Carregar carteira e calcular atraso | Painel de inadimplência com priorização | Atendentes |
| BigQuery (painel_*) | Histórico manual, tarefas diárias, snapshots | 2. Enriquecer com status manual e cooldown | Estado de contato consolidado | Gestores |
| Postgres n8n | Últimas mensagens/interações WhatsApp | 3. Aplicar overlay de eventos recentes detectados no WhatsApp | Sinal de contato quase em tempo real | Admin / BI |
| Superlógica API | Pagamentos do dia (não refletidos ainda no BQ) | 4. Marcar `_regularizado_hoje` na sessão | Overlay de regularizações | — |
| Google OAuth | Identidade e perfil do usuário | 5. Gerar lote diário (30 lig + 50 msg) | Lote diário auditável no BQ | — |
| GitHub Actions | Trigger do cron 08:15 BRT | 6. Persistir histórico, snapshot, tarefas | Base histórica para BI | — |

### Ficha Estratégica

**Propósito:** Reduzir inadimplência com priorização diária baseada em score, respeitando cooldowns automáticos e permitindo intervenção manual do atendente.

**Gatilhos:**
- Cron automático das 08:15 BRT (via GitHub Actions disparado pelo n8n)
- Abertura do painel pelo atendente (regenera lote se ainda não existe pro dia)
- Refresh periódico de 80s (fragment dinâmico) — atualiza cooldowns e mensagens N8N

**Frequência:** Operação contínua de segunda a sexta em horário comercial. Fim de semana e feriados nacionais não geram lote.

**KPIs do Processo**

| KPI | Referência atual |
|---|---|
| Meta diária por atendente | 30 ligações + 50 mensagens = 80 tarefas |
| Cobertura da base em 7 dias | ~61% (medido em 08/07/2026) |
| Cobertura da base em 30 dias | ~100% |
| Rotina do cron | 08:15 BRT (falha rara — retry manual) |
| TTL do cache BQ | 1 hora (fetches com `@st.cache_data`) |
| Fresh cache BQ streak | Sem TTL (varre tabela inteira, ~5MB) |
| Custo BQ mensal estimado | ~US$25/mês (fragment 80s * 4 queries full-scan) |

**Dependências críticas**
- BigQuery `Splgc.*` (replicação diária ~04:00 BRT do Postgres do Superlógica)
- BigQuery `inadimplencia_painel_cobrancas.*` (tabelas de estado do próprio painel)
- Postgres do n8n (`n8nfinchatbot_historico_msgs` — mensagens WhatsApp)
- Superlógica API (overlay de pagamentos do dia)
- Google OAuth + `secrets.toml`
- GitHub Actions + secrets `GCP_SA_JSON`, `PG_N8N_PASSWORD`

**Riscos e Mitigações**

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Atraso na replicação do Splgc → BQ | Alta | Médio | Overlay via Superlógica API pega pagamentos das últimas 3 horas |
| BQ indisponível | Baixa | Alto | Cache local `cache_dados.json` permite navegação |
| Cron falha (GitHub Actions) | Baixa | Alto | Retry manual via `workflow_dispatch`; painel regenera se lote não existe |
| Credenciais OAuth expiradas | Baixa | Alto | Revisar `secrets.toml`, renovar OAuth no console Google |
| Falha silenciosa por `try/except: pass` | Média | Alto | Revisar loops críticos periodicamente (bug do NameError do streak foi assim) |
| N8N sem processar mensagens | Média | Médio | Cooldown de msg pode ficar desatualizado; refresh a cada 80s minimiza |
| Cache stale antes do cron | Baixa | Baixo | Painel valida `ultima_atualizacao < 08:00` e força reprocess |

### Value Stream Map

```
[Cron 08:15] → [Cache load] → [Overlay pagto] → [Reset reincidentes] → [Gera lote] → [Painel exposto]
    3 min          instant          5s               2s                  15s              instant

Tempo de valor agregado: ~25s de processamento efetivo
Lead time do dia operacional: ~5 min (cron completo) + expediente da atendente
Gargalo: dependência da atualização diária do Splgc (~04:00 BRT)
```

---

## RACI

| Etapa | Atendente | Gestor | Admin/BI | Sistema |
|---|---|---|---|---|
| Autenticação (Google OAuth) | I | I | **A** | R |
| Carga da carteira (BQ + cache) | I | I | **A** | R |
| Geração do lote diário (cron) | I | I | **A** | R |
| Ligação e envio de mensagem | **R** | I | I | C |
| Registro de status manual (dialog) | **R** | I | I | C |
| Marcação de status especiais (não cobrar, tel errado, igreja fechada) | **R** | C | I | C |
| Revisão de KPIs e produtividade | C | **R** | A | I |
| Manutenção de secrets e credenciais | I | I | **R** | I |
| Manutenção do cron GitHub Actions | I | I | **R** | I |
| Ajuste em regras de score/cooldown | I | C | **R** | I |
| Deploy do código (push no main) | I | I | **R** | R |

---

## Guia Rápido

### Como acessar
1. Acesse a aplicação no Streamlit Cloud
2. Clique em **Continuar com Google**
3. Use uma conta autorizada (Ana, Priscila, gestor, admin BI)
4. Se conta não autorizada: solicitar inclusão via Admin/BI (edição em `st.secrets["authorized_emails"]`)

### Perfis e permissões

| Perfil | Vê | Pode editar | Não pode |
|---|---|---|---|
| **Atendente** (Ana, Priscila) | Só o próprio grupo do splgc-grupo | Próprio histórico via dialog | Ver clientes de outra atendente |
| **Gestor** | Todos os grupos | Nada (read-only) | Editar histórico |
| **Admin/BI** | União de tudo | Nada via UI (só via código/BQ) | Editar histórico via UI |

### Navegação por tela

| Tela (rota) | Arquivo | Para que serve |
|---|---|---|
| **Atividades** | `views/atividades.py` | Operação diária — kanban de 30 lig + 50 msg, cards NPL, filtros |
| **Inadimplência** | `views/dashboard.py` | Carteira completa — filtros por status, grupo, situação, exportar CSV |
| **Próximas Cobranças** | `views/proximas.py` | Vencimentos futuros por período — antecipa contato |
| **Pagamentos / Regularizados** | `views/especialista.py` | Clientes que regularizaram — reg total, parcial, produtividade |
| **Cliente** | `views/cliente.py` | Visão detalhada de um cliente específico |
| **Histórico** | `views/historico.py` | Timeline de ações do cliente |
| **Login** | `views/login.py` | Tela de OAuth |

### Fluxo de trabalho da atendente

```
1. Abre painel → login → Atividades (kanban do dia)
2. Vê 80 cards priorizados por score (30 LIG + 50 MSG)
3. Para cada card:
   - Ligação: liga → clica dialog → marca resultado (Atendeu / Não atendeu / Prometeu / Negociando)
   - Mensagem: atendente envia pelo WhatsApp pessoal; N8N detecta o envio e marca automaticamente no painel
4. Cards com resultado somem/movem entre colunas (Urgente / Ligar / Msg / Concluído / Tentar Novamente)
5. Card fica em cooldown após ação → volta ao lote nos próximos dias respeitando as regras
```

### Ações no dialog

| Campo | Editável | Efeito |
|---|---|---|
| Status | Sim | Muda coluna no kanban; se `nao_cobrar`/`telefone_errado`/`igreja_fechada`, sai do lote |
| Último Contato | **Não** (readonly) | Mostra data efetiva (max entre manual e evento detectado pelo N8N) |
| Agendar Retorno | Sim | Data futura → cliente vira "Fixado" |
| Prometeu Pagar | Sim | Fixa cliente até data prometida |
| Telefone Fixo (checkbox) | Sim | N8N não detecta ligação em fixo (só WhatsApp); força bucket=ligação; libera botões Atendeu/Não atendeu pra marcação manual |
| Observações | Sim | Texto livre pra contexto (auto-save) |

### O que acontece após cada ação

| Ação | Resultado |
|---|---|
| Login | Sessão criada, `_grupo_atendente` carregado, cache aberto |
| Alterar status no dialog | Auto-save → `save_hist` → BQ + session_state |
| Clicar "Atendeu" (tel fixo) | `registrar_acao_manual` → UPDATE em `painel_tarefas_diarias` |
| Marcar como "Não cobrar" | Cliente some do kanban imediatamente + fora do lote no próximo cron |
| Atualizar (Inadimplência) | `processar_dados_bigquery` refetch + regrava `cache_dados.json` |
| Refresh de 80s (fragment) | `load_cooldowns_from_painel` + `load_mensagens_from_bq` (não bloqueia UI) |
| Logout | Sessão encerrada, dados sensíveis removidos |

### Erros comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| Carteira vazia | Cache corrupto ou credenciais BQ | Clicar Atualizar; verificar `secrets.toml` |
| Login não avança | Conta sem autorização | Adicionar email em `secrets.authorized_emails` |
| Histórico não reflete ação recente | Cache do session_state | F5 na página (aguarda 80s ou reload manual) |
| Cliente aparece indevidamente no lote | Bug de filtro ou cooldown | Verificar `nao_cobrar`/streak/`_regularizado_hoje` |
| Status "Não cobrar" some do card | Cache do usuário admin | F5 — filtro admin usa `get_hist_unificado` |

---

## Documentação Técnica

### Estrutura de arquivos

```
painel-inadimplencia/
├── app.py                       # Bootstrap Streamlit, roteamento, load inicial de dados
├── auth.py                      # Google OAuth, perfis (atendente/gestor/admin), session store
├── data.py                      # BQ, N8N, lote, score, cooldowns, snapshots (~4000 linhas)
├── helpers.py                   # Datas (dias úteis, feriados), telefones internacionais, histórico
├── config.py                    # STATUS_LABELS/OPTS/SEM_CONTATO, sort_map, CSS global
├── cache_dados.json             # Fallback local (last known good state)
├── requirements.txt
├── inchurch_logo.png
├── .streamlit/
│   ├── config.toml              # Tema dark
│   └── secrets.toml             # OAuth, GCP SA, PG password (não commitado)
├── .github/
│   └── workflows/
│       └── gerar-lote.yml       # workflow_dispatch para cron 08:15 (disparado pelo n8n)
├── scripts/
│   └── gerar_lote_cron.py       # Entrypoint do cron (shim streamlit + roda pipeline)
├── views/
│   ├── login.py                 # OAuth callback
│   ├── sidebar.py               # Menu de navegação + info do usuário
│   ├── header.py                # Cabeçalho comum
│   ├── dashboard.py             # Tela Inadimplência
│   ├── atividades.py            # Tela Atividades (kanban + NPL)
│   ├── cliente.py               # Tela Cliente (detalhe)
│   ├── historico.py             # Tela Histórico
│   ├── especialista.py          # Tela Pagamentos/Regularizados
│   ├── proximas.py              # Tela Próximas Cobranças
│   └── dialog.py                # Dialog modal de edição (usado em vários lugares)
└── Documentacoes/
    └── painel-cobranca.md       # Este arquivo
```

### C4 — Contexto

```
Ana / Priscila     Gestor           Admin/BI
     ↓                ↓                 ↓
        Streamlit Cloud (painel-cobranca.streamlit.app)
                     ↕
        ┌────────────┼─────────────────────────────┐
        ↓            ↓                             ↓
  BigQuery      Postgres n8n                Superlógica API
  (Splgc + painel_*)  (mensagens WhatsApp)  (pagamentos live)

  ↑
  Cron 08:15 BRT (GitHub Actions dispatched by n8n)
```

### C4 — Containers principais

```
app.py (orquestração)
  ├─ auth.py                     → Google OAuth, roles, session
  ├─ data.py                     → BQ / N8N / Superlógica / cache
  │   ├─ processar_dados_bigquery      → fetch_cobrancas + liquidacao + grupo
  │   ├─ load_cooldowns_from_painel    → cooldown normal (5d/3d) + streak (7 úteis)
  │   ├─ load_mensagens_from_bq        → últimas msgs do n8n
  │   ├─ gerar_tarefas_do_dia          → orquestra lote diário
  │   ├─ _selecionar_top_30_50         → Pass A/B/MSG/Fallback
  │   ├─ recomendar_acao               → decide se cliente é elegível
  │   ├─ calcular_score                → heurística de priorização
  │   └─ aplicar_pagamentos_hoje       → overlay Superlógica
  ├─ helpers.py                  → formatação, datas úteis, telefones
  └─ views/                      → renderização Streamlit
```

### Fluxo de execução do painel (usuário abrindo)

```
1. app.py sobe (Streamlit)
2. Callback OAuth se estiver retornando de popup
3. Se não autenticado → views/login.py
4. Se autenticado:
   4.1 processar_dados_bigquery() → carrega ~626 clientes
   4.2 load_historico_from_bq()   → histórico manual das atendentes
   4.3 load_mensagens_from_bq()   → últimas msgs do n8n
   4.4 load_cooldowns_from_painel() → cooldown normal + streak
   4.5 load_ultimo_contato_painel() → última interação sem janela
   4.6 load_atendente_atual_painel() → fallback do grupo
   4.7 aplicar_pagamentos_hoje_no_store() → overlay live
   4.8 Roteia pra view escolhida (default: Atividades)
5. Fragment dinâmico (a cada 80s) → refresh cooldowns + mensagens
```

### Fluxo do cron das 08:15 BRT

Executado por `scripts/gerar_lote_cron.py` via GitHub Actions (workflow_dispatch disparado pelo n8n):

```
1. Shim de streamlit é instalado em sys.modules (SessionState fake)
2. processar_dados_bigquery() → clientes inadimplentes
3. load_mensagens_from_bq() → mensagens N8N
4. load_cooldowns_from_painel() → popula _streak_cooldown_dias
5. aplicar_pagamentos_hoje_no_store() → marca _regularizado_hoje
6. resetar_status_reincidentes() → limpa status stale de dívida velha
7. Para cada atendente:
   gerar_tarefas_do_dia(clientes, email) → seleciona 80, insere no BQ
8. salvar_snapshot_inadimplentes_hoje() → snapshot diário
```

### BPMN — Ciclo diário

```
        08:15 BRT
           ↓
     [Cron dispara]
           ↓
  [Carrega Splgc do BQ]
           ↓
    [Overlay pagto Superlógica]
           ↓
  [Reset status reincidentes]
           ↓
    ┌──────┴──────┐
    ↓             ↓
 Ana:            Priscila:
 gerar 80        gerar 80
    ↓             ↓
    └──────┬──────┘
           ↓
   [Salva no BQ]
           ↓
  [Snapshot diário]
           ↓
       (Fim)

    Depois, durante o dia:

  [Atendente abre painel]
           ↓
  [App detecta lote existente]
           ↓
  [Renderiza kanban]
           ↓
  ┌────────┴─────────┐
  ↓                  ↓
Atende cliente     Marca especial
  ↓                (não cobrar/tel errado)
[Bot registra]        ↓
  ↓             [Card some do kanban]
[Cooldown ativa]      ↓
  ↓             [Fora do próximo lote]
Próximo dia:
  Se cooldown ok → volta ao lote
  Se streak (2 falhas) → 7 úteis fora
```

---

## Regras de Priorização e Lote

### Score (calcular_score em data.py:3605)

Pontuação usada pra ordenar candidatos:

```
score = valor / 100                        # receita total dividida por 100
      + dias_atraso                        # até 90d → +1/dia
      + max(0, (dias_atraso - 90) * 0.5)   # 90-360d → +0.5/dia (teto 225pts)
      + soma de +15 por parcela com atraso > 15d
      + 20 se _tem_acordo (flat)
      + (parcelas - 1) * 50                # cada parcela adicional
      + dias_sem_contato * 2               # último contato ou vencimento
```

Score alto = mais prioridade.

### Passes de seleção (_selecionar_top_30_50 em data.py:2830)

Todos os passes percorrem `cands_all` ordenados por score decrescente.

| Pass | Filtro | Ocupa | Limite inativos |
|---|---|---|---|
| **A (LIG)** | `"urgente" in recomendar_acao(c)` → só acordos elegíveis | slots LIG até 30 | máx 10 inativos |
| **B (LIG)** | `"ligar" in acoes AND "urgente" not in acoes` → não-acordos | completa LIG até 30 | máx 10 inativos (contador compartilhado com A) |
| **MSG** | `"mensagem" in acoes AND not _tel_fixo` | slots MSG até 50 | máx 15 inativos |
| **Fallback** | Sorteio aleatório de inativos elegíveis | completa LIG/MSG faltante | Sem limite (respeita cooldown) |

**Regra chave:** acordos têm precedência sobre score puro. Acordo urgente com score 40 entra antes de não-acordo com score 200.

### recomendar_acao (data.py:3628)

Decide o que o cliente pode receber hoje:

```python
if _tem_acordo:
    if dias_atraso < 7:
        return []                              # espera 7d de atraso
    return ["ligar", "urgente"] if cooldown_lig_ok else []

# Sem acordo:
acoes = []
if dias_atraso >= 7 and cooldown_lig_ok:
    acoes.append("ligar")
if dias_atraso >= 5 and cooldown_msg_ok:
    acoes.append("mensagem")
return acoes
```

### Cooldowns

| Cooldown | Fonte | Duração | Componente |
|---|---|---|---|
| **Mensagem** | `_painel_dias_msg` (última msg enviada) | 3 dias corridos | `cooldown_msg_ok = dias_msg is None or dias_msg >= 3` |
| **Ligação (atendida)** | `_painel_dias_lig` (última atendida) | 5 dias corridos | `cooldown_lig_ok` parte 1 |
| **Streak (2 falhas)** | `_streak_cooldown_dias` (2 tentativas sem atender) | 7 dias **úteis** | `cooldown_lig_ok` parte 2 |
| Combinação | Ambos precisam OK pra "ligar" | | `AND` de ambos |

**Regra do streak (data.py:2625):**
- Query pega as 2 tentativas mais recentes (dentro de 30 dias corridos) de cada cliente
- Se ambas têm `ligacao_atendida = FALSE` → streak ativa
- Cooldown = 7 dias úteis a partir da última tentativa
- Só bloqueia LIG — cliente sem acordo com streak pode ir pra MSG

**Cálculo de dias úteis:** `helpers.dias_uteis_entre(d1, d2)` exclui sábado, domingo e feriados nacionais (BrasilAPI + fallback local em `data._FERIADOS_FIXOS_MMDD`).

### Status especiais (STATUS_SEM_CONTATO)

Cliente marcado com um desses status **não entra no lote nem aparece no kanban**:

| Status | Uso |
|---|---|
| `telefone_errado` | Cadastro tem número inválido/desatualizado |
| `igreja_fechada` | Instituição encerrou operações |
| `nao_cobrar` | Bloqueio administrativo (jurídico, acordo externo, congelamento a pedido do gestor) |

Todos definidos em `config.STATUS_SEM_CONTATO`. Filtro aplicado em:
- `data.py:2982` (geração do lote no cron)
- `views/atividades.py:1194` (filtro live do kanban)

Cliente continua visível em outras telas (Inadimplência, Fixados, Cliente, Histórico) mesmo com esses status. Reversível a qualquer momento — atendente muda status pra outra coisa e cliente volta ao lote no próximo cron.

### Overlay de pagamentos (aplicar_pagamentos_hoje_no_store)

Como o BQ replica com defasagem de horas, pagamentos das últimas horas ainda não aparecem no snapshot. O overlay consulta a **Superlógica API** e marca `_regularizado_hoje = True` no dict do cliente. Isso:
- Exclui do lote no próximo cron
- Move o cliente pra coluna "Concluído" no kanban
- Aparece em Pagamentos/Regularizados

TTL do fetch: 5 minutos (cacheado). Rodado a cada render do painel (idempotente).

### Reset de reincidentes (resetar_status_reincidentes)

Cliente que pagou uma dívida antiga e reincidiu com nova dívida pode ter status residual ("promise", "retorno agendado", "negociando") referente à dívida já quitada. O cron limpa esses status pra atendente tratar como caso novo. Preserva `notes` e `lastContact` (contexto ainda vale).

---

## Dicionário de Dados

### Store da sessão Streamlit

| Campo | Tipo | Observações |
|---|---|---|
| `store.clientes[].id` | STRING | Chave primária (id_sacado_sac) |
| `store.clientes[].valor` | FLOAT | Só entra na carteira se > 0 |
| `store.clientes[].dias_atraso` | INT | Atraso da cobrança mais velha |
| `store.clientes[]._tem_acordo` | BOOL | Tem cobrança 1.2.13 aberta vencida |
| `store.clientes[]._inativo` | BOOL | `dt_desativacao_sac IS NOT NULL` |
| `store.clientes[]._nova_cobranca` | BOOL | Cliente com >1 parcela e a mais nova ≤ 30d |
| `store.clientes[]._grupo` | STRING | Nome do atendente (`Ana Carolina`, `Priscila Oliveira`, ou "—") |
| `store.clientes[]._cobracas` | LIST | Cobranças individuais (id_recebimento, valor, venc, dias, tipo, status) |
| `store.clientes[]._regularizado_hoje` | BOOL | Marcado pelo overlay Superlógica |
| `store.clientes[]._meses_atraso` | INT | Histórico consolidado |
| `store.clientes[]._tel_fixo` | BOOL | Marcado pela atendente no dialog |
| `store.historico[uid][cid].status` | STRING | Ver tabela de status abaixo |
| `store.historico[uid][cid].lastContact` | STRING | `DD/MM/YYYY` — manual |
| `store.historico[uid][cid].retorno` | STRING | Data de retorno agendado |
| `store.historico[uid][cid].promiseDate` | STRING | Data de promessa de pagamento |
| `store.historico[uid][cid].tel_fixo` | BOOL | Persistido |
| `store.historico[uid][cid].notes` | STRING | Observações |
| `store.historico[uid][cid].atendente` | STRING | Quem salvou |
| `store.ultima_atualizacao` | STRING | Timestamp da última carga |
| `st.session_state._painel_dias_msg` | DICT[cid→int] | Dias desde última msg |
| `st.session_state._painel_dias_lig` | DICT[cid→int] | Dias desde última lig atendida |
| `st.session_state._painel_dias_lig_tentada` | DICT[cid→int] | Dias desde última tentativa |
| `st.session_state._streak_cooldown_dias` | DICT[cid→int] | Dias úteis restantes do streak |
| `st.session_state._painel_ultimo_contato_dias` | DICT[cid→int] | Sem janela — full history |
| `st.session_state._painel_atendente_atual` | DICT[cid→str] | Fallback de grupo |
| `st.session_state._grupo_atendente` | DICT[cid→str] | Do splgc-grupo |

### Tabelas BigQuery consumidas

**Splgc (replicação diária ~04:00 BRT do Postgres do Superlógica)**

| Tabela | Uso |
|---|---|
| `Splgc.splgc-cobrancas_competencia-all` | Cobranças em aberto (fl_status_recb=0) — carteira principal |
| `Splgc.splgc-cobrancas_liquidacao-all` | Liquidações (fl_status_recb=1) — regularizados, histórico |
| `Splgc.splgc-grupo` | Grupo/atendente do cliente |
| `Splgc.splgc-clientes-inchurch` | Telefone auxiliar (st_fax_sac) |

**Painel (estado do próprio app — schema `inadimplencia_painel_cobrancas`)**

| Tabela | Chave | Uso |
|---|---|---|
| `painel_tarefas_diarias` | (id_sacado_sac, atendente, data_tarefa) | Fonte de verdade do lote — bucket, timestamps, marcações detectadas pelo N8N |
| `painel_historico` | (uid, cliente_id) | Histórico manual (status, retorno, promise, notes, tel_fixo) |
| `cobrancas_snapshot_diario` | (data_snapshot, id_sacado_sac) | Snapshot diário pra métricas de variação |

**Postgres n8n (`n8nfinchatbot_historico_msgs`)**

Histórico de mensagens WhatsApp trocadas entre as atendentes (Ana e Priscila) e os clientes. **As atendentes enviam as mensagens pessoalmente pelo WhatsApp — o N8N não envia nada, ele apenas monitora as conversas.** Um workflow do N8N escuta os eventos do WhatsApp Business API e classifica cada interação em categorias operacionais (mensagem enviada, ligação pendente, ligação atendida, tentar novamente, concluída).

Consumido por `load_mensagens_from_bq` (nome legado — na verdade lê do Postgres). Usado pra:
- Detectar status atualizado a partir da conversa real
- Popular `dt_mensagem_enviada`, `dt_ligacao_feita`, `dt_ligacao_atendida` via `atualizar_tarefas_bq`

**Classificação depende de palavras-chave e padrões** definidos no fluxo N8N. Se cliente responder algo fora do padrão (gíria, áudio, emoji só), o N8N pode não classificar corretamente.

### Status válidos

| Chave | Rótulo UI | Fonte | Efeito no lote |
|---|---|---|---|
| `pending` | Sem contato | Automático (sem histórico) | Elegível normal |
| `contacted` | Contactado | Automático (atendente interagiu — detectado pelo N8N) | Elegível normal |
| `promise` | Prometeu pagar | Manual | Elegível normal (mas fixado até promiseDate) |
| `negotiating` | Negociando | Manual | Elegível normal |
| `telefone_errado` | Telefone errado | Manual | **Excluído** do lote e kanban |
| `igreja_fechada` | Igreja fechada | Manual | **Excluído** do lote e kanban |
| `nao_cobrar` | Não cobrar | Manual | **Excluído** do lote e kanban |
| `paid` | Regularizado | Automático (overlay/liquidação) | Auto-exclui (não é mais inadimplente) |

### Buckets do lote

| Bucket | Coluna BQ | Origem |
|---|---|---|
| `ligacao` | `dt_entrou_coluna_ligacao IS NOT NULL` | Pass A ou B do lote |
| `mensagem` | `dt_entrou_coluna_msg IS NOT NULL` | Pass MSG do lote |

Cliente cai em exatamente um bucket por dia. Bucket é congelado no INSERT — não muda durante o dia mesmo se cliente vira acordo depois.

---

## ADRs

### ADR-001: BigQuery como fonte principal com cache local

**Status:** Aceito

**Contexto:** A carteira precisa estar disponível mesmo quando o BQ falha ou demora. O app também precisa responder rápido na navegação cotidiana.

**Decisão:** BQ como fonte principal; espelho local em `cache_dados.json` para fallback imediato. TTL de 1h nas queries mais pesadas via `@st.cache_data`.

**Consequências**
- Positivo: app continua útil em falhas temporárias; reduz custo de reconexão durante a sessão
- Negativo: risco de exibir dados levemente defasados se o BQ não for recarregado
- Trade-off aceito: consistência eventual em troca de disponibilidade e velocidade

**Alternativas descartadas**
- Sempre buscar do BQ: latência alta na navegação
- Somente em memória: perde estado ao reiniciar sessão

---

### ADR-002: n8n/Postgres para interações recentes, BQ para estado consolidado

**Status:** Aceito

**Contexto:** O N8N monitora o WhatsApp das atendentes e grava cada mensagem/interação no Postgres em tempo quase real. Se dependêssemos só do BQ, atendente ficaria minutos/horas sem ver a atividade recente (Splgc → BQ replica ~04:00 BRT do dia seguinte). Por outro lado, `painel_tarefas_diarias` no BQ é a fonte de verdade auditável do lote.

**Decisão:** Postgres do n8n é lido a cada 50s (fragment) pra atualizar `_msg_status`. Estado consolidado (bucket, timestamps de ação, cooldowns) é sempre gravado e lido do BQ. `atualizar_tarefas_bq` propaga o status detectado pelo N8N → `painel_tarefas_diarias`.

**Consequências**
- Positivo: atendente vê o que ela mesma acabou de fazer refletido no painel em ~1 minuto; auditoria fica no BQ
- Negativo: duas fontes → regra de precedência precisa estar clara (implementada em `get_effective_status`)
- Trade-off aceito: complexidade adicional em troca de responsividade

**Alternativas descartadas**
- Tudo no n8n/Postgres: sem histórico persistente pra BI
- Tudo no BQ: painel lento pra refletir o que atendente acabou de fazer no WhatsApp

---

### ADR-003: Virada do lote às 08:15 BRT com quotas 30/50 e caps de inativos

**Status:** Aceito

**Contexto:** Precisamos evitar gerar lote antes da replicação da noite anterior estar completa (Splgc → BQ termina ~04:00 BRT, mas às vezes atrasa). E precisamos priorizar clientes ativos sem descartar totalmente inativos (podem regularizar em teoria).

**Decisão:**
- Dia operacional vira às 08:15 BRT (`hoje_lote()` respeita esse corte)
- Lote: 30 ligações + 50 mensagens por atendente
- Cap de inativos: 10 em ligação, 15 em mensagem
- Fallback: sorteia inativos sem acordo pra completar

**Consequências**
- Positivo: reduz falsa priorização por pagamento não refletido; dá previsibilidade
- Negativo: regra não é intuitiva pra quem não leu a doc
- Trade-off aceito: corte operacional diferente do calendário civil em troca de qualidade do lote

**Alternativas descartadas**
- Virar à meia-noite: pega dados stale
- Sem cap de inativos: pioraria eficiência da carteira ativa

---

### ADR-004: Cooldown de streak em 7 dias úteis com janela de 30 dias

**Status:** Aceito (janela ajustada em 2026-07-08 após bug fix)

**Contexto:** Cliente que atendente tenta ligar 2x seguidas e não atende raramente vai atender na 3ª. Insistir todo dia gasta slot e frustra a atendente. Precisa de cooldown, mas não pode ser "para sempre".

**Decisão:**
- **Regra:** 2 tentativas de ligação consecutivas sem atender → cliente sai do lote de ligação por 7 dias úteis (sem contar sábado, domingo e feriados nacionais)
- **Janela de busca:** últimos 30 dias corridos (cobre casos de clientes que caem esporadicamente no lote — 14 dias era insuficiente)
- **Cliente sem acordo em streak:** ainda pode receber mensagem (streak bloqueia só LIG)
- **Cliente com acordo em streak:** fica totalmente fora do lote (acordo nunca vai pra MSG)

**Cálculo de dias úteis:** `helpers.dias_uteis_entre` chama `data.eh_feriado` que consulta BrasilAPI + fallback hardcoded de feriados fixos.

**Bug histórico (2026-07-08):** o import de `eh_feriado` não estava sendo feito — `try/except: pass` engolia o NameError. Só clientes com falha HOJE entravam no dict de streak (dias_uteis retornava 0 no early return, evitando o crash). Fix em commit `cb44360`.

**Consequências**
- Positivo: libera ~46 slots/dia pra clientes que não estão em cooldown (medido em 08/07/2026)
- Negativo: cliente que ficaria receptivo hoje precisa esperar até o cooldown expirar
- Trade-off aceito: eficiência da fila em troca de possíveis oportunidades perdidas

**Alternativas descartadas**
- 3 falhas → 7 dias: muito tolerante, insistência excessiva
- 2 falhas → 14 dias corridos: muito rígido, empurra demais
- Sem janela: full-scan da tabela desnecessário (30d já cobre 100% dos casos ativos)

---

### ADR-005: Status especiais (nao_cobrar, telefone_errado, igreja_fechada) como flag de exclusão

**Status:** Aceito

**Contexto:** Alguns clientes não devem receber cobrança:
- Telefone errado no cadastro (atendente não consegue contatar pelo WhatsApp)
- Igreja encerrada (não faz sentido cobrar)
- Bloqueio administrativo (acordo externo, jurídico, congelamento)

Antes da existência desses status, atendente marcava manualmente algo genérico ou pedia ao Admin BI pra remover do lote — processo lento e sujeito a erro.

**Decisão:** Criar 3 status que, quando aplicados, excluem o cliente:
- Do lote do dia (filtro em `gerar_tarefas_do_dia`)
- Do kanban de Atividades (filtro live)
- Mas **preservam visibilidade** em Inadimplência, Fixados, Histórico, Pagamentos

Reversível: atendente muda status pra outra coisa e cliente volta ao próximo lote.

**Consequências**
- Positivo: atendente resolve sozinha, sem depender de Admin; documenta motivo (status é auditável)
- Negativo: mais 3 opções no dropdown do dialog (leve poluição visual)
- Trade-off aceito: autonomia da atendente em troca de complexidade mínima

**Alternativas descartadas**
- Remover cliente do BQ: destrutivo, perde histórico
- Deletar linha do splgc-grupo: fora do escopo do painel, quebra outros dashboards
- Flag booleana única: perde a semântica de por que está excluído

---

### ADR-006: `get_hist_unificado` para admin/gestor visualizar união de históricos

**Status:** Aceito (formalizado em 2026-07-09)

**Contexto:** Cada atendente tem seu próprio `uid` (hash do email). `get_hist(cid)` retorna só o histórico do uid logado. Isso funciona pra atendente (vê o próprio), mas admin/gestor têm `uid` sem histórico → veriam sempre "vazio".

Antes: cliente marcado como "Não cobrar" pela Ana aparecia normalmente pro admin no kanban (o filtro STATUS_SEM_CONTATO usava `get_hist` e o admin não tinha o status marcado).

**Decisão:** `get_hist_unificado(cid)`:
- Atendente → retorna o próprio `get_hist`
- Admin/Gestor → união dos históricos das atendentes, escolhendo o "estado mais ativo" (promise > negotiating > contacted > pending). Anota `_atendentes_origem`.

Aplicado em:
- `views/atividades.py` (kanban)
- `views/dashboard.py` (via `get_effective_status`)
- `views/dialog.py` (admin vê como está salvo)

**Consequências**
- Positivo: admin/gestor veem a realidade que atendente vê
- Negativo: cliente marcado com status conflitante entre atendentes (raro) tem "vencedor" arbitrário
- Trade-off aceito: consistência visual em troca de possível merge ambíguo

---

## Referência Rápida

### Constantes do lote

Definidas em `data.py`:

| Constante | Valor | Onde |
|---|---|---|
| `_LOTE_META_LIG` | 30 | data.py |
| `_LOTE_META_MSG` | 50 | data.py |
| `_LOTE_MAX_INAT_LIG` | 10 | data.py |
| `_LOTE_MAX_INAT_MSG` | 15 | data.py |
| `PAGE_SIZE` | 50 | config.py (paginação inadimplência) |
| Cooldown ligação | 5 dias corridos | recomendar_acao |
| Cooldown mensagem | 3 dias corridos | recomendar_acao |
| Cooldown streak | 7 dias úteis | load_cooldowns_from_painel |
| Janela do streak | 30 dias corridos | data.py:2634 |
| Virada do dia | 08:15 BRT | helpers.hoje_lote |
| Refresh fragment | 80 segundos | views/atividades.py |
| Refresh N8N | 50 segundos | views/atividades.py |
| TTL cache overlay | 5 minutos | aplicar_pagamentos_hoje |

### Feriados (fallback local em data._FERIADOS_FIXOS_MMDD)

- 01-01 (Ano Novo)
- 21-04 (Tiradentes)
- 01-05 (Trabalho)
- 07-09 (Independência)
- 12-10 (Padroeira)
- 02-11 (Finados)
- 15-11 (Proclamação)
- 25-12 (Natal)

Fonte primária: `https://brasilapi.com.br/api/feriados/v1/{ano}` (inclui móveis: Sexta Santa, Corpus Christi).

### Colunas relevantes de `painel_tarefas_diarias`

| Campo | Tipo | Significado |
|---|---|---|
| `id_sacado_sac` | STRING | ID do cliente |
| `atendente` | STRING | Nome (Ana Carolina / Priscila Oliveira) |
| `data_tarefa` | DATE | Dia operacional |
| `dt_entrou_coluna_ligacao` | TIMESTAMP | Não-null se bucket=ligacao |
| `dt_entrou_coluna_msg` | TIMESTAMP | Não-null se bucket=mensagem |
| `mensagem_enviada` | BOOL | Bot enviou msg |
| `ligacao_feita` | BOOL | Atendente tentou ligar (detectado pelo N8N ou marcado manualmente no dialog) |
| `ligacao_atendida` | BOOL | Cliente atendeu |
| `dt_mensagem_enviada` | TIMESTAMP | Momento da msg |
| `dt_ligacao_feita` | TIMESTAMP | Momento da tentativa |
| `dt_ligacao_atendida` | TIMESTAMP | Momento do atendimento |

### Custo BigQuery estimado

Baseado em observação de 2026-07:

| Query | Frequência | Scan por chamada | Custo mensal |
|---|---|---|---|
| `load_cooldowns_from_painel` (4 sub-queries) | 720/dia (fragment 80s) | ~15 MB (30d streak + full-scan últ. contato) | ~US$8 |
| `fetch_npl_metrics` | ~50/dia (filtros) | ~30 MB | ~US$5 |
| `fetch_npl_rolling` | ~50/dia | ~40 MB | ~US$6 |
| `processar_dados_bigquery` | ~10/dia por atendente | ~100 MB | ~US$3 |
| Outras (snapshots, meta, etc) | várias | pequeno | ~US$3 |
| **Total** | | | **~US$25/mês** |

Otimizações possíveis (não aplicadas ainda):
- Aumentar intervalo do fragment de 80s pra 5min (reduz 4x)
- Particionar `painel_tarefas_diarias` por `data_tarefa`
- Cachear queries "somente por sessão" mais agressivamente

---

## Bugs Históricos Resolvidos

### Streak silenciosamente quebrado (2026-06-29 a 2026-07-08)

**Sintoma:** Clientes com 2+ ligações consecutivas não atendidas continuavam caindo no lote LIG todo dia (30-50% do lote diário).

**Causa:** `helpers.dias_uteis_entre` chamava `eh_feriado()` sem importar (função vive em `data.py`). Um `try/except: pass` em `load_cooldowns_from_painel` engolia o `NameError`. Só clientes cuja última tentativa foi HOJE entravam no dict (early return em `dias_uteis_entre` evitava o crash).

**Impacto:** 67 dos 84 clientes elegíveis pra streak eram filtrados silenciosamente. Cliente 1497 (Igreja Plenitude Da Bencao) foi o caso emblemático — caía no lote todo dia por semanas.

**Fix:** Import lazy `from data import eh_feriado` dentro de `dias_uteis_entre` (evita circular import). Commit `cb44360` em 2026-07-08.

**Aprendizado:** Trocar `except Exception: pass` por logging estruturado nas funções críticas — bug ficou 9 dias em produção sem detecção.

### Cliente inadimplente sumia de MoM enquanto WoW virava (comportamento, não bug)

**Sintoma reportado:** Card p.p. do NPL sempre vermelho (30d MoM).

**Investigação:** É comportamento correto — inadimplência cresceu mesmo no acumulado do mês. WoW (7d) foi adicionado e depois removido a pedido (usuário achou que não ajudava). Só MoM está em produção agora.

### `nao_cobrar` não persistia em get_effective_status (2026-07-09)

**Sintoma:** Cliente marcado como "Não cobrar" tinha o status sobrescrito por "contacted" ou "pending" na tela Inadimplência (enquanto "Telefone errado" e "Igreja fechada" apareciam certos).

**Causa:** Lista hardcoded em `helpers.get_effective_status` não incluía `nao_cobrar`.

**Fix:** Adicionar `nao_cobrar` à tupla. Commit `a9c5a3a` em 2026-07-09.

### Admin não filtrava STATUS_SEM_CONTATO no kanban (2026-07-09)

**Sintoma:** Cards marcados pelas atendentes como "Não cobrar" / "Telefone errado" continuavam aparecendo pro admin no kanban.

**Causa:** Kanban usava `get_hist` (histórico do próprio uid logado). Admin não tinha marcações — filtro não removia.

**Fix:** Trocar por `get_hist_unificado` (união dos históricos das atendentes quando role=admin). Commit `b06ad30`.

### Bug UnboundLocalError no dialog (2026-07-09)

**Sintoma:** Streamlit Cloud erro `UnboundLocalError: name 'parse_date_br' is not defined`.

**Causa:** Import local `from helpers import parse_date_br` dentro da função `dialog_editar` fazia Python tratar a variável como local em todo o escopo — mas o uso vinha antes do import.

**Fix:** Remover import redundante (já importado no topo). Commit `d379467`.

---

## Changelog

| Versão | Data | Autor | O que mudou |
|---|---|---|---|
| 1.0 | 2026-05-14 | Davi Machado | Criação da documentação consolidada (migração de 6 arquivos + 3 ADRs) |
| 1.1 | 2026-07-16 | Caio Cadete | Atualização aprofundada: reflete código real (paths, arquivos, tabelas BQ vs Postgres), adiciona status especiais (nao_cobrar, telefone_errado, igreja_fechada), detalha cooldown/streak com fix do bug, adiciona ADRs 4-6, seção de bugs históricos, custos BQ, cron GitHub Actions |

---

## Ver também

- [[bigquery-regras]] — regras críticas de join e tipos de dados BQ_BI
- [[inadimplencia]] — janela rolante, implementação numpy
- [[FIN] Dashboard_Financeiro]] — painel financeiro com página de inadimplência relacionada
