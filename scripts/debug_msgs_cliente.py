"""Debug: lista mensagens N8N enviadas pra um cliente nos últimos N dias.

Uso:
    python scripts/debug_msgs_cliente.py 17981512599 17988116513
    python scripts/debug_msgs_cliente.py --dias 7 17981512599

Lê credenciais de .streamlit/secrets.toml (mesma config do app).
"""
import sys
import argparse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import tomllib
except ImportError:
    import tomli as tomllib

import psycopg2


def carregar_secrets():
    root = Path(__file__).resolve().parent.parent
    path = root / ".streamlit" / "secrets.toml"
    if not path.exists():
        raise SystemExit(f"[ERR] Nao achei {path}")
    with open(path, "rb") as f:
        return tomllib.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("telefones", nargs="+", help="Telefones (qualquer formato)")
    ap.add_argument("--dias", type=int, default=7, help="Janela em dias (default 7)")
    args = ap.parse_args()

    secrets = carregar_secrets()
    pg = secrets.get("n8n_postgres", {})

    conn = psycopg2.connect(
        host=pg["host"], port=pg.get("port", 5432),
        dbname=pg.get("database", "postgres"),
        user=pg["user"], password=pg["password"],
        sslmode=pg.get("sslmode", "require"),
    )
    schema = pg.get("schema", "public")
    table  = pg.get("table",  "n8nfinchatbot_historico_atendente")
    tabela_msgs = f'"{schema}"."n8nfinchatbot_historico_msgs"'

    cur = conn.cursor()

    for tel in args.telefones:
        digitos = "".join(c for c in tel if c.isdigit())
        sufixo = digitos[-8:] if len(digitos) >= 8 else digitos
        print("=" * 72)
        print(f"Telefone: {tel}  (busca por sufixo '{sufixo}')")
        print("=" * 72)

        cur.execute(f"""
            SELECT telefone, fromme, created_at, message
            FROM {tabela_msgs}
            WHERE telefone LIKE %s
              AND created_at >= NOW() - INTERVAL '{args.dias} days'
            ORDER BY created_at ASC
        """, (f"%{sufixo}%",))
        rows = cur.fetchall()

        if not rows:
            print("  (nenhuma mensagem na janela)")
            continue

        for telefone, fromme, ts, msg in rows:
            direcao = "-> ENVIADA " if str(fromme).lower() == "true" else "<- RECEBIDA"
            ts_str = ts.strftime("%d/%m %H:%M") if ts else "?"
            msg_str = (msg or "").replace("\n", " | ")
            if len(msg_str) > 200:
                msg_str = msg_str[:200] + "..."
            print(f"  [{ts_str}] {direcao}  {msg_str}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
