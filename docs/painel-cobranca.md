---
date: 2026-05-14
updated: 2026-05-14
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

---

## Visão Estratégica

### SIPOC

| Suppliers | Inputs | Process | Outputs | Customers |
|---|---|---|---|---|
| BigQuery | Cobranças em aberto, liquidações, grupos, clientes | 1. Carregar carteira e calcular atraso | Painel de inadimplência com priorização | Atendentes |
| n8n / Postgres | Histórico recente de mensagens e ligações | 2. Enriquecer com status e cooldown do dia | Estado de contato e alertas | Gestores |
| Google OAuth | Identidade do usuário | 3. Montar lote diário de ligação e mensagem | Lote diário auditável | Admin / BI |
| Operação de cobrança | Interações registradas no dia | 4. Salvar histórico e regularizados | Histórico persistido no BQ | — |

### Ficha Estratégica

**Propósito:** Reduzir inadimplência com priorização diária e rastreabilidade por cliente.
**Gatilho:** Abertura do app, clique em "Atualizar" ou virada do dia operacional (08:15 BRT).
**Frequência:** Diário, com interação contínua durante o expediente.

**KPIs do Processo**

| KPI | Referência |
|---|---|
| Disponibilidade da carteira | Visível no início da operação |
| Lote do dia | Disponível até a virada às 08:15 BRT |
| Cache de fallback | `cache_dados.json` — até 1h de defasagem aceitável |

**Dependências críticas**
- BigQuery (`Splgc.splgc-cobrancas_competencia-all`, `splgc-cobrancas_liquidacao-all`, `splgc-grupo`)
- Postgres do n8n (`painel_historico`, `painel_tarefas_diarias`)
- Credenciais Google OAuth + `secrets.toml`

**Riscos e Mitigações**

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Atraso de dados no BQ | Média | Alto | Cache local `cache_dados.json` como fallback |
| BQ indisponível | Baixa | Alto | App continua operacional com cache; clicar Atualizar quando normalizar |
| Credenciais expiradas | Baixa | Alto | Verificar secrets.toml e renovar OAuth |
| Cache desatualizado | Média | Médio | Botão "Atualizar" recarrega do BQ e regrava cache |

### Value Stream Map

```
[Carregamento] → [Priorização] → [Contato] → [Registro] → [Publicação]
     5 min           10 min        15 min       5 min         2 min

Tempo de valor agregado: 37 min
Lead time real: variável (depende do BQ, n8n e ação humana)
Oportunidade: reduzir dependência de recarga manual e atrasos de sincronização
```

---

## RACI

| Etapa | Atendente | Gestor | Sistema / Automação | Admin / BI |
|---|---|---|---|---|
| Autenticação | I | I | R | **A** |
| Carga da carteira | I | I | R | **A** |
| Priorização do lote | I | C | R | **A** |
| Atendimento do cliente | **R** | I | C | I |
| Edição do histórico | **R** | I | C | I |
| Revisão da carteira | I | **R** | C | A |
| Manutenção de integrações | I | I | C | **R** |
| Publicação de mudanças de regra | I | C | C | **A** |

---

## Guia Rápido

### Como acessar
1. Acesse a aplicação Streamlit e clique em **Continuar com Google**
2. Use uma conta do domínio interno autorizada
3. Se a conta não tiver acesso: solicitar inclusão ao Admin/BI

### Navegação por tela

| Tela | Para que serve |
|---|---|
| **Atividades** | Operação diária — cards priorizados por score, registrar contato |
| **Inadimplência** | Carteira completa — atualizar, filtrar, exportar CSV |
| **Próximas Cobranças** | Antecipar vencimentos futuros por período |
| **Regularizados** | Clientes que liquidaram — revisar e exportar |
| **Cliente** | Visão detalhada de um cliente específico |

### O que acontece após cada ação

| Ação | Resultado |
|---|---|
| Login | Sessão criada, carteira começa a carregar |
| Atualizar dados (Inadimplência) | App busca BQ → regrava `cache_dados.json` |
| Salvar atendimento | Histórico salvo na sessão, cache local e BQ |
| Registrar interação no lote | Alimenta painel de tarefas e atualiza badges do card |
| Sair | Sessão encerrada, dados de autenticação removidos |

### Erros comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| Carteira vazia | Falha de carga ou cache sem dados | Clicar Atualizar; verificar credenciais BQ |
| Login não avança | Conta sem autorização | Conferir se e-mail está cadastrado em `st.secrets` |
| Histórico desatualizado | Dados recentes ainda não chegaram ao BQ | Aguardar sincronização do n8n ou recarregar sessão |

### Perfis de uso
- **Atendente:** opera lista diária, registra contato e acompanha retorno
- **Gestor:** acompanha carteira e indicadores (leitura e supervisão)
- **Admin/BI:** mantém credenciais, integrações, estrutura de dados e regras

---

## Documentação Técnica

**Localização:** `C:\Claude_Files\streamlite_dashboards\cobranca\` *(confirmar path exato)*
**Como rodar localmente:** `streamlit run app.py` dentro do diretório do projeto

### Estrutura de arquivos

```
cobranca/
├── app.py              ← orquestração de navegação + callback OAuth popup
├── auth.py             ← store de sessão, valida login local e Google
├── data.py             ← consulta BQ, histórico n8n, lote diário, score, cache
├── helpers.py          ← normaliza datas, telefones, badges, histórico
├── cache_dados.json    ← fallback local da carteira
└── views/
    ├── login.py
    ├── sidebar.py
    ├── header.py
    ├── dashboard.py
    ├── atividades.py
    ├── cliente.py
    ├── historico.py
    ├── proximas_cobrancas.py
    └── dialogo_edicao.py
```

### C4 — Contexto

```
Usuário interno → Streamlit InChurch Cobranças → BigQuery
                                               → Postgres n8n
                                               → Google OAuth
                                               → cache_dados.json
```

### C4 — Containers

```
app.py (orquestração) → auth.py (sessão / autenticação)
                      → data.py (carga / lote / persistência) → BigQuery
                                                              → Postgres n8n
                                                              → cache_dados.json
                      → views/ (telas)
                      → helpers.py (regras de data / formato / histórico)
```

### Fluxo de execução

1. App sobe: define layout, tema e CSS global
2. Callback OAuth tratado quando login ocorre em popup
3. Sidebar renderizada e sessão validada
4. Carteira carregada do `cache_dados.json`; se necessário, busca do BQ
5. Histórico recente do n8n e cooldowns do painel carregados uma vez por sessão
6. Navegação escolhe a view ativa

### BPMN — Fluxo Operacional

```
(Início)
  ↓
[Usuário acessa o painel]
  ↓
{Autenticado?}
  → Não → [Tela de login] → [Login Google ou local] → {Autenticado?}
  → Sim → [Carrega cache e dados do BQ]
            ↓
         [Exibe atividades / inadimplência / próximas cobranças]
            ↓
         {Há cliente para agir?}
           → Sim → [Registrar contato / retorno / promessa]
                     ↓
                   [Salvar histórico e atualizar painel]
                     ↓
                   (Fim)
           → Não → [Consultar relatórios e filtros]
                     ↓
                   (Fim)
```

---

## Dicionário de Dados

### Store da sessão (`store`)

| Campo | Tipo | Valores / Observações |
|---|---|---|
| `store.clientes[].id` | STRING | Chave principal na aplicação |
| `store.clientes[].valor` | FLOAT | `> 0` para entrar na carteira |
| `store.clientes[]._tem_acordo` | BOOLEAN | Indica cobrança com acordo vencido |
| `store.clientes[]._inativo` | BOOLEAN | Cliente desativado na base |
| `store.clientes[]._nova_cobranca` | BOOLEAN | Cobrança nova no dia |
| `store.historico[uid][cliente_id].status` | STRING | `pending`, `contacted`, `promise`, `negotiating`, `paid` |
| `store.historico[uid][cliente_id].lastContact` | STRING | Data do último contato |
| `store.historico[uid][cliente_id].retorno` | STRING | Data agendada de retorno |
| `store.historico[uid][cliente_id].promiseDate` | STRING | Data prometida para pagamento |
| `store.historico[uid][cliente_id].atendente` | STRING | Usuário que salvou |
| `store.regularizados` | ARRAY | Liquidações e saídas da carteira do dia |
| `store.ultima_atualizacao` | STRING | Timestamp da última carga |

### Tabelas BigQuery consumidas

| Tabela | Projeto | Uso |
|---|---|---|
| `Splgc.splgc-cobrancas_competencia-all` | BQ_BI | Cobranças em aberto — base principal da carteira |
| `Splgc.splgc-cobrancas_liquidacao-all` | BQ_BI | Liquidações — alimenta regularizados e histórico |
| `Splgc.splgc-grupo` | BQ_BI | Grupo/carteira do cliente (priorização por atendente) |
| `Splgc.splgc-clientes-inchurch` | BQ_BI | Telefone auxiliar (fallback) |
| `painel_historico` | BQ | Histórico por usuário e cliente; versão mais recente por `updated_at` |
| `painel_tarefas_diarias` | BQ | Fonte de verdade do lote diário e cooldowns |

### Status e valores válidos

| Campo | Valores | Significado |
|---|---|---|
| `status` | `pending` / `contacted` / `promise` / `negotiating` / `paid` | Estado do atendimento |
| `bucket` | `ligacao` / `mensagem` | Tipo de ação do lote diário |
| `dias_atraso` | INT ou nulo | Atraso em dias pela data de vencimento |

---

## ADRs

### ADR-001: BigQuery como fonte principal com cache local

**Status:** Aceito

**Contexto:** A carteira precisa estar disponível mesmo quando o BQ falha ou demora. O app também precisa responder rápido na navegação cotidiana.

**Decisão:** BQ como fonte principal; espelho local em `cache_dados.json` para fallback imediato.

**Consequências**
- Positivo: app continua útil em falhas temporárias; reduz custo de reconexão durante a sessão
- Negativo: risco de exibir dados levemente defasados se o BQ não for recarregado
- Trade-off aceito: consistência eventual em troca de disponibilidade e velocidade

**Alternativas descartadas**
- Sempre buscar do BQ: maior latência e dependência de disponibilidade
- Somente em memória: perde estado ao reiniciar a sessão

---

### ADR-002: n8n/Postgres para interações recentes e BQ para estado consolidado

**Status:** Aceito

**Contexto:** Interações recentes chegam pelo n8n mais rápido do que a consolidação final do BQ. A geração do lote diário precisa de uma fonte estável para cooldowns e marcações.

**Decisão:** Histórico recente de mensagens e ligações lido do Postgres do n8n; estado consolidado do painel gravado e consultado em `painel_tarefas_diarias` no BQ.

**Consequências**
- Positivo: atendente enxerga sinais quase em tempo real; lote do dia fica auditável
- Negativo: duas fontes diferentes para informações de contato — regra de precedência deve ser documentada
- Trade-off aceito: n8n para eventos recentes, BQ para estado persistente

**Alternativas descartadas**
- Tudo no n8n: frágil para relatórios e histórico persistente
- Tudo no BQ: painel menos responsivo para contatos do dia

---

### ADR-003: Virada do lote às 08:15 BRT com quotas e caps de inativos

**Status:** Aceito

**Contexto:** A operação precisa evitar gerar lote antes que a base da noite anterior esteja refletida e manter distribuição controlada.

**Decisão:** Dia operacional vira às 08:15 BRT. Lote: 30 ligações e 50 mensagens, com cap de 10 inativos em ligação e 15 em mensagem. Fallback: inativos sem acordo sorteados para completar a fila se necessário.

**Consequências**
- Positivo: reduz falsa priorização por pagamento não refletido; dá previsibilidade à operação
- Negativo: regra exige documentação clara — não é intuitivo para quem usa o painel
- Trade-off aceito: corte operacional diferente do calendário civil em troca de qualidade de fila

**Alternativas descartadas**
- Virar à meia-noite: risco de lote desatualizado
- Sem limite de inativos: pioraria eficiência da carteira ativa

---

## Referência

### Status de cobrança

| Chave | Rótulo | Uso |
|---|---|---|
| `pending` | Sem contato | Estado inicial |
| `contacted` | Contactado | Houve contato, sem encerramento |
| `promise` | Prometeu pagar | Cliente assumiu compromisso |
| `negotiating` | Negociando | Negociação em andamento |
| `paid` | Regularizado | Cobrança quitada |

### Regras de priorização do lote

| Regra | Valor padrão |
|---|---|
| Itens por página na carteira | 50 |
| Dias sem contato para pendência | 5 |
| Lote diário de ligação | 30 |
| Lote diário de mensagem | 50 |
| Inativos máximos em ligação | 10 |
| Inativos máximos em mensagem | 15 |
| Virada do dia operacional | 08:15 BRT |

### Campos do painel de tarefas diárias

| Campo | Significado |
|---|---|
| `dt_mensagem_enviada` | Início da ação de mensagem no dia |
| `dt_ligacao_feita` | Tentativa de ligação no dia |
| `dt_ligacao_atendida` | Ligação atendida no dia |
| `mensagem_enviada` | Booleano — ação ocorreu |
| `ligacao_feita` | Booleano — ação ocorreu |
| `ligacao_atendida` | Booleano — ligação concluída |

---

## Changelog

| Versão | Data | Autor | O que mudou |
|---|---|---|---|
| 1.0 | 2026-05-14 | Davi Machado | Criação da documentação consolidada (migração de 6 arquivos + 3 ADRs para formato único) |

---

## Ver também

- [[bigquery-regras]] — regras críticas de join e tipos de dados BQ_BI
- [[inadimplencia]] — janela rolante, implementação numpy
- [[FIN] Dashboard_Financeiro]] — painel financeiro com página de inadimplência relacionada
