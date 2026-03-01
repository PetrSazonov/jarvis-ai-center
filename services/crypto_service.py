from typing import Any, Iterable

from services.http_service import request_json


COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
CRYPTO_IDS = {"BTC": "bitcoin", "ETH": "ethereum"}


def _normalize_currencies(vs: str | Iterable[str]) -> str:
    if isinstance(vs, str):
        return vs
    cleaned = [item.strip().lower() for item in vs if item and item.strip()]
    return ",".join(cleaned)


async def fetch_prices(vs_currency: str | Iterable[str]) -> dict[str, Any]:
    return await request_json(
        service="coingecko",
        method="GET",
        url=COINGECKO_URL,
        params={
            "ids": ",".join(CRYPTO_IDS.values()),
            "vs_currencies": _normalize_currencies(vs_currency),
            "include_24hr_change": "true",
        },
        timeout=8.0,
        retries=1,
    )


async def fetch_market_changes(vs_currency: str) -> dict[str, dict[str, float | None]]:
    rows = await request_json(
        service="coingecko",
        method="GET",
        url=COINGECKO_MARKETS_URL,
        params={
            "vs_currency": (vs_currency or "usd").lower(),
            "ids": ",".join(CRYPTO_IDS.values()),
            "price_change_percentage": "24h,7d,30d",
        },
        timeout=8.0,
        retries=1,
    )

    out: dict[str, dict[str, float | None]] = {}
    if not isinstance(rows, list):
        return out

    for row in rows:
        coin_id = str(row.get("id") or "")
        if not coin_id:
            continue
        out[coin_id] = {
            "price": float(row["current_price"]) if row.get("current_price") is not None else None,
            "change_24h_pct": float(row["price_change_percentage_24h_in_currency"])
            if row.get("price_change_percentage_24h_in_currency") is not None
            else None,
            "change_7d_pct": float(row["price_change_percentage_7d_in_currency"])
            if row.get("price_change_percentage_7d_in_currency") is not None
            else None,
            "change_30d_pct": float(row["price_change_percentage_30d_in_currency"])
            if row.get("price_change_percentage_30d_in_currency") is not None
            else None,
        }
    return out
