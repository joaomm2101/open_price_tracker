from datetime import date, timedelta

import pytest

from app.logic import (
    calculate_average_price,
    calculate_highest_price,
    filter_recent_prices,
    get_cheapest_price,
    get_current_prices,
)

TODAY = date(2026, 10, 23)


def make(id, product_id=1, store_id=1, price=1000, days_ago=0):
    return {
        "id": id,
        "product_id": product_id,
        "store_id": store_id,
        "price": price,
        "date": TODAY - timedelta(days=days_ago),
    }


class TestFilterRecentPrices:
    def test_keeps_recent_and_drops_old(self):
        prices = [make(1, days_ago=1), make(2, days_ago=40)]
        result = filter_recent_prices(prices, 30, today=TODAY)
        assert [p["id"] for p in result] == [1]

    def test_cutoff_day_is_inclusive(self):
        prices = [make(1, days_ago=30), make(2, days_ago=31)]
        result = filter_recent_prices(prices, 30, today=TODAY)
        assert [p["id"] for p in result] == [1]

    def test_today_is_included(self):
        assert len(filter_recent_prices([make(1, days_ago=0)], 30, today=TODAY)) == 1

    def test_future_dates_are_ignored(self):
        assert filter_recent_prices([make(1, days_ago=-1)], 30, today=TODAY) == []

    def test_empty(self):
        assert filter_recent_prices([], 30, today=TODAY) == []

    def test_defaults_to_real_today(self):
        fresh = {**make(1), "date": date.today()}
        assert filter_recent_prices([fresh]) == [fresh]


class TestGetCurrentPrices:
    def test_latest_per_store(self):
        prices = [
            make(1, store_id=1, price=2000, days_ago=10),
            make(2, store_id=1, price=1800, days_ago=2),
            make(3, store_id=2, price=2500, days_ago=5),
        ]
        result = get_current_prices(prices, 30, today=TODAY)
        assert sorted(p["id"] for p in result) == [2, 3]

    def test_latest_wins_regardless_of_order(self):
        prices = [make(1, days_ago=1), make(2, days_ago=9)]
        assert [p["id"] for p in get_current_prices(prices, 30, today=TODAY)] == [1]

    def test_old_prices_do_not_count(self):
        prices = [make(1, store_id=1, days_ago=2), make(2, store_id=2, days_ago=90)]
        assert [p["id"] for p in get_current_prices(prices, 30, today=TODAY)] == [1]

    def test_empty(self):
        assert get_current_prices([], 30, today=TODAY) == []


class TestStats:
    prices = [make(1, price=1000), make(2, price=2000), make(3, price=1500)]

    def test_average(self):
        assert calculate_average_price(self.prices) == 1500

    def test_average_is_an_int_in_cents(self):
        prices = [make(1, price=1000), make(2, price=1000), make(3, price=1001)]
        result = calculate_average_price(prices)
        assert result == 1000
        assert isinstance(result, int)

    def test_highest(self):
        assert calculate_highest_price(self.prices) == 2000

    @pytest.mark.parametrize("func", [calculate_average_price, calculate_highest_price])
    def test_empty_returns_none(self, func):
        assert func([]) is None


class TestGetCheapestPrice:
    def test_returns_whole_record(self):
        prices = [make(1, price=1000), make(2, price=800), make(3, price=1500)]
        assert get_cheapest_price(prices)["id"] == 2

    def test_tie_prefers_most_recent(self):
        prices = [make(1, price=800, days_ago=5), make(2, price=800, days_ago=1)]
        assert get_cheapest_price(prices)["id"] == 2

    def test_empty_returns_none(self):
        assert get_cheapest_price([]) is None
