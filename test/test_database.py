from datetime import date

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.database import create_db_and_tables, get_session, make_engine
from app.models import Price, Product, Store


class TestSchema:
    def test_has_the_three_tables(self, engine):
        assert set(inspect(engine).get_table_names()) == {"product", "store", "price"}

    def test_price_foreign_keys(self, engine):
        fks = {
            fk["constrained_columns"][0]: fk["referred_table"]
            for fk in inspect(engine).get_foreign_keys("price")
        }
        assert fks == {"product_id": "product", "store_id": "store"}

    def test_product_and_store_have_no_foreign_keys(self, engine):
        insp = inspect(engine)
        assert insp.get_foreign_keys("product") == []
        assert insp.get_foreign_keys("store") == []

    def test_primary_keys(self, engine):
        insp = inspect(engine)
        for table in ("product", "store", "price"):
            assert insp.get_pk_constraint(table)["constrained_columns"] == ["id"]

    def test_price_column_is_integer(self, engine):
        columns = {c["name"]: c for c in inspect(engine).get_columns("price")}
        assert str(columns["price"]["type"]) == "INTEGER"
        assert str(columns["date"]["type"]) == "DATE"


class TestConstraints:
    def test_price_with_unknown_product_is_rejected(self, session):
        session.add(Price(product_id=99, store_id=1, price=100, date=date.today()))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_price_with_unknown_store_is_rejected(self, session):
        session.add(Price(product_id=1, store_id=99, price=100, date=date.today()))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_product_with_prices_cannot_be_deleted(self, session):
        session.delete(session.get(Product, 1))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_duplicate_product_is_rejected(self, session):
        session.add(Product(name="Rice 5kg", brand="Brand A"))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_duplicate_store_is_rejected(self, session):
        session.add(Store(name="Store A", location="City A"))
        with pytest.raises(IntegrityError):
            session.commit()


class TestRoundTrip:
    def test_date_comes_back_as_date(self, session):
        price = session.get(Price, 1)
        assert type(price.date) is date

    def test_price_comes_back_as_int(self, session):
        assert session.get(Price, 1).price == 2000

    def test_ids_are_generated(self, session):
        product = Product(name="Milk", brand="B")
        session.add(product)
        session.commit()
        assert product.id == 3

    def test_filter_prices_by_product(self, session):
        rows = session.exec(select(Price).where(Price.product_id == 1)).all()
        assert {r.id for r in rows} == {1, 2}


class TestEngineHelpers:
    def test_sqlite_engine_enforces_foreign_keys(self):
        engine = make_engine("sqlite://")
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1

    def test_create_db_and_tables(self, tmp_path, monkeypatch):
        from app import database

        engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
        monkeypatch.setattr(database, "engine", engine)
        create_db_and_tables()
        assert set(inspect(engine).get_table_names()) == {"product", "store", "price"}

    def test_get_session_yields_a_session(self):
        session = next(get_session())
        assert isinstance(session, Session)
        session.close()
