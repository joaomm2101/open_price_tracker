import os
from collections.abc import Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

# Trocar para Postgres é só mudar a variável, ex.:
# DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/open_price_tracker
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///open_price_tracker.db")


def make_engine(url: str = DATABASE_URL, **kwargs) -> Engine:
    if url.startswith("sqlite"):
        # As rotas rodam em threads diferentes da que criou a conexão.
        kwargs.setdefault("connect_args", {"check_same_thread": False})
    engine = create_engine(url, **kwargs)

    if engine.dialect.name == "sqlite":
        # O SQLite só respeita foreign keys com este PRAGMA; o Postgres já respeita.
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = make_engine()


def create_db_and_tables() -> None:
    """Cria as tabelas direto no SQLite de desenvolvimento.

    No Postgres o esquema é gerenciado pelo Alembic (`alembic upgrade head`).
    """
    from app import models  # noqa: F401  (registra as tabelas no metadata)

    if engine.dialect.name == "sqlite":
        SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
