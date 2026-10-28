import base64
from pathlib import Path


# Versao do codigo no ar. Serve pra responder "o deploy pegou?" sem
# adivinhacao: o rodape da sidebar mostra isso, e se nao bater com o que
# acabou de subir, o painel esta rodando codigo velho. Bumpar a cada deploy
# que mude comportamento visivel.
VERSAO = "2026.10.20-ipca"
# A versao do PRODUTO, que e a que aparece na sidebar. A VERSAO acima e
# a do build: muda a cada deploy e serve pra conferir o que subiu, nao
# pra ocupar espaco na tela da atendente.
VERSAO_CURTA = "2.0"


# ── Paginação e regras ────────────────────────────────────────────────────────
PAGE_SIZE        = 50

# ── Ordenação da tabela ───────────────────────────────────────────────────────
SORT_MAP = {
    "↑ Maior score":  ("_score",      False),
    "↓ Menor score":  ("_score",      True),
    "↑ Maior atraso": ("dias_atraso", False),
    "↓ Menor atraso": ("dias_atraso", True),
    "↑ Maior saldo":  ("valor",       False),
    "↓ Menor saldo":  ("valor",       True),
    "↑ Tempo de login": ("_ultimoLoginOrdem", False),
    "↓ Tempo de login": ("_ultimoLoginOrdem", True),
    "Nome A→Z":       ("nome",        True),
    "Nome Z→A":       ("nome",        False),
}

# ── Status ────────────────────────────────────────────────────────────────────
STATUS_LABELS = {
    "pending":          "Sem contato",
    "contacted":        "Contactado",
    "promise":          "Prometeu pagar",
    "negotiating":      "Negociando",
    "telefone_errado":  "Telefone errado",
    "igreja_fechada":   "Igreja fechada",
    "nao_cobrar":       "Não cobrar",
}
STATUS_COLORS = {
    "pending":          "#ef4444",
    "contacted":        "#f59e0b",
    "promise":          "#f97316",
    "negotiating":      "#5fa3ff",
    "telefone_errado":  "#9ca3af",  # cinza neutro — sem urgência operacional
    "igreja_fechada":   "#6b7280",  # cinza mais escuro — encerramento definitivo
    "nao_cobrar":       "#4b5563",  # cinza escuro — bloqueio administrativo
}
# Status que IMPEDEM o cliente de cair no lote do dia (atendente nao consegue
# contatar). Cliente continua aparecendo nas outras telas, so e' excluido
# da geracao do lote operacional e do kanban de hoje.
STATUS_SEM_CONTATO = {"telefone_errado", "igreja_fechada", "nao_cobrar"}

# Chave de exibição → chave interna (usado no dropdown de edição do dialog).
# Apenas DECISOES INTENCIONAIS da atendente. 'Sem contato' (pending) e
# 'Contactado' (contacted) sao gerenciados EXCLUSIVAMENTE pela funcao
# get_effective_status (helpers.py) com base em atividade do N8N/painel —
# nao aparecem como opcoes pra evitar conflito com a logica automatica
# (atendente nao deve poder anular ou contradizer o estado real).
STATUS_OPTS = {
    "Prometeu pagar":   "promise",
    "Negociando":       "negotiating",
    "Telefone errado":  "telefone_errado",
    "Igreja fechada":   "igreja_fechada",
    "Não cobrar":       "nao_cobrar",
}
# Rótulo da pill → chave interna  (usado no filtro do dashboard)
STATUS_FILTER_MAP = {
    "Sem contato":      "pending",
    "Contactado":       "contacted",
    "Prometeu pagar":   "promise",
    "Negociando":       "negotiating",
    "Telefone errado":  "telefone_errado",
    "Igreja fechada":   "igreja_fechada",
    "Não cobrar":       "nao_cobrar",
}

# ── Logo ──────────────────────────────────────────────────────────────────────
# Sao duas artes da mesma marca, nao duas versoes da mesma imagem: a do painel
# tem a palavra "inchurch" em BRANCO (feita pro fundo escuro) e no modo claro
# ela simplesmente desaparece, sobrando os quadradinhos verdes soltos. A da
# proposta tem a palavra em cinza-escuro — e a mesma que vai no PDF do acordo,
# entao nao e um asset novo pra manter.
def _b64(nome):
    p = Path(__file__).parent / nome
    if not p.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


LOGO_SRC       = _b64("inchurch_logo.png")           # texto branco  → escuro
LOGO_SRC_CLARO = _b64("inchurch_logo_proposta.png")  # texto cinza   → claro


def logo_src(claro: bool = False) -> str:
    """A arte certa pro tema. Cai na do painel se a outra sumir do disco."""
    return (LOGO_SRC_CLARO or LOGO_SRC) if claro else LOGO_SRC

# ── Tema ──────────────────────────────────────────────────────────────────────
# As cores do painel sempre foram hexadecimais escritos a mao dentro das
# f-strings que montam o HTML — 580 deles, em 11 arquivos, sem nenhuma
# variavel. Estilo inline vence qualquer folha de estilo, entao nao havia
# como trocar de tema por fora: cada elemento carregava a propria cor.
#
# Todas as telas ja leem estes tokens — menos a de login, que roda antes do
# session_state do tema existir e carrega as cores de marca do Google.
#
# Os valores do modo claro NAO sao o escuro invertido. Verde #7cc243 tem
# contraste bom sobre #181c26 e fica lavado sobre branco, entao vira #4a8a2c;
# o mesmo vale pro ambar e pro azul. Trocar so o fundo deixaria texto
# ilegivel.
_TOKENS_ESCURO = {
    "bg":        "#0f1117",   # fundo da pagina
    "surface":   "#181c26",   # card
    "surface-2": "#1e2333",   # card dentro de card / divisor
    "surface-3": "#13161f",   # fundo de linha
    "border":    "#2a2f42",
    "border-2":  "#1f2433",
    "txt":       "#e8eaf0",   # texto principal
    "txt-2":     "#9ca3af",   # secundario
    "txt-3":     "#6b7280",   # apagado
    "txt-4":     "#4b5563",   # mais apagado ainda
    "brand":     "#7cc243",   # verde da marca
    "ok":        "#22c55e",
    "alerta":    "#f59e0b",
    "erro":      "#ef4444",
    "erro-2":    "#ff5555",
    "info":      "#5fa3ff",
    "roxo":      "#a78bfa",
    "rosa":      "#fb7185",
    "laranja":     "#ff9800",
    "laranja-2":   "#ffb84d",
    "laranja-3":   "#f97316",
    "amarelo":     "#fcd34d",
    "amarelo-2":   "#fde68a",
    "azul-2":      "#4f7cff",
    "erro-3":      "#ff4444",
    "erro-4":      "#ff6b6b",
    "brand-2":     "#8fd44e",
    "brand-3":     "#a3d672",
    "brand-esc":   "#3e7a1f",
    "brand-esc2":  "#2d5a14",
    "border-3":    "#3d4460",
    "txt-inv":     "#ffffff",
    "txt-claro":   "#c7cede",
    "cinza-cl":    "#cbd5e1",
}
_TOKENS_CLARO = {
    "bg":        "#f5f6f8",
    "surface":   "#ffffff",
    "surface-2": "#eef0f4",
    "surface-3": "#f8f9fb",
    "border":    "#d4d9e2",
    "border-2":  "#e5e8ee",
    "txt":       "#1a1d26",
    "txt-2":     "#5b6472",
    "txt-3":     "#78818f",
    "txt-4":     "#9aa2ae",
    "brand":     "#4a8a2c",   # escurecido: #7cc243 some no branco
    "ok":        "#15803d",
    "alerta":    "#b45309",
    "erro":      "#dc2626",
    "erro-2":    "#dc2626",
    "info":      "#1d4ed8",
    "roxo":      "#6d28d9",
    "rosa":      "#be123c",
    "laranja":     "#c2410c",
    "laranja-2":   "#ea580c",
    "laranja-3":   "#c2410c",
    "amarelo":     "#a16207",
    "amarelo-2":   "#ca8a04",
    "azul-2":      "#1e40af",
    "erro-3":      "#dc2626",
    "erro-4":      "#e11d48",
    "brand-2":     "#3f7a24",
    "brand-3":     "#4a8a2c",
    "brand-esc":   "#2d5a14",
    "brand-esc2":  "#1e3d0d",
    "border-3":    "#c3c9d4",
    "txt-inv":     "#ffffff",
    "txt-claro":   "#3a4150",
    "cinza-cl":    "#64748b",
}


def css_tema(claro: bool = False) -> str:
    """Bloco <style> com os tokens do tema escolhido.

    Injetado DEPOIS do CSS global pra vencer na cascata — os dois definem
    :root, e o ultimo ganha.
    """
    t = _TOKENS_CLARO if claro else _TOKENS_ESCURO
    regras = "".join(f"--{k}:{v};" for k, v in t.items())
    extra = ""
    if claro:
        # O fundo e as superficies do proprio Streamlit nao leem nossos
        # tokens — precisam ser ditos na mao.
        extra = (
            "html,body,[class*='css'],.stApp{background:var(--bg)!important;"
            "color:var(--txt)!important}"
            "section[data-testid='stSidebar']{background:var(--surface)!important;"
            "border-right:1px solid var(--border)!important}"
        )
    return f"<style>:root{{{regras}}}{extra}</style>"


# ── CSS global ────────────────────────────────────────────────────────────────
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@300;400;500&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif!important;background:var(--bg)!important;color:var(--txt)!important;font-size:20px!important}
#MainMenu,footer,header{visibility:hidden}
/* ...MENOS o botao de reabrir a sidebar, que o Streamlit renderiza dentro
   do <header>. Esconder o header inteiro deixava a sidebar fechar e nunca
   mais abrir — foi o que derrubou a tentativa anterior. visibility (e nao
   display) justamente porque da pra reverter no filho. O testid certo e
   stExpandSidebarButton; o "collapsedControl" que estava no CSS nao existe
   mais no Streamlit 1.59 e aquela regra nao casava com nada. */
[data-testid="stExpandSidebarButton"],
[data-testid="stExpandSidebarButton"] *{visibility:visible!important}
[data-testid="stExpandSidebarButton"]{opacity:.55;z-index:130!important}
[data-testid="stExpandSidebarButton"]:hover{opacity:1}
.block-container{padding-top:0!important;padding-bottom:1.5rem!important;max-width:100%!important;padding-left:2rem!important;padding-right:2rem!important}

/* ── Sidebar ──────────────────────────────────────────────────────────────
   Recolhivel. O Streamlit ja sabe fazer isso sozinho; o que impedia eram
   tres regras daqui, e vale registrar quais pra ninguem reintroduzir:

     transform:translateX(0)!important   prendia ela aberta. Mesmo com o
                                         Streamlit marcando aria-expanded
                                         ="false", o transform trazia de volta.
     [data-testid="collapsedControl"]    e o botao de REABRIR, e vive FORA da
       display:none                      sidebar. Escondido, dava pra fechar e
                                         nunca mais abrir.
     stSidebarCollapseButton             o botao de recolher, dentro dela.
       display:none

   Agora as regras de largura e transform sao presas a aria-expanded="true",
   e o estado "false" tem as suas. Sem isso o !important da largura vence o
   colapso do Streamlit e a sidebar fecha pela metade. */
section[data-testid="stSidebar"]{background:var(--surface-3)!important;border-right:1px solid var(--surface-2)!important;position:relative!important;z-index:100!important;transition:width .2s ease,transform .2s ease!important}
section[data-testid="stSidebar"][aria-expanded="true"]{min-width:250px!important;width:250px!important;transform:translateX(0)!important;display:block!important;visibility:visible!important;opacity:1!important}
section[data-testid="stSidebar"][aria-expanded="true"] > div:first-child{width:250px!important;padding:0!important;display:block!important}
section[data-testid="stSidebar"][aria-expanded="false"]{min-width:0!important;width:0!important;transform:translateX(-250px)!important;overflow:visible!important;border-right:none!important}
/* O cabecalho nativo some (a sidebar ja tem logo propria), mas o botao de
   recolher mora dentro dele — entao escondo o logo nativo, nao o header. */
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"]{padding:0!important;min-height:0!important;height:0!important}
section[data-testid="stSidebar"] [data-testid="stSidebarLogo"],
section[data-testid="stSidebar"] [data-testid="stLogoSpacer"]{display:none!important}
/* Aparece quando o mouse entra na sidebar — comportamento nativo do
   Streamlit (onMouseOver no stSidebarContent), e o Caio preferiu assim:
   mais limpo que um botao permanente no canto. Aqui so o posicionamento. */
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"]{display:block!important;position:absolute!important;top:8px;right:6px;z-index:120!important}
.main .block-container{margin-left:0!important}

/* Botões da sidebar */
section[data-testid="stSidebar"] .stButton>button{
  background:transparent!important;color:var(--txt-2)!important;border:none!important;
  border-radius:8px!important;font-size:13px!important;font-weight:500!important;
  padding:10px 16px!important;text-align:left!important;justify-content:flex-start!important;
  width:100%!important;transition:all 0.18s!important;box-shadow:none!important;
  letter-spacing:0.2px!important
}
section[data-testid="stSidebar"] .stButton>button:hover{
  background:rgba(124,194,67,.1)!important;color:var(--brand)!important;transform:none!important
}
/* O gap padrao de 1rem entre blocos, vezes 6 itens, custa ~96px de altura e
   empurrava a navegacao contra o 'Sair' fixo do rodape. 0.15rem resolvia a
   altura mas colava o "Lote do Dia" na borda do cabecalho — 0.3rem e o meio
   termo, com um respiro explicito antes do primeiro item. */
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:0.3rem!important}
/* O respiro antes do "Lote do Dia" mora na margem do cabecalho, nao num
   :first-of-type do bloco — aquele seletor pegava o PROPRIO cabecalho (ele
   tambem e um stElementContainer), entao empurrava o logo pra baixo e
   deixava o primeiro item colado na borda, que era o defeito. */
section[data-testid="stSidebar"] .stButton:first-of-type{margin-top:10px!important}
/* nowrap porque rotulo de navegacao quebrado em duas linhas desalinha a
   lista inteira: cada item passa a ter altura diferente do vizinho. */
section[data-testid="stSidebar"] .stButton>button p{line-height:1.3!important;margin:0!important;white-space:nowrap!important}
/* Em tela estreita a sidebar vai a 200px (nao 190): "Resultados da Cobranca"
   e o rotulo mais longo e, a 12px com o padding menor, cabe em uma linha. */
@media (max-width:1500px){
  section[data-testid="stSidebar"] .stButton>button{padding:8px 10px!important;font-size:12px!important;letter-spacing:0!important}
}

/* ── Cards de métrica ── */
.metric-card{background:var(--surface);border:1px solid var(--surface-2);border-radius:14px;padding:20px 22px;box-shadow:0 1px 6px rgba(0,0,0,.15);transition:box-shadow .2s;min-height:130px;display:flex;flex-direction:column;justify-content:space-between}
.metric-card:hover{box-shadow:0 4px 16px rgba(0,0,0,.25)}
.metric-label{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:var(--txt-2);margin-bottom:10px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.metric-value{font-family:'DM Sans',sans-serif;font-size:34px;font-weight:700;line-height:1;letter-spacing:0;font-variant-numeric:tabular-nums}
.metric-sub{font-size:13px;color:var(--txt-3);margin-top:8px;letter-spacing:0.2px}

/* ── Badges ── */
.badge{display:inline-block;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:600}
.badge-pending{background:rgba(239,68,68,.12);color:var(--erro-2)}
.badge-contacted{background:rgba(245,158,11,.12);color:var(--laranja-2)}
.badge-promise{background:rgba(249,115,22,.12);color:var(--laranja)}
.badge-negotiating{background:rgba(79,124,255,.12);color:var(--info)}
.badge-paid{background:rgba(34,197,94,.12);color:var(--ok)}
.tag-novo{white-space:nowrap;background:rgba(34,197,94,.15);color:var(--ok);font-size:9px;padding:2px 5px;border-radius:5px;font-weight:700;margin-right:3px}
.tag-upd{white-space:nowrap;background:rgba(245,158,11,.15);color:var(--laranja-2);font-size:9px;padding:2px 5px;border-radius:5px;font-weight:700;margin-right:3px}
.top-badge{white-space:nowrap;background:rgba(239,68,68,.18);color:var(--erro-4);font-size:9px;padding:2px 5px;border-radius:5px;font-weight:700;margin-right:3px}
.tag-nova-cob{white-space:nowrap;background:rgba(79,124,255,.18);color:var(--info);font-size:9px;padding:2px 5px;border-radius:5px;font-weight:700;margin-right:3px}

/* ── Atraso chips ── */
/* Botao de editar da tabela: a coluna e' estreita (~32px) e o padding padrao
   de 15px de cada lado nao cabe — sobram 2px de content-box, o conteudo e'
   empurrado e o lapis sai do centro. Em monitor grande a coluna e' maior e o
   efeito some, por isso so' aparecia em notebook. */
[class*="st-key-edit_"] button{padding-left:2px!important;padding-right:2px!important;min-width:0!important}
/* Grupo sempre em 2 linhas quando o nome tem espaco: "Priscila" em cima,
   "Oliveira" embaixo. A quebra e' EXPLICITA (dois spans), nao deixada pro
   navegador — era o que produzia "Ana / Carolin / a". nowrap em cada parte
   impede quebra por dentro da palavra. Era gated por media query, mas
   notebook de 1920 nao disparava o breakpoint e ficava numa linha so'. */
span.g-nome,span.g-sobre{white-space:nowrap;display:block}
.da{padding:2px 7px;border-radius:6px;font-size:14px;font-weight:700;display:inline-block}
.da-ok{background:rgba(45,211,111,.12);color:var(--ok)}
.da-30{background:rgba(255,184,77,.12);color:var(--laranja-2)}
.da-60{background:rgba(255,152,0,.12);color:var(--laranja)}
.da-90{background:rgba(255,85,85,.12);color:var(--erro-2)}
.da-max{background:rgba(200,0,0,.18);color:var(--erro-3)}

/* ── Pendência card ── */
.pend-card{background:var(--surface);border:1px solid var(--surface-2);border-radius:10px;padding:14px 16px;margin-bottom:8px}

/* ── Botões globais ── */
.stButton>button{background:var(--surface-2)!important;color:var(--txt)!important;font-weight:600!important;border:1px solid var(--border)!important;border-radius:8px!important;font-size:15px!important;padding:0.5rem 1.1rem!important;transition:all 0.18s!important;box-shadow:none!important}
.stButton>button:hover{background:var(--border)!important;border-color:var(--border-3)!important;transform:none!important;box-shadow:none!important}
button[kind="primary"]{background:var(--brand)!important;color:var(--bg)!important;border:none!important;font-weight:700!important}
button[kind="primary"]:hover{background:var(--brand-2)!important}

/* Sidebar nav ativa: override do primary global (verde solido) — na
   sidebar queremos fundo verde translucido + texto verde (mesma
   linguagem do hover, so que persistente). Sinaliza pagina atual sem
   competir com CTAs primary de outras telas. */
section[data-testid="stSidebar"] .stButton>button[kind="primary"]{
  background:rgba(124,194,67,.12)!important;color:var(--brand)!important;
  border:none!important;font-weight:600!important
}
section[data-testid="stSidebar"] .stButton>button[kind="primary"]:hover{
  background:rgba(124,194,67,.18)!important;color:var(--brand)!important
}

/* ── Inputs ── */
.stTextInput input,.stTextArea textarea{background:var(--surface)!important;color:var(--txt)!important;border:1px solid var(--surface-2)!important;border-radius:8px!important;font-size:15px!important;padding:0.6rem 0.9rem!important}
.stTextInput input:focus,.stTextArea textarea:focus{border-color:var(--brand)!important;box-shadow:0 0 0 2px rgba(124,194,67,.15)!important}
/* <<fix-base>> (marcador: amostra_tema.py corta daqui ate <</fix-base>> pra
   mostrar como fica SEM estas regras — nao remover) */
/* O .streamlit/config.toml fixa base="dark", e o Streamlit usa isso pra
   escolher sozinho o cinza de tres coisas que nunca passam pelo nosso CSS:
   o texto do placeholder, o texto de campo desabilitado e o icone do X do
   dialog. Como o base nao muda junto com o tema, no modo claro esses tres
   saem no cinza-claro de fundo escuro e somem no branco. Aqui eles passam a
   ler os tokens — vale pros dois temas, so que no escuro ja estava passavel.

   O -webkit-text-fill-color nao e redundante: em campo :disabled o Chrome
   ignora 'color' e usa ele. So com os dois o "Ultimo Contato" aparece. */
.stTextInput input::placeholder,.stTextArea textarea::placeholder,
input::placeholder,textarea::placeholder{color:var(--txt-3)!important;opacity:1!important}
input:disabled,textarea:disabled,
.stTextInput input:disabled,.stDateInput input:disabled{
  color:var(--txt-2)!important;-webkit-text-fill-color:var(--txt-2)!important;opacity:1!important
}
/* Placeholder do selectbox ("Apenas para decisoes manuais") — baseweb nao usa
   ::placeholder aqui, e um div proprio. */
div[data-baseweb="select"] [class*="placeholder"]{color:var(--txt-3)!important}
/* O X do dialog nao tem testid: e button[aria-label="Close"] com um svg de
   10x10 dentro. */
[data-testid="stDialog"] button[aria-label="Close"]{
  background:transparent!important;border:none!important;
  color:var(--txt-2)!important;opacity:1!important
}
[data-testid="stDialog"] button[aria-label="Close"]:hover{color:var(--txt)!important}
[data-testid="stDialog"] button[aria-label="Close"] svg,
[data-testid="stDialog"] button[aria-label="Close"] svg path{fill:currentColor!important}
/* <</fix-base>> */
/* stNumberInput faltava nesta lista: os dois campos de desconto da proposta
   saiam na fonte do user-agent, do lado de "PARCELAMENTO" que e selectbox e
   pegava a regra. Sao os unicos number_input do app. */
.stTextInput label,.stTextArea label,.stSelectbox label,.stMultiSelect label,.stDateInput label,.stNumberInput label{color:var(--txt-3)!important;font-size:13px!important;text-transform:uppercase!important;letter-spacing:0.8px!important;font-weight:600!important}
div[data-baseweb="select"]>div{background:var(--surface)!important;border-color:var(--surface-2)!important;border-radius:8px!important}
div[data-baseweb="select"] span{color:var(--txt)!important;font-size:12px!important}
div[data-baseweb="popover"],div[data-baseweb="menu"]{background:var(--surface)!important;border:1px solid var(--border)!important;border-radius:10px!important}
div[data-baseweb="menu"] li{color:var(--txt)!important;font-size:13px!important}
div[data-baseweb="menu"] li:hover{background:var(--surface-2)!important}
/* Chips do multiselect: mesma paleta dos selects, pra Grupo e
   Ordenar nao destoarem da fileira de filtros. */
span[data-baseweb="tag"]{background:var(--border)!important;border-radius:6px!important}
span[data-baseweb="tag"] span{color:var(--txt)!important;font-size:12px!important}

/* Em tela estreita o gap padrao de 1rem entre as 10 colunas da tabela custa
   ~144px — mais da metade do que a sidebar inteira ocupa. Apertar o gap e o
   padding das celulas devolve essa largura sem mexer em fonte nenhuma. */
@media (max-width:1500px){
  [data-testid="stHorizontalBlock"]{gap:0.35rem!important}
}

/* Topbar em tela estreita. O nowrap do proprio header impede a quebra, mas
   nao cria espaco: abaixo de certa largura os pills simplesmente nao cabem
   lado a lado. Entao eles somem por ordem de dispensabilidade — primeiro
   quem esta online (informacao social), depois o "Atualizado" (o carimbo
   tambem aparece no banner de dados velhos). O nome de quem esta logado
   nunca sai: e o unico que responde "estou vendo a carteira de quem?". */
@media (max-width:1100px){
  .topbar-online{display:none!important}
}
/* A regra de gap acima foi escrita pra tabela de 10 colunas da
   Inadimplencia, mas pega TODO stHorizontalBlock do app. Na linha "Visao
   Geral + Analise", que tem so duas colunas largas, o mesmo aperto colava o
   filtro de exclusao no card ao lado. Aqui o gap volta ao normal — so nessa
   linha, pela key do container. */
.st-key-atv_linha_indicadores [data-testid="stHorizontalBlock"]{
  gap:1rem!important;
}
/* Nada de margem extra no multiselect: a altura desse bloco e o que posiciona
   o card da Analise em relacao ao Visao Geral ao lado, e esse alinhamento foi
   calibrado no olho. O grude em tela estreita era o gap das colunas, resolvido
   na regra acima — a margem aqui so desalinhava os dois cards. */
@media (max-width:820px){
  .topbar-upd{display:none!important}
  .topbar{padding:0 14px!important}
}

/* Sidebar em tela estreita: 250px fixos comem ~18% de um notebook de 1366.
   Encolhe pra 200px. O recolher/reabrir ja vale em qualquer largura desde
   que as regras globais passaram a respeitar o aria-expanded — aqui so
   sobra a largura, e o translateX do estado fechado acompanhando ela. */
@media (max-width:1500px){
  section[data-testid="stSidebar"][aria-expanded="true"]{min-width:200px!important;width:200px!important}
  section[data-testid="stSidebar"][aria-expanded="true"] > div:first-child{width:200px!important}
  section[data-testid="stSidebar"][aria-expanded="false"]{transform:translateX(-200px)!important}
}
.stDateInput input{background:var(--surface)!important;color:var(--txt)!important;border:1px solid var(--surface-2)!important;border-radius:8px!important;font-size:15px!important;padding:0.6rem 0.9rem!important}

/* ── Expander ── */
.streamlit-expanderHeader{background:var(--surface)!important;color:var(--txt)!important;border:1px solid var(--surface-2)!important;border-radius:10px!important;font-size:13px!important;font-weight:600!important}
.streamlit-expanderContent{background:var(--surface-3)!important;border:1px solid var(--surface-2)!important;border-top:none!important}
hr{border-color:var(--surface-2)!important;margin:16px 0!important;opacity:1}

/* ── Dialog ── */
/* Streamlit 1.59: stDialogContent/div[role=dialog] nao existem mais no DOM.
   O painel e' <section role="dialog"> dentro de [data-testid="stDialog"]. */
[data-testid="stDialog"] section[role="dialog"]{background:var(--surface)!important;border:1px solid var(--border)!important;border-radius:16px!important;box-shadow:0 16px 48px rgba(0,0,0,.5)!important}
[data-testid="stDialog"] [data-testid="stVerticalBlock"]{gap:0.8rem!important}
.dialog-info{background:var(--surface-3);border:1px solid var(--surface-2);border-radius:10px;padding:14px 16px;margin-bottom:4px}
.dialog-info-label{font-size:13px;text-transform:uppercase;letter-spacing:1.2px;color:var(--txt-2);margin-bottom:6px;font-weight:700}
.dialog-info-value{font-size:14px;color:var(--txt);font-weight:600}
</style>
"""
