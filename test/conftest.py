from datetime import date, timedelta

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.database import get_session, make_engine
from app.main import app
from app.models import Price, Product, Store


def days_ago(n: int) -> date:
    return date.today() - timedelta(days=n)


# Por padrão os testes usam SQLite em memória. Para rodá-los no Postgres:
#   TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/open_price_tracker_test pytest
# (o banco de teste é apagado e recriado a cada teste, nunca aponte para o banco real)
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture
def engine():
    """Banco novo a cada teste, já com os dados de exemplo."""
    if TEST_DATABASE_URL:
        engine = make_engine(TEST_DATABASE_URL)
        SQLModel.metadata.drop_all(engine)
    else:
        engine = make_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Product(name="Rice 5kg", brand="Brand A"),
                Product(name="Black beans 1kg", brand="Brand B"),
                Store(name="Store A", location="City A"),
                Store(name="Store B", location="City B"),
            ]
        )
        session.commit()
        session.add_all(
            [
                Price(product_id=1, store_id=1, price=2000, date=days_ago(2)),
                Price(product_id=1, store_id=2, price=2200, date=days_ago(5)),
                Price(product_id=2, store_id=1, price=1000, date=days_ago(10)),
                Price(product_id=2, store_id=2, price=1200, date=days_ago(400)),
            ]
        )
        session.commit()
    yield engine
    if TEST_DATABASE_URL:
        SQLModel.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(engine):
    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    yield TestClient(app)
    app.dependency_overrides.clear()
