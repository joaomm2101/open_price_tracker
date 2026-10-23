# Open Price Tracker

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

## Testes

    uv run pytest                                  # SQLite em memória
    TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/open_price_tracker_test \
      uv run pytest                                # Postgres (o banco de teste é apagado a cada teste)
