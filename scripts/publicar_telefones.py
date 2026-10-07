# -*- coding: utf-8 -*-
"""Publica os telefones de TODOS os clientes, ja prontos pra disparo.

Por que existe: a leitura do telefone no Superlogica nao cabe numa consulta
SQL. Nao e formatar um numero — e juntar os 4 campos do cadastro, descobrir
que 35191317897 e 351913178975 sao o mesmo telefone cortado pela mascara do
campo de celular, ficar com o inteiro, aplicar o st_ddd_sac em quem precisa
e descartar numero de enchimento. Sao ~200 linhas de Python com tres travas
automatizadas em cima (tests/).

Reescrever isso em SQL, ou num workflow do n8n, cria outra copia da regra —
e as copias divergem. O documento que descrevia o telefone_wa_link pro
disparo ficou sem 10 paises, tres deles ja existentes quando foi escrito, e
por isso o cliente 1623 (Eglise Du Centre) recebia WhatsApp brasileiro num
numero suico.

Entao a ordem se inverte: o painel grava JA FORMATADO, e quem dispara so
consulta:

    SELECT numero_wa
    FROM `business-intelligence-467516.N8N.telefones_para_disparo`
    WHERE id_sacado_sac = '4151'
      AND problema IS NULL AND tipo_numero != 'fixo'
    ORDER BY ordem

A tabela cobre o cadastro inteiro — 5.596 clientes, nao so os inadimplentes.

    .venv/Scripts/python.exe scripts/publicar_telefones.py          # grava
    .venv/Scripts/python.exe scripts/publicar_telefones.py --dry    # so mostra
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from google.cloud import bigquery

from helpers import telefones_cliente, telefone_wa_link, tipo_numero

TABELA = "business-intelligence-467516.N8N.telefones_para_disparo"

# Peso da ordem. 'desconhecido' e DDD inexistente: nao da pra afirmar que e
# fixo, mas tambem nao da pra confiar — vai depois do fixo.
PESO = {"celular": 0, "celular_antigo": 1, "fixo": 2, "desconhecido": 3}

ORIGEM = """
SELECT CAST(id_sacado_sac AS STRING) AS id_sacado_sac,
       MAX(st_nome_sac)      AS nome,
       MAX(st_celular_sac)   AS cel,
       MAX(st_fax_sac)       AS fax,
       MAX(st_telefone_sac)  AS tel,
       MAX(st_ddd_sac)       AS ddd,
       MAX(CASE WHEN dt_desativacao_sac IS NOT NULL THEN TRUE ELSE FALSE END) AS inativo
FROM `business-intelligence-467516.Splgc.splgc-clientes-inchurch`
GROUP BY 1
"""

ESQUEMA = [
    bigquery.SchemaField("id_sacado_sac", "STRING", mode="REQUIRED",
                         description="id do cliente no Superlogica"),
    bigquery.SchemaField("nome", "STRING"),
    bigquery.SchemaField("ordem", "INTEGER", mode="REQUIRED",
                         description="1 = melhor numero. Percorrer nesta ordem "
                                     "quando o envio anterior falhar"),
    bigquery.SchemaField("numero_wa", "STRING", mode="REQUIRED",
                         description="so digitos, com DDI — pronto pro wa.me"),
    bigquery.SchemaField("formatado", "STRING",
                         description="o mesmo numero legivel, pra log e tela"),
    bigquery.SchemaField("problema", "STRING",
                         description="NULL = pode disparar. Preenchido = o numero "
                                     "existe no cadastro mas nao leva a lugar "
                                     "nenhum; nao gastar envio"),
    bigquery.SchemaField("tipo_numero", "STRING", mode="REQUIRED",
                         description="celular | celular_antigo | fixo | desconhecido. O antigo "
                                     "e de 8 digitos, de antes do nono: o wa.me "
                                     "acha essas contas, entao vale tentar. "
                                     "Fixo o WhatsApp nao alcanca"),
    bigquery.SchemaField("cliente_inativo", "BOOLEAN"),
    bigquery.SchemaField("atualizado_em", "TIMESTAMP", mode="REQUIRED"),
]


def cliente_bq():
    """Cliente BigQuery, com ou sem painel em volta.

    Antes isso era `data.get_bq_client()`. Importar o data.py arrastava o
    Streamlit inteiro, que le st.secrets no import — e no GitHub Actions nao
    existe .streamlit/secrets.toml. Isso custou uma tentativa de extrair um
    shim de 119 linhas do gerar_lote_cron.py, mexendo em producao, quando o
    acoplamento inteiro vinha desta UNICA chamada.

    Na Action a credencial vem da env var; local, do secrets.toml como sempre.
    """
    sa = os.environ.get("GCP_SA_JSON")
    if not sa:
        import data
        return data.get_bq_client()

    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa), scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return bigquery.Client(credentials=creds, project=creds.project_id)


def montar_campo(r):
    """A mesma string que o data.py entrega pro painel."""
    partes = [str(v).strip() for v in (r.cel, r.fax, r.tel) if str(v or "").strip()]
    if str(r.ddd or "").strip():
        partes.append("ddd=" + str(r.ddd).strip())
    return ";".join(partes)


def main():
    dry = "--dry" in sys.argv
    client = cliente_bq()
    if client is None:
        print("sem cliente BigQuery — checar credenciais")
        return 1

    cad = client.query(ORIGEM).to_dataframe()
    agora = datetime.now(timezone(timedelta(hours=-3)))

    linhas = []
    sem_numero = 0
    for _, r in cad.iterrows():
        itens = telefones_cliente(montar_campo(r))
        if not itens:
            sem_numero += 1
            continue
        # A ordem NAO prevê qual numero entrega — isso so se descobre
        # tentando. Ela garante duas coisas: numero quebrado por ultimo, e
        # celular de 9 digitos antes do antigo de 8, que e de antes de 2016
        # e tem mais chance de estar inativo. Sem a segunda regra, 55
        # clientes tinham o antigo em 1o lugar com um atual logo abaixo.
        ordenados = sorted(
            itens,
            key=lambda t: (bool(t[2]), PESO.get(tipo_numero(t[0]), 3)))
        # Descarta ANTES de numerar. Enumerar primeiro e pular depois abriria
        # buraco na ordem (1, 3, 4) e quem consome por 'ORDER BY ordem' com
        # LIMIT 1 no retry pararia num numero que nao existe. Hoje nenhum
        # cliente cai nisso — telefones_cliente nao devolve nada que o
        # wa_link recuse — mas a ordem contigua passa a ser garantida pelo
        # codigo, nao por coincidencia.
        com_link = [(b, f, p, telefone_wa_link(b)) for b, f, p in ordenados]
        com_link = [x for x in com_link if x[3]]
        for i, (bruto, fmt, prob, wa) in enumerate(com_link, start=1):
            linhas.append({
                "id_sacado_sac":   r.id_sacado_sac,
                "nome":            str(r.nome or ""),
                "ordem":           i,
                "numero_wa":       wa,
                "formatado":       fmt,
                "problema":        prob or None,
                "tipo_numero":     tipo_numero(bruto),
                "cliente_inativo": bool(r.inativo),
                "atualizado_em":   agora,
            })

    df = pd.DataFrame(linhas)
    print(f"clientes no cadastro            : {len(cad)}")
    print(f"clientes sem numero exibivel    : {sem_numero}")
    print(f"clientes na tabela              : {df.id_sacado_sac.nunique()}")
    print(f"linhas (um numero por linha)    : {len(df)}")
    print(f"  disparaveis (problema NULL)   : {df.problema.isna().sum()}")
    print(f"  marcados com problema         : {df.problema.notna().sum()}")
    for t, n in df[df.problema.isna()].tipo_numero.value_counts().items():
        print(f"  {t:30s}: {n}")
    print()
    print("amostra:")
    print(df[df.id_sacado_sac.isin(["4151", "1743", "72", "6613"])]
          [["id_sacado_sac", "ordem", "numero_wa", "formatado", "problema"]]
          .to_string(index=False))

    if dry:
        print("\n--dry: nada foi gravado")
        return 0

    job = client.load_table_from_dataframe(
        df, TABELA,
        job_config=bigquery.LoadJobConfig(
            schema=ESQUEMA,
            write_disposition="WRITE_TRUNCATE",  # idempotente: pode rodar de novo
        ),
    )
    job.result()
    print(f"\ngravado em {TABELA}: {job.output_rows} linhas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
