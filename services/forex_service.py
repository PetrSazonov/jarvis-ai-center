from datetime import date, timedelta

from services.http_service import ExternalAPIError, request_json

CBR_DAILY_URL = "https://www.cbr-xml-daily.ru/daily_json.js"


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous * 100.0


def _extract_rate(payload: dict, code: str) -> float:
    valute = payload.get("Valute", {})
    currency = valute.get(code)
    if not currency:
        raise ExternalAPIError(service="cbr", kind="parse", message=f"missing {code} block")

    value = currency.get("Value")
    nominal = currency.get("Nominal")
    if value is None or nominal in (None, 0):
        raise ExternalAPIError(service="cbr", kind="parse", message=f"invalid {code} value/nominal")

    return float(value) / float(nominal)


async def _fetch_daily(url: str) -> dict:
    return await request_json(
        service="cbr",
        method="GET",
        url=url,
        timeout=8.0,
        retries=1,
    )


def _archive_url_for_date(day: date) -> str:
    return f"https://www.cbr-xml-daily.ru/archive/{day.year:04d}/{day.month:02d}/{day.day:02d}/daily_json.js"


async def _fetch_archive_nearest_before(base_day: date, max_lookback_days: int = 10) -> dict:
    for offset in range(max_lookback_days + 1):
        target = base_day - timedelta(days=offset)
        url = _archive_url_for_date(target)
        try:
            return await _fetch_daily(url)
        except ExternalAPIError as exc:
            if exc.kind == "http" and exc.status_code in {404, 403}:
                continue
            raise
    raise ExternalAPIError(service="cbr", kind="data_gap", message=f"archive missing near {base_day.isoformat()}")


async def fetch_usd_eur_to_rub() -> dict[str, float]:
    current = await _fetch_daily(CBR_DAILY_URL)

    previous_url = current.get("PreviousURL")
    if not previous_url:
        raise ExternalAPIError(service="cbr", kind="parse", message="missing PreviousURL")

    if previous_url.startswith("//"):
        previous_url = "https:" + previous_url

    previous = await _fetch_daily(previous_url)

    usd_current = _extract_rate(current, "USD")
    eur_current = _extract_rate(current, "EUR")
    usd_prev = _extract_rate(previous, "USD")
    eur_prev = _extract_rate(previous, "EUR")

    return {
        "usd_rub": usd_current,
        "eur_rub": eur_current,
        "usd_rub_24h_change": _pct_change(usd_current, usd_prev),
        "eur_rub_24h_change": _pct_change(eur_current, eur_prev),
    }


async def fetch_usd_eur_to_rub_extended() -> dict[str, float]:
    current = await _fetch_daily(CBR_DAILY_URL)

    previous_url = current.get("PreviousURL")
    if not previous_url:
        raise ExternalAPIError(service="cbr", kind="parse", message="missing PreviousURL")
    if previous_url.startswith("//"):
        previous_url = "https:" + previous_url

    previous = await _fetch_daily(previous_url)
    day7 = await _fetch_archive_nearest_before(date.today() - timedelta(days=7))
    day30 = await _fetch_archive_nearest_before(date.today() - timedelta(days=30))

    usd_current = _extract_rate(current, "USD")
    eur_current = _extract_rate(current, "EUR")

    usd_prev = _extract_rate(previous, "USD")
    eur_prev = _extract_rate(previous, "EUR")
    usd_7 = _extract_rate(day7, "USD")
    eur_7 = _extract_rate(day7, "EUR")
    usd_30 = _extract_rate(day30, "USD")
    eur_30 = _extract_rate(day30, "EUR")

    return {
        "usd_rub": usd_current,
        "eur_rub": eur_current,
        "usd_rub_24h_change": _pct_change(usd_current, usd_prev),
        "eur_rub_24h_change": _pct_change(eur_current, eur_prev),
        "usd_rub_7d_change": _pct_change(usd_current, usd_7),
        "eur_rub_7d_change": _pct_change(eur_current, eur_7),
        "usd_rub_30d_change": _pct_change(usd_current, usd_30),
        "eur_rub_30d_change": _pct_change(eur_current, eur_30),
    }
