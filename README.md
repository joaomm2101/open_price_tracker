# Open Price Tracker

[![Tests](https://github.com/joaomm2101/open_price_tracker/actions/workflows/tests.yml/badge.svg)](https://github.com/joaomm2101/open_price_tracker/actions/workflows/tests.yml)

API (FastAPI + SQLModel) para acompanhar preços de produtos em lojas. Os preços são
guardados como **inteiros em centavos** (`2050` = 20,50) e só preços recentes
(`max_age_days`, padrão 30) entram nas consultas.

## Interface web

Com o servidor rodando, abra http://127.0.0.1:8000/ : análise de preços (atuais e de qualquer
período), cadastro de produtos, lojas e preços, e a aba **Import CSV**, onde você escolhe um
arquivo, usa **Check file** para ver o que aconteceria (nada é gravado) e só então **Import**.
Ao cadastrar um produto dá para escolher a loja onde ele foi visto (com preço e data); isso
cria o produto e o primeiro preço juntos (`POST /products` aceita `store_id`, `price` e `date`).
A documentação interativa da API continua em `/docs`.

## Rodar com SQLite (desenvolvimento)

    uv run fastapi dev app/main.py

Cria o arquivo `open_price_tracker.db` automaticamente.

## Rodar com Postgres

    docker compose up -d
    export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/open_price_tracker
    uv run alembic upgrade head
    uv run fastapi dev app/main.py

Depois de mudar `app/models.py`, gere a migração com
`uv run alembic revision --autogenerate -m "descrição"`.

## Consultar preços em qualquer período

    GET /products/{id}/prices/history?start_date=2014-01-01&end_date=2014-12-31

Retorna o menor preço já registrado no período (com loja e data), a média, o maior preço e
a quantidade de registros. `start_date` e `end_date` são opcionais e inclusivos; sem eles o
período fica aberto. Já `/cheapest` e `/prices/average|highest` olham só os preços recentes
(`max_age_days`, padrão 30).

## Importar preços de um CSV

    uv run python -m app.importer precos.csv          # preço em reais, ex.: 19,09 ou 19.09
    uv run python -m app.importer precos.csv --cents  # preço já em centavos, ex.: 1909

Colunas: `product_name, brand, store_name, city, price, date` (também aceita `product`,
`store`, `location` e nomes em português; colunas extras como `unit` são ignoradas).
Datas em `AAAA-MM-DD` ou `DD/MM/AAAA`; separador `,`, `;` ou tab.

- Produtos e lojas são criados se ainda não existirem (maiúsculas/minúsculas são ignoradas).
- Reimportar o mesmo arquivo não duplica: o mesmo produto, loja e data atualiza o preço.
- Também dá para enviar o arquivo pela API: `POST /imports?dry_run=true` (só confere) ou
  `dry_run=false` (importa), com o arquivo no campo `file` (até 20 MB, UTF-8 ou Windows-1252).
- Linhas inválidas não interrompem a importação; são gravadas em `<arquivo>.rejected.csv`
  com o motivo. Usa o banco de `DATABASE_URL` (SQLite por padrão).

## Testes

    uv run pytest                                  # SQLite em memória
    TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/open_price_tracker_test \
      uv run pytest                                # Postgres (o banco de teste é apagado a cada teste)
