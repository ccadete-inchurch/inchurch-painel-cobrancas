import hashlib
import streamlit as st


def _usuarios_do_secrets():
    """Carrega usuários autorizados de [usuarios] do secrets.toml."""
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


def _lookup_usuario_por_email(email: str):
    """Retorna (uid, dict_usuario) se o email estiver em [usuarios] do secrets,
    ou (None, None) caso contrario. Case-insensitive."""
    email_lower = (email or "").lower()
    for uid, u in get_store()["usuarios"].items():
        if u["email"].lower() == email_lower:
            return uid, u
    return None, None


def is_logged() -> bool:
    """Autenticado pelo Google (via st.login) E autorizado no secrets.toml."""
    try:
        if not st.user.is_logged_in:
            return False
    except Exception:
        return False
    email = getattr(st.user, "email", "") or ""
    uid, _ = _lookup_usuario_por_email(email)
    return uid is not None


def current_email() -> str:
    try:
        return (getattr(st.user, "email", "") or "").lower()
    except Exception:
        return ""


def current_uid() -> str:
    email = current_email()
    uid, _ = _lookup_usuario_por_email(email)
    return uid or ""


def current_nome() -> str:
    """Nome preferencial do secrets (que a atendente escolheu como rotulo);
    fallback pro nome que o Google retornou; ultimo fallback pro email."""
    email = current_email()
    _, u = _lookup_usuario_por_email(email)
    if u:
        return u["nome"]
    try:
        return getattr(st.user, "name", "") or email
    except Exception:
        return email


def current_role() -> str:
    """Role vem do secrets.toml [usuarios] — admin ou atendente."""
    email = current_email()
    _, u = _lookup_usuario_por_email(email)
    return (u["role"] if u else "atendente")
