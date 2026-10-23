from datetime import date, timedelta

import pytest
from sqlmodel import select

from app.models import Price, Product, Store


def iso(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


class TestHealth:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


class TestProducts:
    def test_list(self, client):
        r = client.get("/products")
        assert r.status_code == 200
        assert [p["id"] for p in r.json()] == [1, 2]

    def test_get(self, client):
        r = client.get("/products/1")
        assert r.status_code == 200
        assert r.json() == {"id": 1, "name": "Rice 5kg", "brand": "Brand A"}

    def test_get_not_found(self, client):
        r = client.get("/products/99")
        assert r.status_code == 404
        assert r.json()["detail"] == "Product not found"

    def test_get_invalid_id(self, client):
        assert client.get("/products/abc").status_code == 422

    def test_create(self, client, session):
        r = client.post("/products", json={"name": "Milk 1L", "brand": "Brand C"})
        assert r.status_code == 201
        assert r.json() == {"name": "Milk 1L", "brand": "Brand C", "id": 3}
        assert session.get(Product, 3).name == "Milk 1L"

    def test_create_duplicate(self, client):
        r = client.post("/products", json={"name": "Rice 5kg", "brand": "Brand A"})
        assert r.status_code == 400
        assert r.json()["detail"] == "Product already exists"

    def test_same_name_other_brand_is_allowed(self, client):
        r = client.post("/products", json={"name": "Rice 5kg", "brand": "Brand Z"})
        assert r.status_code == 201

    def test_create_invalid(self, client):
        assert client.post("/products", json={"name": "Milk"}).status_code == 422

    def test_create_ignores_client_id(self, client):
        r = client.post("/products", json={"id": 50, "name": "Milk", "brand": "B"})
        assert r.json()["id"] == 3


class TestStores:
    def test_list(self, client):
        r = client.get("/stores")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_count(self, client):
        assert client.get("/stores/count").json() == {"count": 2}

    def test_create(self, client, session):
        r = client.post("/stores", json={"name": "Store C", "location": "City C"})
        assert r.status_code == 201
        assert r.json() == {"name": "Store C", "location": "City C", "id": 3}
        assert client.get("/stores/count").json() == {"count": 3}
        assert session.get(Store, 3).location == "City C"

    def test_create_duplicate(self, client):
        r = client.post("/stores", json={"name": "Store A", "location": "City A"})
        assert r.status_code == 400
        assert r.json()["detail"] == "Store already exists"

    def test_create_invalid(self, client):
        assert client.post("/stores", json={"name": "Store C"}).status_code == 422

    def test_store_prices(self, client):
        r = client.get("/stores/1/prices")
        assert r.status_code == 200
        body = r.json()
        assert body["store_id"] == 1
        assert {p["id"] for p in body["prices"]} == {1, 3}

    def test_store_prices_exclude_old(self, client):
        r = client.get("/stores/2/prices")
        assert {p["id"] for p in r.json()["prices"]} == {2}

    def test_store_prices_window_limit(self, client):
        assert client.get("/stores/2/prices?max_age_days=365").status_code == 200
        assert client.get("/stores/2/prices?max_age_days=500").status_code == 422

    def test_store_prices_not_found(self, client):
        assert client.get("/stores/99/prices").status_code == 404


class TestProductPrices:
    def test_recent_only(self, client):
        r = client.get("/products/2/prices")
        assert [p["id"] for p in r.json()["prices"]] == [3]

    def test_prices_are_int_cents_and_dates_are_iso(self, client):
        price = client.get("/products/1/prices").json()["prices"][0]
        assert price["price"] == 2000
        assert isinstance(price["price"], int)
        assert price["date"] == iso(2)

    def test_narrow_window(self, client):
        r = client.get("/products/1/prices?max_age_days=3")
        assert [p["id"] for p in r.json()["prices"]] == [1]

    def test_not_found(self, client):
        assert client.get("/products/99/prices").status_code == 404

    def test_invalid_window(self, client):
        assert client.get("/products/1/prices?max_age_days=0").status_code == 422


class TestAggregates:
    def test_average(self, client):
        r = client.get("/products/1/prices/average")
        assert r.status_code == 200
        assert r.json() == {"product_id": 1, "max_age_days": 30, "average_price": 2100}

    def test_highest(self, client):
        body = client.get("/products/1/prices/highest").json()
        assert body["highest_price"] == 2200
        assert body["store_id"] == 2
        assert body["date"] == iso(5)

    def test_old_price_excluded(self, client):
        # O preço de 400 dias do produto 2 nunca entra, mesmo com a janela máxima.
        r = client.get("/products/2/prices/highest?max_age_days=365")
        assert r.json()["highest_price"] == 1000

    def test_only_latest_price_per_store_counts(self, client):
        client.post("/prices", json={"product_id": 1, "store_id": 1, "price": 3000})
        r = client.get("/products/1/prices/average")
        assert r.json()["average_price"] == 2600  # (3000 + 2200) / 2

    def test_window_without_prices(self, client):
        r = client.get("/products/1/prices/average?max_age_days=1")
        assert r.status_code == 404
        assert "No prices" in r.json()["detail"]

    def test_product_not_found(self, client):
        for kind in ("average", "highest"):
            assert client.get(f"/products/99/prices/{kind}").status_code == 404

    def test_lowest_route_was_removed(self, client):
        assert client.get("/products/1/prices/lowest").status_code == 404


class TestCheapest:
    def test_cheapest(self, client):
        r = client.get("/products/1/cheapest")
        assert r.status_code == 200
        assert r.json() == {
            "product_id": 1,
            "max_age_days": 30,
            "price": 2000,
            "date": iso(2),
            "store": {"id": 1, "name": "Store A", "location": "City A"},
        }

    def test_new_cheaper_price_wins(self, client):
        client.post("/prices", json={"product_id": 1, "store_id": 2, "price": 1500})
        r = client.get("/products/1/cheapest")
        assert r.json()["price"] == 1500
        assert r.json()["store"]["id"] == 2

    def test_new_store_can_be_cheapest(self, client):
        store = client.post("/stores", json={"name": "Store C", "location": "City C"}).json()
        client.post("/prices", json={"product_id": 1, "store_id": store["id"], "price": 500})
        assert client.get("/products/1/cheapest").json()["store"]["name"] == "Store C"

    def test_ignores_stale_cheaper_price(self, client):
        client.post("/prices", json={"product_id": 1, "store_id": 2, "price": 100, "date": iso(100)})
        assert client.get("/products/1/cheapest").json()["price"] == 2000

    def test_wide_window_still_uses_latest_price_per_store(self, client):
        # Loja 2 tem um preço de 5 dias (2200) e um de 100 dias (100): só o mais recente vale.
        client.post("/prices", json={"product_id": 1, "store_id": 2, "price": 100, "date": iso(100)})
        r = client.get("/products/1/cheapest?max_age_days=365")
        assert r.json()["price"] == 2000

    def test_no_recent_prices(self, client):
        assert client.get("/products/1/cheapest?max_age_days=1").status_code == 404

    def test_product_not_found(self, client):
        assert client.get("/products/99/cheapest").status_code == 404


class TestCreatePrice:
    def test_defaults_to_today(self, client, session):
        r = client.post("/prices", json={"product_id": 1, "store_id": 1, "price": 1950})
        assert r.status_code == 201
        assert r.json()["date"] == date.today().isoformat()
        assert r.json()["price"] == 1950
        assert r.json()["id"] == 5
        assert len(session.exec(select(Price)).all()) == 5

    def test_stored_date_is_a_date_object(self, client, session):
        client.post("/prices", json={"product_id": 1, "store_id": 1, "price": 1950, "date": iso(3)})
        stored = session.get(Price, 5).date
        assert type(stored) is date
        assert stored == date.today() - timedelta(days=3)

    def test_float_price_rejected(self, client):
        r = client.post("/prices", json={"product_id": 1, "store_id": 1, "price": 19.5})
        assert r.status_code == 422

    def test_future_date_rejected(self, client):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        r = client.post("/prices", json={"product_id": 1, "store_id": 1, "price": 100, "date": tomorrow})
        assert r.status_code == 400

    def test_unknown_product(self, client):
        r = client.post("/prices", json={"product_id": 99, "store_id": 1, "price": 100})
        assert r.status_code == 404
        assert r.json()["detail"] == "Product not found"

    def test_unknown_store(self, client):
        r = client.post("/prices", json={"product_id": 1, "store_id": 99, "price": 100})
        assert r.status_code == 404
        assert r.json()["detail"] == "Store not found"

    def test_invalid_price(self, client):
        r = client.post("/prices", json={"product_id": 1, "store_id": 1, "price": -5})
        assert r.status_code == 422

    def test_invalid_date_format(self, client):
        r = client.post("/prices", json={"product_id": 1, "store_id": 1, "price": 100, "date": "xx"})
        assert r.status_code == 422


class TestPriceHistory:
    @staticmethod
    def add(client, price, day, store_id=1, product_id=1):
        r = client.post(
            "/prices",
            json={"product_id": product_id, "store_id": store_id, "price": price, "date": day},
        )
        assert r.status_code == 201

    def test_cheapest_in_an_old_year(self, client):
        self.add(client, 1800, "2014-03-10", store_id=1)
        self.add(client, 1500, "2014-08-01", store_id=2)
        self.add(client, 900, "2015-01-02", store_id=1)  # fora de 2014
        r = client.get("/products/1/prices/history?start_date=2014-01-01&end_date=2014-12-31")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2
        assert body["cheapest"] == {
            "price": 1500,
            "date": "2014-08-01",
            "store": {"id": 2, "name": "Store B", "location": "City B"},
        }
        assert body["average_price"] == 1650
        assert body["highest_price"] == 1800
        assert body["start_date"] == "2014-01-01"

    def test_uses_every_record_not_only_latest_per_store(self, client):
        self.add(client, 1000, "2014-01-10", store_id=1)
        self.add(client, 2000, "2014-06-10", store_id=1)
        body = client.get(
            "/products/1/prices/history?start_date=2014-01-01&end_date=2014-12-31"
        ).json()
        assert (body["count"], body["cheapest"]["price"], body["average_price"]) == (2, 1000, 1500)

    def test_boundaries_are_inclusive(self, client):
        self.add(client, 1000, "2014-01-01")
        self.add(client, 1100, "2014-12-31")
        self.add(client, 1200, "2013-12-31")
        self.add(client, 1300, "2015-01-01")
        body = client.get(
            "/products/1/prices/history?start_date=2014-01-01&end_date=2014-12-31"
        ).json()
        assert body["count"] == 2

    def test_single_day(self, client):
        self.add(client, 1000, "2014-05-05")
        body = client.get(
            "/products/1/prices/history?start_date=2014-05-05&end_date=2014-05-05"
        ).json()
        assert (body["count"], body["cheapest"]["price"]) == (1, 1000)

    def test_open_ended_periods(self, client):
        self.add(client, 100, "2014-05-05")
        everything = client.get("/products/1/prices/history").json()
        assert everything["count"] == 3  # 2 do exemplo + 1 antigo
        assert everything["cheapest"]["price"] == 100
        assert everything["start_date"] is None and everything["end_date"] is None
        only_from = client.get("/products/1/prices/history?start_date=2020-01-01").json()
        assert only_from["count"] == 2
        only_until = client.get("/products/1/prices/history?end_date=2014-12-31").json()
        assert only_until["count"] == 1

    def test_tie_prefers_most_recent(self, client):
        self.add(client, 700, "2014-02-01", store_id=1)
        self.add(client, 700, "2014-09-01", store_id=2)
        body = client.get(
            "/products/1/prices/history?start_date=2014-01-01&end_date=2014-12-31"
        ).json()
        assert body["cheapest"]["date"] == "2014-09-01"
        assert body["cheapest"]["store"]["id"] == 2

    def test_other_products_are_not_mixed_in(self, client):
        self.add(client, 50, "2014-05-05", product_id=2)
        body = client.get("/products/1/prices/history?end_date=2014-12-31").status_code
        assert body == 404

    def test_old_prices_still_reachable_while_cheapest_ignores_them(self, client):
        self.add(client, 100, "2014-05-05")
        assert client.get("/products/1/cheapest").json()["price"] == 2000
        assert client.get("/products/1/prices/history").json()["cheapest"]["price"] == 100

    def test_no_prices_in_period(self, client):
        r = client.get("/products/1/prices/history?start_date=1999-01-01&end_date=1999-12-31")
        assert r.status_code == 404
        assert "No prices" in r.json()["detail"]

    def test_future_period_is_just_empty(self, client):
        assert client.get("/products/1/prices/history?start_date=2999-01-01").status_code == 404

    def test_start_after_end(self, client):
        r = client.get("/products/1/prices/history?start_date=2015-01-01&end_date=2014-01-01")
        assert r.status_code == 422

    @pytest.mark.parametrize("value", ["2014", "2014-13-01", "yesterday", "01/02/2014"])
    def test_invalid_dates(self, client, value):
        assert client.get(f"/products/1/prices/history?start_date={value}").status_code == 422

    def test_product_not_found(self, client):
        assert client.get("/products/99/prices/history").status_code == 404
