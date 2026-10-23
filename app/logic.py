from datetime import date, timedelta

DEFAULT_MAX_AGE_DAYS = 30


def filter_recent_prices(
    prices: list[dict],
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    today: date | None = None,
) -> list[dict]:
    """
    Mantém apenas os preços registrados nos últimos `max_age_days` dias.

    Preços mais antigos são descartados porque o produto pode não estar
    mais disponível com aquele valor. Datas futuras também são ignoradas.
    """
    today = today or date.today()
    cutoff = today - timedelta(days=max_age_days)
    return [price for price in prices if cutoff <= price["date"] <= today]


def get_current_prices(
    prices: list[dict],
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    today: date | None = None,
) -> list[dict]:
    """
    Retorna o preço atual de cada loja: o registro mais recente dentro
    da janela de `max_age_days` dias. Assim, uma loja não pesa mais de
    uma vez nas estatísticas.
    """
    latest_by_store: dict[int, dict] = {}
    for price in filter_recent_prices(prices, max_age_days, today):
        current = latest_by_store.get(price["store_id"])
        if current is None or price["date"] > current["date"]:
            latest_by_store[price["store_id"]] = price
    return list(latest_by_store.values())


def calculate_average_price(prices: list[dict]) -> int | None:
    """Preço médio em centavos (arredondado), ou None se não houver preços."""
    if not prices:
        return None
    return round(sum(p["price"] for p in prices) / len(prices))


def get_cheapest_price(prices: list[dict]) -> dict | None:
    """
    Registro de preço mais barato, ou None se não houver preços.

    Em caso de empate, vence o mais recente.
    """
    if not prices:
        return None
    return min(prices, key=lambda p: (p["price"], -p["date"].toordinal()))


def calculate_highest_price(prices: list[dict]) -> int | None:
    """Maior preço em centavos, ou None se não houver preços."""
    if not prices:
        return None
    return max(p["price"] for p in prices)
