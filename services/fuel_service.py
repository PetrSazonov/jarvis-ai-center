import re
from datetime import datetime, timedelta

from core.settings import Settings
from db import add_fuel95_history, get_cache_value, get_fuel95_latest_before, get_latest_fuel95_in_range, set_cache_value
from services.http_service import ExternalAPIError, request_text


# Single-source mode: use only configured source URL (default is PetrolPlus).
FALLBACK_FUEL95_URLS: list[str] = []


CACHE_KEY_FUEL95_MOSCOW = "fuel95_moscow_rub"
CACHE_KEY_FUEL95_MOSCOW_CHANGE = "fuel95_moscow_24h_change_pct"
CACHE_KEY_FUEL95_MOSCOW_7D_CHANGE = "fuel95_moscow_7d_change_pct"
CACHE_KEY_FUEL95_MOSCOW_30D_CHANGE = "fuel95_moscow_30d_change_pct"
MAX_REASONABLE_JUMP_PCT = 15.0
MIN_REASONABLE_MOSCOW_PRICE = 55.0
MAX_24H_CHANGE_PCT = 5.0
MAX_7D_CHANGE_PCT = 15.0
MAX_30D_CHANGE_PCT = 40.0


def _to_float(value: str) -> float:
    return float(value.replace(",", "."))


def _in_plausible_range(value: float) -> bool:
    # Keep realistic corridor for Moscow retail AI-95.
    return 40.0 <= value <= 90.0


def _is_cache_price_acceptable(value: float) -> bool:
    return MIN_REASONABLE_MOSCOW_PRICE <= value <= 90.0


def _dedup_preserve_order(values: list[float]) -> list[float]:
    seen: set[float] = set()
    out: list[float] = []
    for item in values:
        v = round(item, 2)
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _extract_prices_from_html(html: str) -> list[float]:
    text = (html or "").lower()
    def _score_ctx(ctx: str) -> int:
        score = 0
        if any(w in ctx for w in ("сейчас", "сегодня", "current", "today", "now")):
            score += 4
        if any(w in ctx for w in ("аи-95", "аи 95", "ai-95", "ai 95")):
            score += 3
        if "моск" in ctx:
            score += 1
        if any(w in ctx for w in ("аи-100", "аи 100", "ai-100", "ai 100", "дт", "diesel", "аи-92", "ai-92")):
            score -= 4
        return score

    def _pick_best(values_with_score_pos: list[tuple[float, int, int]]) -> list[float]:
        if not values_with_score_pos:
            return []
        # Prefer higher context score; for equal score prefer later occurrence in page
        # (usually freshest value in dynamic/stat pages).
        ranked = sorted(values_with_score_pos, key=lambda x: (x[1], x[2]), reverse=True)
        seen: set[float] = set()
        out: list[float] = []
        for value, _, _ in ranked:
            v = round(value, 2)
            if v in seen:
                continue
            seen.add(v)
            out.append(v)
        return out

    # 1) Strong contextual patterns near AI-95 label.
    # PetrolPlus dedicated page exposes current value via itemprop="price".
    schema_price_matches = re.finditer(
        r'itemprop\s*=\s*"price"[^>]{0,80}>(\d{2,3}(?:[\.,]\d{1,2})?)<',
        text,
        flags=re.IGNORECASE,
    )
    schema_scored: list[tuple[float, int, int]] = []
    for m in schema_price_matches:
        value = _to_float(m.group(1))
        if _in_plausible_range(value):
            ctx = text[max(0, m.start() - 120) : min(len(text), m.end() + 120)]
            s = 6
            if "pricecurrency" in ctx and "rub" in ctx:
                s += 2
            if any(w in ctx for w in ("сейчас", "today", "current", "now")):
                s += 2
            schema_scored.append((value, s, m.start()))
    if schema_scored:
        ranked = sorted(schema_scored, key=lambda x: (x[1], x[2]), reverse=True)
        return _dedup_preserve_order([x[0] for x in ranked])

    primary_patterns = [
        r"(?:аи|ai)\s*[-–]?\s*95[^0-9]{0,45}(?:сейчас|цена|стоимость)?[^0-9]{0,15}(\d{2,3}(?:[\.,]\d{1,2})?)",
        r"(\d{2,3}(?:[\.,]\d{1,2})?)[^0-9]{0,8}(?:р|руб|₽)[^a-zа-я0-9]{0,30}(?:аи|ai)\s*[-–]?\s*95",
        r"(?:аи|ai)\s*[-–]?\s*95[^0-9]{0,25}(\d{2,3}(?:[\.,]\d{1,2})?)[^a-zа-я0-9]{0,12}(?:руб\/л|р\/л|руб|₽)",
    ]

    prices: list[float] = []
    scored: list[tuple[float, int, int]] = []
    for pattern in primary_patterns:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _to_float(m.group(1))
            if _in_plausible_range(value):
                prices.append(value)
                ctx = text[max(0, m.start() - 80) : min(len(text), m.end() + 80)]
                scored.append((value, _score_ctx(ctx), m.start()))
    if prices:
        best = _pick_best(scored)
        return best if best else _dedup_preserve_order(prices)

    # 2) Relaxed fallback for messy pages.
    fallback_patterns = [
        r"(?:аи|ai)\s*[-–]?\s*95[^0-9]{0,60}(\d{2,3}(?:[\.,]\d{1,2})?)",
        r"(?:сейчас|цена|стоимость)[^0-9]{0,25}(\d{2,3}(?:[\.,]\d{1,2})?)[^a-zа-я0-9]{0,6}(?:р|руб|₽)",
        r"(?:аи|ai)\s*95[^0-9]{0,120}(\d{2,3}(?:[\.,]\d{1,2})?)[^a-zа-я0-9]{0,10}(?:руб\/л|р\/л)",
    ]
    scored: list[tuple[float, int, int]] = []
    for pattern in fallback_patterns:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _to_float(m.group(1))
            if _in_plausible_range(value):
                prices.append(value)
                ctx = text[max(0, m.start() - 80) : min(len(text), m.end() + 80)]
                scored.append((value, _score_ctx(ctx), m.start()))
        if prices:
            break

    best = _pick_best(scored)
    return best if best else _dedup_preserve_order(prices)


def _extract_change_pct_from_html(html: str, current_price: float) -> float | None:
    text = (html or "").lower()
    for m in re.finditer(r"([+-]?\d{1,2}(?:[\.,]\d{1,3})?)\s*%", text, flags=re.IGNORECASE):
        value = _to_float(m.group(1))
        if abs(value) > 20:
            continue
        ctx = text[max(0, m.start() - 90) : min(len(text), m.end() + 40)]
        if any(token in ctx for token in ("измен", "динамик", "сут", "день", "24", "today", "daily")):
            return value

    abs_patterns = [
        r"(?:изменени[ея]|динамик)[^0-9+-]{0,40}([+-]?\d{1,2}(?:[\.,]\d{1,3})?)\s*(?:р|руб|₽)",
        r"(?:сут|день|24\s*ч)[^0-9+-]{0,30}([+-]?\d{1,2}(?:[\.,]\d{1,3})?)\s*(?:р|руб|₽)",
    ]
    for pattern in abs_patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m and current_price > 0:
            delta_rub = _to_float(m.group(1))
            return (delta_rub / current_price) * 100.0

    return None


def _extract_period_change_pct_from_html(html: str, current_price: float, period: str) -> float | None:
    text = (html or "").lower()
    if period == "7d":
        tokens = ("недел", "7д", "7 д", "7 day", "week")
    elif period == "30d":
        tokens = ("месяц", "30д", "30 д", "30 day", "month")
    else:
        return None

    for m in re.finditer(r"([+-]?\d{1,2}(?:[\.,]\d{1,3})?)\s*%", text, flags=re.IGNORECASE):
        value = _to_float(m.group(1))
        if abs(value) > 50:
            continue
        ctx = text[max(0, m.start() - 120) : min(len(text), m.end() + 120)]
        if any(token in ctx for token in tokens):
            return value

    abs_patterns = [
        r"(?:изменени[ея]|динамик)[^0-9+-]{0,50}([+-]?\d{1,2}(?:[\.,]\d{1,3})?)\s*(?:р|руб|₽)",
    ]
    for pattern in abs_patterns:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            ctx = text[max(0, m.start() - 120) : min(len(text), m.end() + 120)]
            if not any(token in ctx for token in tokens):
                continue
            if current_price > 0:
                delta_rub = _to_float(m.group(1))
                return (delta_rub / current_price) * 100.0
    return None


def _round_change(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)


def _sanitize_change(value: float | None, max_abs_pct: float) -> float | None:
    v = _round_change(value)
    if v is None:
        return None
    if abs(v) > max_abs_pct:
        return None
    return v


def _pct_change(current: float, previous: float) -> float | None:
    if previous <= 0:
        return None
    return (current - previous) / previous * 100.0


def _is_reasonable_vs_reference(candidate: float, reference: float | None) -> bool:
    if reference is None or reference <= 0:
        return True
    pct = _pct_change(candidate, reference)
    if pct is None:
        return True
    return abs(pct) <= MAX_REASONABLE_JUMP_PCT


def _change_from_history_hours(current_price: float, now: datetime, hours: int) -> float | None:
    cutoff = (now - timedelta(hours=hours)).isoformat(timespec="seconds")
    row = get_fuel95_latest_before(cutoff)
    if not row:
        return None
    previous_price = float(row[0])
    try:
        previous_ts = datetime.fromisoformat(str(row[1]))
    except (TypeError, ValueError):
        return None
    # Ignore stale historical anchors that are too far from target window.
    # For 24h we allow +/-12h drift; for bigger windows allow up to 25% drift.
    drift_hours = abs((now - previous_ts).total_seconds() / 3600.0 - hours)
    allowed_drift = 12.0 if hours <= 24 else max(24.0, hours * 0.25)
    if drift_hours > allowed_drift:
        return None
    if not _is_reasonable_vs_reference(current_price, previous_price):
        return None
    return _round_change(_pct_change(current_price, previous_price))


async def fetch_fuel95_moscow_data(settings: Settings) -> dict[str, float | None]:
    urls = [settings.fuel95_source_url, *FALLBACK_FUEL95_URLS]
    unique_urls: list[str] = []
    for url in urls:
        if url not in unique_urls:
            unique_urls.append(url)

    cached_ref_row = get_cache_value(CACHE_KEY_FUEL95_MOSCOW)
    ref_price: float | None = None
    if cached_ref_row and cached_ref_row[0]:
        try:
            rp = float(cached_ref_row[0])
            ref_price = rp if _is_cache_price_acceptable(rp) else None
        except ValueError:
            ref_price = None
    if ref_price is None:
        history_ref = get_latest_fuel95_in_range(MIN_REASONABLE_MOSCOW_PRICE, 90.0)
        if history_ref:
            try:
                ref_price = float(history_ref[0])
            except (TypeError, ValueError):
                ref_price = None

    for url in unique_urls:
        try:
            html = await request_text(service="fuel95", method="GET", url=url, retries=0, timeout=8.0)
            prices = _extract_prices_from_html(html)
            if prices:
                now = datetime.now()
                selected: float | None = None
                for p in prices:
                    pv = round(p, 2)
                    if _is_reasonable_vs_reference(pv, ref_price):
                        selected = pv
                        break
                if selected is None:
                    # All candidates look like outliers versus last stable value.
                    continue
                value = selected
                change = _sanitize_change(_extract_change_pct_from_html(html, value), MAX_24H_CHANGE_PCT)
                change_7d = _sanitize_change(_extract_period_change_pct_from_html(html, value, "7d"), MAX_7D_CHANGE_PCT)
                change_30d = _sanitize_change(_extract_period_change_pct_from_html(html, value, "30d"), MAX_30D_CHANGE_PCT)
                add_fuel95_history(price=value, created_at=now.isoformat(timespec="seconds"))
                if change is None:
                    change = _sanitize_change(_change_from_history_hours(value, now, 24), MAX_24H_CHANGE_PCT)
                if change_7d is None:
                    change_7d = _sanitize_change(_change_from_history_hours(value, now, 24 * 7), MAX_7D_CHANGE_PCT)
                if change_30d is None:
                    change_30d = _sanitize_change(_change_from_history_hours(value, now, 24 * 30), MAX_30D_CHANGE_PCT)
                set_cache_value(CACHE_KEY_FUEL95_MOSCOW, str(value), now.isoformat(timespec="seconds"))
                set_cache_value(
                    CACHE_KEY_FUEL95_MOSCOW_CHANGE,
                    "" if change is None else str(change),
                    now.isoformat(timespec="seconds"),
                )
                set_cache_value(
                    CACHE_KEY_FUEL95_MOSCOW_7D_CHANGE,
                    "" if change_7d is None else str(change_7d),
                    now.isoformat(timespec="seconds"),
                )
                set_cache_value(
                    CACHE_KEY_FUEL95_MOSCOW_30D_CHANGE,
                    "" if change_30d is None else str(change_30d),
                    now.isoformat(timespec="seconds"),
                )
                return {
                    "price_rub": value,
                    "change_24h_pct": change,
                    "change_7d_pct": change_7d,
                    "change_30d_pct": change_30d,
                }
        except ExternalAPIError:
            continue

    cached = get_cache_value(CACHE_KEY_FUEL95_MOSCOW)
    cached_change = get_cache_value(CACHE_KEY_FUEL95_MOSCOW_CHANGE)
    cached_change_7d = get_cache_value(CACHE_KEY_FUEL95_MOSCOW_7D_CHANGE)
    cached_change_30d = get_cache_value(CACHE_KEY_FUEL95_MOSCOW_30D_CHANGE)
    if cached and cached[0]:
        try:
            price = float(cached[0])
            if not _is_cache_price_acceptable(price):
                raise ValueError("cached fuel95 value out of acceptable range")
            change = float(cached_change[0]) if cached_change and cached_change[0] else None
            change_7d = float(cached_change_7d[0]) if cached_change_7d and cached_change_7d[0] else None
            change_30d = float(cached_change_30d[0]) if cached_change_30d and cached_change_30d[0] else None
            return {
                "price_rub": price,
                "change_24h_pct": _sanitize_change(change, MAX_24H_CHANGE_PCT),
                "change_7d_pct": _sanitize_change(change_7d, MAX_7D_CHANGE_PCT),
                "change_30d_pct": _sanitize_change(change_30d, MAX_30D_CHANGE_PCT),
            }
        except ValueError:
            pass

    history_row = get_latest_fuel95_in_range(MIN_REASONABLE_MOSCOW_PRICE, 90.0)
    if history_row:
        try:
            return {
                "price_rub": float(history_row[0]),
                "change_24h_pct": None,
                "change_7d_pct": None,
                "change_30d_pct": None,
            }
        except (TypeError, ValueError):
            pass

    if settings.fuel95_moscow_rub is not None:
        return {
            "price_rub": float(settings.fuel95_moscow_rub),
            "change_24h_pct": None,
            "change_7d_pct": None,
            "change_30d_pct": None,
        }

    raise ExternalAPIError(
        service="fuel95",
        kind="data_gap",
        message=f"fuel95 average is unavailable, checked {len(unique_urls)} urls",
    )


async def fetch_fuel95_moscow_avg(settings: Settings) -> float:
    data = await fetch_fuel95_moscow_data(settings)
    return float(data["price_rub"] or 0.0)



