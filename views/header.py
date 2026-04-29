import streamlit as st

from config import LOGO_SRC, SVG_LOGO_SRC
from auth import current_nome, current_role
from data import get_store


def render_header():
    store    = get_store()
    upd      = store.get("ultima_atualizacao") or "—"
    role_tag  = '<span style="background:rgba(124,194,67,.2);color:#7cc243;font-size:11px;padding:3px 10px;border-radius:12px;font-weight:700;margin-left:8px">ADMIN</span>' if current_role() == "admin" else ""
    _src = SVG_LOGO_SRC or LOGO_SRC
    logo_html = f'<img src="{_src}" style="height:30px;object-fit:contain;filter:brightness(0) invert(1);opacity:0.7">' if _src else ""
    st.markdown(f"""
    <div style="background:#181c26;border-bottom:1px solid #2a2f42;padding:0 24px;height:60px;display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,.15)">
      <div style="display:flex;align-items:center;gap:10px">{logo_html}<span style="color:#4b5563;font-size:13px;font-weight:500">Cobranças</span></div>
      <div style="display:flex;align-items:center;gap:12px">
        <span style="font-size:13px;color:#8b94a5;background:#1e2333;padding:6px 14px;border-radius:20px;border:1px solid #2a2f42">Atualizado: {upd}</span>
        <span style="font-size:13px;background:#1e2333;border:1px solid #2a2f42;border-radius:20px;padding:6px 14px;display:inline-flex;align-items:center;gap:8px;font-weight:500">
          <span style="width:8px;height:8px;background:#7cc243;border-radius:50%;display:inline-block"></span>{current_nome()}{role_tag}
        </span>
      </div>
    </div>""", unsafe_allow_html=True)
