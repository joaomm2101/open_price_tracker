from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas import PriceCreate, ProductCreate, StoreCreate


class TestProduct:
    def test_create_does_not_need_id(self):
        assert ProductCreate(name="Milk", brand="B").name == "Milk"

    @pytest.mark.parametrize("data", [{"name": "", "brand": "B"}, {"name": "M", "brand": ""}, {"name": "M"}])
    def test_invalid(self, data):
        with pytest.raises(ValidationError):
            ProductCreate(**data)


class TestStore:
    def test_create(self):
        assert StoreCreate(name="S", location="L").location == "L"

    @pytest.mark.parametrize("data", [{"name": "", "location": "L"}, {"name": "S", "location": ""}])
    def test_invalid(self, data):
        with pytest.raises(ValidationError):
            StoreCreate(**data)


class TestPrice:
    def test_date_is_parsed_to_date_object(self):
        price = PriceCreate(product_id=1, store_id=1, price=950, date="2026-10-20")
        assert price.date == date(2026, 10, 20)
        assert type(price.date) is date

    def test_date_defaults_to_today(self):
        assert PriceCreate(product_id=1, store_id=1, price=1).date == date.today()

    def test_price_is_integer_cents(self):
        price = PriceCreate(product_id=1, store_id=1, price=2050).price
        assert price == 2050
        assert isinstance(price, int)

    def test_price_rejects_fractional_cents(self):
        with pytest.raises(ValidationError):
            PriceCreate(product_id=1, store_id=1, price=20.5)

    @pytest.mark.parametrize("value", [0, -1])
    def test_price_must_be_positive(self, value):
        with pytest.raises(ValidationError):
            PriceCreate(product_id=1, store_id=1, price=value)

    def test_invalid_date(self):
        with pytest.raises(ValidationError):
            PriceCreate(product_id=1, store_id=1, price=1, date="not-a-date")


class TestProductWithStore:
    def test_store_and_price_together_are_valid(self):
        p = ProductCreate(name="M", brand="B", store_id=1, price=549)
        assert (p.store_id, p.price) == (1, 549)
        assert p.date == date.today()

    def test_neither_is_valid(self):
        p = ProductCreate(name="M", brand="B")
        assert (p.store_id, p.price) == (None, None)

    @pytest.mark.parametrize("extra", [{"store_id": 1}, {"price": 549}])
    def test_one_without_the_other_is_invalid(self, extra):
        with pytest.raises(ValidationError, match="together"):
            ProductCreate(name="M", brand="B", **extra)
