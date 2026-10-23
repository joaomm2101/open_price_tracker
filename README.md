# Open Price Tracker

[![Tests](https://github.com/joaomm2101/open_price_tracker/actions/workflows/tests.yml/badge.svg)](https://github.com/joaomm2101/open_price_tracker/actions/workflows/tests.yml)

API (FastAPI + SQLModel) para acompanhar preços de produtos em lojas. Os preços são
guardados como **inteiros em centavos** (`2050` = 20,50) e só preços recentes
(`max_age_days`, padrão 30) entram nas consultas.

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

## Importar preços de um CSV

    uv run python -m app.importer precos.csv          # preço em reais, ex.: 19,09 ou 19.09
    uv run python -m app.importer precos.csv --cents  # preço já em centavos, ex.: 1909

Colunas: `product_name, brand, store_name, city, price, date` (também aceita `product`,
`store`, `location` e nomes em português; colunas extras como `unit` são ignoradas).
Datas em `AAAA-MM-DD` ou `DD/MM/AAAA`; separador `,`, `;` ou tab.

- Produtos e lojas são criados se ainda não existirem (maiúsculas/minúsculas são ignoradas).
- Reimportar o mesmo arquivo não duplica: o mesmo produto, loja e data atualiza o preço.
- Linhas inválidas não interrompem a importação; são gravadas em `<arquivo>.rejected.csv`
  com o motivo. Usa o banco de `DATABASE_URL` (SQLite por padrão).

## Testes

    uv run pytest                                  # SQLite em memória
    TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/open_price_tracker_test \
      uv run pytest                                # Postgres (o banco de teste é apagado a cada teste)
