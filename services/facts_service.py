from datetime import date

from services.http_service import ExternalAPIError, request_json


WIKIMEDIA_ONTHISDAY_URL = "https://api.wikimedia.org/feed/v1/wikipedia/{lang}/onthisday/all/{mm}/{dd}"


def _candidate_from_item(item: dict) -> str | None:
    text = (item.get("text") or item.get("extract") or "").strip()
    if len(text) < 40:
        return None
    year = item.get("year")
    if isinstance(year, int):
        return f"{year}: {text}"
    return text


def _extract_candidates(payload: dict) -> list[str]:
    out: list[str] = []
    for key in ("selected", "events"):
        rows = payload.get(key) or []
        if not isinstance(rows, list):
            continue
        for item in rows:
            if not isinstance(item, dict):
                continue
            candidate = _candidate_from_item(item)
            if candidate:
                out.append(candidate)
    return out


async def fetch_interesting_fact(*, today: date, lang: str = "ru") -> str:
    mm = f"{today.month:02d}"
    dd = f"{today.day:02d}"
    langs = [lang, "en"] if lang != "en" else ["en"]

    for code in langs:
        url = WIKIMEDIA_ONTHISDAY_URL.format(lang=code, mm=mm, dd=dd)
        try:
            payload = await request_json(
                service="wikimedia_onthisday",
                method="GET",
                url=url,
                headers={"User-Agent": "PureCompanyBot/1.0"},
                retries=1,
                timeout=12,
            )
        except ExternalAPIError:
            continue

        candidates = _extract_candidates(payload if isinstance(payload, dict) else {})
        if not candidates:
            continue
        index = (today.toordinal() + len(candidates)) % len(candidates)
        return candidates[index]

    raise ExternalAPIError(service="wikimedia_onthisday", kind="data_gap", message="no fact candidates")
