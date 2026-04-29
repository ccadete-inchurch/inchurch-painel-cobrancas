import hashlib
import streamlit as st


def _usuarios_do_secrets():
    """Carrega usuários do st.secrets se disponível, senão usa credenciais de dev."""
    try:
        usuarios_secrets = st.secrets.get("usuarios", {})
        if usuarios_secrets:
            usuarios = {}
            for _, u in usuarios_secrets.items():
                uid = hashlib.md5(u["email"].encode()).hexdigest()
                usuarios[uid] = {
                    "nome":       u["nome"],
                    "email":      u["email"],
                    "senha_hash": u.get("senha_hash", ""),
                    "role":       u.get("role", "atendente"),
                }
            return usuarios
    except Exception:
        pass
    # Fallback para desenvolvimento local
    uid = hashlib.md5("teste@inchurch.com.br".encode()).hexdigest()
    return {uid: {
        "nome":       "Administrador",
        "email":      "teste@inchurch.com.br",
        "senha_hash": hashlib.sha256("admin".encode()).hexdigest(),
        "role":       "admin",
    }}


def get_store():
    if "store" not in st.session_state:
        st.session_state["store"] = {
            "usuarios":           _usuarios_do_secrets(),
            "clientes":           [],
            "historico":          {},
            "regularizados":      [],
            "ultima_atualizacao": None,
        }
    return st.session_state["store"]


def hash_senha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def login(email, senha):
    for uid, u in get_store()["usuarios"].items():
        if u["email"].lower() == email.lower() and u["senha_hash"] == hash_senha(senha):
            st.session_state.update({
                "user_uid":  uid,
                "user_nome": u["nome"],
                "user_role": u["role"],
            })
            return True
    return False


def login_google(email: str, nome: str) -> bool:
    """Permite apenas emails cadastrados em [usuarios] no secrets.toml."""
    email_lower = email.lower()
    for uid, u in get_store()["usuarios"].items():
        if u["email"].lower() == email_lower:
            st.session_state.update({
                "user_uid":  uid,
                "user_nome": u["nome"],
                "user_role": u["role"],
            })
            return True
    return False


def is_logged():    return "user_uid" in st.session_state
def current_uid():  return st.session_state.get("user_uid",  "")
def current_nome(): return st.session_state.get("user_nome", "")
def current_role(): return st.session_state.get("user_role", "atendente")
