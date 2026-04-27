import base64
from pathlib import Path

# ── Paginação e regras ────────────────────────────────────────────────────────
PAGE_SIZE        = 50
DIAS_SEM_CONTATO = 5

# ── Mapeamento de colunas (importação via planilha) ───────────────────────────
MAP_COB  = {
    "codigo":    "código",
    "vencimento":"dt_vencimento_recb",
    "cnpj":      "st_cgc_sac",
    "telefone":  "st_telefone_sac",
}
MAP_INAD = {
    "codigo":   "código",
    "nome":     "st_nome_sac",
    "cnpj":     "st_cgc_sac",
    "telefone1":"st_fax_sac",
    "telefone2":"st_telefone_sac",
    "valor":    "soma_cobrancas",
    "parcelas": "quantidade_cobrancas",
}

# ── Ordenação da tabela ───────────────────────────────────────────────────────
SORT_MAP = {
    "Maior atraso": ("dias_atraso", False),
    "Menor atraso": ("dias_atraso", True),
    "Maior saldo":  ("valor",       False),
    "Menor saldo":  ("valor",       True),
    "Nome A→Z":     ("nome",        True),
    "Nome Z→A":     ("nome",        False),
}

# ── Status ────────────────────────────────────────────────────────────────────
STATUS_LABELS = {
    "pending":     "Sem contato",
    "contacted":   "Contactado",
    "promise":     "Prometeu pagar",
    "negotiating": "Negociando",
    "paid":        "Regularizado",
}
STATUS_COLORS = {
    "pending":     "#ef4444",
    "contacted":   "#f59e0b",
    "promise":     "#f97316",
    "negotiating": "#5fa3ff",
    "paid":        "#22c55e",
}
# Chave de exibição (com emoji) → chave interna  (usado no dialog de edição)
STATUS_OPTS = {
    "🔴 Sem contato":    "pending",
    "🟡 Contactado":     "contacted",
    "🟠 Prometeu pagar": "promise",
    "🔵 Negociando":     "negotiating",
}
# Rótulo da pill → chave interna  (usado no filtro do dashboard)
STATUS_FILTER_MAP = {
    "Sem contato":    "pending",
    "Contactado":     "contacted",
    "Prometeu pagar": "promise",
    "Negociando":     "negotiating",
}

# ── Logo ──────────────────────────────────────────────────────────────────────
_logo_path = Path(__file__).parent / "inchurch_logo.png"
if _logo_path.exists():
    with open(_logo_path, "rb") as _f:
        LOGO_B64 = base64.b64encode(_f.read()).decode()
    LOGO_SRC = f"data:image/png;base64,{LOGO_B64}"
else:
    LOGO_SRC = ""

# ── CSS global ────────────────────────────────────────────────────────────────
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@300;400;500&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif!important;background:#0f1117!important;color:#e8eaf0!important;font-size:15px!important}
#MainMenu,footer,header{visibility:hidden}
.block-container{padding-top:0!important;padding-bottom:1.5rem!important;max-width:100%!important;padding-left:2rem!important;padding-right:2rem!important}

/* ── Sidebar ── */
section[data-testid="stSidebar"]{background:#13161f!important;border-right:1px solid #1e2333!important;min-width:220px!important;width:220px!important;transform:translateX(0)!important;display:block!important;visibility:visible!important;opacity:1!important;position:relative!important;z-index:100!important}
section[data-testid="stSidebar"] > div:first-child{width:220px!important;padding:0!important;display:block!important}
[data-testid="collapsedControl"]{display:none!important;visibility:hidden!important}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"]{display:none!important}
section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"]{display:none!important}
.main .block-container{margin-left:0!important}

/* Botões da sidebar */
section[data-testid="stSidebar"] .stButton>button{
  background:transparent!important;color:#8b94a5!important;border:none!important;
  border-radius:8px!important;font-size:13px!important;font-weight:500!important;
  padding:10px 16px!important;text-align:left!important;justify-content:flex-start!important;
  width:100%!important;transition:all 0.18s!important;box-shadow:none!important;
  letter-spacing:0.2px!important
}
section[data-testid="stSidebar"] .stButton>button:hover{
  background:rgba(124,194,67,.1)!important;color:#7cc243!important;transform:none!important
}

/* ── Cards de métrica ── */
.metric-card{background:#181c26;border:1px solid #1e2333;border-radius:14px;padding:20px 22px;box-shadow:0 1px 6px rgba(0,0,0,.15);transition:box-shadow .2s}
.metric-card:hover{box-shadow:0 4px 16px rgba(0,0,0,.25)}
.metric-label{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:#8b94a5;margin-bottom:10px;font-weight:600}
.metric-value{font-family:'DM Sans',sans-serif;font-size:28px;font-weight:700;line-height:1;letter-spacing:0;font-variant-numeric:tabular-nums}
.metric-sub{font-size:11px;color:#6b7280;margin-top:8px;letter-spacing:0.2px}

/* ── Badges ── */
.badge{display:inline-block;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:600}
.badge-pending{background:rgba(239,68,68,.12);color:#ff5555}
.badge-contacted{background:rgba(245,158,11,.12);color:#ffb84d}
.badge-promise{background:rgba(249,115,22,.12);color:#ff9800}
.badge-negotiating{background:rgba(79,124,255,.12);color:#5fa3ff}
.badge-paid{background:rgba(34,197,94,.12);color:#2dd36f}
.tag-novo{background:rgba(34,197,94,.15);color:#2dd36f;font-size:10px;padding:2px 6px;border-radius:5px;font-weight:700;margin-right:3px}
.tag-upd{background:rgba(245,158,11,.15);color:#ffb84d;font-size:10px;padding:2px 6px;border-radius:5px;font-weight:700;margin-right:3px}
.top-badge{background:rgba(239,68,68,.18);color:#ff6b6b;font-size:10px;padding:2px 6px;border-radius:5px;font-weight:700;margin-right:3px}
.tag-nova-cob{background:rgba(79,124,255,.18);color:#5fa3ff;font-size:10px;padding:2px 7px;border-radius:5px;font-weight:700;margin-right:3px}

/* ── Atraso chips ── */
.da{padding:3px 9px;border-radius:6px;font-size:12px;font-weight:700;display:inline-block}
.da-ok{background:rgba(45,211,111,.12);color:#2dd36f}
.da-30{background:rgba(255,184,77,.12);color:#ffb84d}
.da-60{background:rgba(255,152,0,.12);color:#ff9800}
.da-90{background:rgba(255,85,85,.12);color:#ff5555}
.da-max{background:rgba(200,0,0,.18);color:#ff4444}

/* ── Pendência card ── */
.pend-card{background:#181c26;border:1px solid #1e2333;border-radius:10px;padding:14px 16px;margin-bottom:8px}

/* ── Botões globais ── */
.stButton>button{background:#1e2333!important;color:#e8eaf0!important;font-weight:600!important;border:1px solid #2a2f42!important;border-radius:8px!important;font-size:13px!important;padding:0.4rem 1rem!important;transition:all 0.18s!important;box-shadow:none!important}
.stButton>button:hover{background:#2a2f42!important;border-color:#3d4460!important;transform:none!important;box-shadow:none!important}
button[kind="primary"]{background:#7cc243!important;color:#0f1117!important;border:none!important;font-weight:700!important}
button[kind="primary"]:hover{background:#8fd44e!important}

/* ── Inputs ── */
.stTextInput input,.stTextArea textarea{background:#181c26!important;color:#e8eaf0!important;border:1px solid #1e2333!important;border-radius:8px!important;font-size:13px!important;padding:0.55rem 0.8rem!important}
.stTextInput input:focus,.stTextArea textarea:focus{border-color:#7cc243!important;box-shadow:0 0 0 2px rgba(124,194,67,.15)!important}
.stTextInput label,.stTextArea label,.stSelectbox label,.stDateInput label{color:#6b7280!important;font-size:11px!important;text-transform:uppercase!important;letter-spacing:0.8px!important;font-weight:600!important}
div[data-baseweb="select"]>div{background:#181c26!important;border-color:#1e2333!important;border-radius:8px!important}
div[data-baseweb="select"] span{color:#e8eaf0!important;font-size:13px!important}
div[data-baseweb="popover"],div[data-baseweb="menu"]{background:#181c26!important;border:1px solid #2a2f42!important;border-radius:10px!important}
div[data-baseweb="menu"] li{color:#e8eaf0!important;font-size:13px!important}
div[data-baseweb="menu"] li:hover{background:#1e2333!important}
.stDateInput input{background:#181c26!important;color:#e8eaf0!important;border:1px solid #1e2333!important;border-radius:8px!important;font-size:13px!important;padding:0.55rem 0.8rem!important}

/* ── Expander ── */
.streamlit-expanderHeader{background:#181c26!important;color:#e8eaf0!important;border:1px solid #1e2333!important;border-radius:10px!important;font-size:13px!important;font-weight:600!important}
.streamlit-expanderContent{background:#13161f!important;border:1px solid #1e2333!important;border-top:none!important}
hr{border-color:#1e2333!important;margin:16px 0!important;opacity:1}

/* ── Dialog ── */
[data-testid="stDialogContent"]{background:#181c26!important;border:1px solid #2a2f42!important;border-radius:16px!important;box-shadow:0 16px 48px rgba(0,0,0,.5)!important}
div[role="dialog"] [data-testid="stVerticalBlock"]{gap:0.8rem!important}
.dialog-info{background:#13161f;border:1px solid #1e2333;border-radius:10px;padding:14px 16px;margin-bottom:4px}
.dialog-info-label{font-size:10px;text-transform:uppercase;letter-spacing:1.2px;color:#6b7280;margin-bottom:4px;font-weight:700}
.dialog-info-value{font-size:14px;color:#e8eaf0;font-weight:600}
</style>
"""
