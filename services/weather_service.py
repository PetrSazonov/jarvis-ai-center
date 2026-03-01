import logging
import asyncio
import re
from xml.etree import ElementTree as ET

from services.http_service import request_json, request_text


logger = logging.getLogger("purecompanybot")


GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GISMETEO_MOSCOW_RSS = "https://www.gismeteo.ru/rss/4368.xml"
MOSCOW_COORDS = (55.7522, 37.6156)
FAST_TIMEOUT_SECONDS = 6.0
_MOJIBAKE_MARKERS = ("Р ", "Р’", "РІ", "Ð", "Ñ", "вЂ", "�")


def _weather_text(code: int, lang: str) -> str:
    ru = {
        0: "ясно",
        1: "преимущественно ясно",
        2: "переменная облачность",
        3: "пасмурно",
        45: "туман",
        48: "изморозь",
        51: "морось",
        53: "морось",
        55: "сильная морось",
        61: "дождь",
        63: "дождь",
        65: "сильный дождь",
        71: "снег",
        73: "снег",
        75: "сильный снег",
        80: "ливень",
        81: "ливень",
        82: "сильный ливень",
        95: "гроза",
    }
    en = {
        0: "clear",
        1: "mainly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "fog",
        48: "rime fog",
        51: "drizzle",
        53: "drizzle",
        55: "dense drizzle",
        61: "rain",
        63: "rain",
        65: "heavy rain",
        71: "snow",
        73: "snow",
        75: "heavy snow",
        80: "rain showers",
        81: "rain showers",
        82: "violent rain showers",
        95: "thunderstorm",
    }
    data = en if lang == "en" else ru
    return data.get(code, "unknown")


def weather_emoji(summary: str) -> str:
    s = (summary or "").lower()
    if "гроза" in s or "thunder" in s:
        return "⛈️"
    if "дожд" in s or "rain" in s or "лив" in s:
        return "🌧️"
    if "снег" in s:
        return "❄️"
    if "ясно" in s or "clear" in s:
        return "☀️"
    if "пасмур" in s or "облач" in s or "overcast" in s:
        return "☁️"
    return "🌤️"


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _looks_like_mojibake(text: str) -> bool:
    sample = (text or "").strip()
    if not sample:
        return False
    marker_hits = sum(1 for marker in _MOJIBAKE_MARKERS if marker in sample)
    if marker_hits >= 2:
        return True
    if len(sample) >= 40 and sample.count("Р") >= 6:
        return True
    return False


def clean_weather_summary(summary: str) -> str:
    text = (summary or "").replace("\r\n", "\n").strip()
    if not text:
        return ""

    cleaned_lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        cache_match = re.search(r"\s*\((?:кэш|cache)\s+([^)]*)\)\s*$", line, flags=re.IGNORECASE)
        if cache_match:
            cache_payload = cache_match.group(1).strip()
            payload_norm = cache_payload.lower()
            cache_age_ok = bool(re.fullmatch(r"\d{1,3}\s*(м|мин|min|m|ч|h)", payload_norm))
            if _looks_like_mojibake(cache_payload) or not cache_age_ok:
                line = line[: cache_match.start()].rstrip()

        if line:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def _city_locative(city_name: str, lang: str) -> str:
    if lang != "ru":
        return city_name
    special = {
        "москва": "Москве",
        "санкт-петербург": "Санкт-Петербурге",
    }
    key = city_name.strip().lower()
    return special.get(key, city_name)


def _build_5d_trend(today_max: float | None, next_max_values: list[float], lang: str) -> str:
    if today_max is None or not next_max_values:
        return ""

    avg_next = sum(next_max_values) / len(next_max_values)
    delta = avg_next - today_max

    if lang == "en":
        if delta > 0.5:
            return f"5-day trend: generally warmer by about {delta:.1f}C than today."
        if delta < -0.5:
            return f"5-day trend: generally colder by about {abs(delta):.1f}C than today."
        return "5-day trend: close to today's temperatures."

    if delta > 0.5:
        return f"Тренд на 5 дней: в среднем теплее примерно на {delta:.1f}C, чем сегодня."
    if delta < -0.5:
        return f"Тренд на 5 дней: в среднем холоднее примерно на {abs(delta):.1f}C, чем сегодня."
    return "Тренд на 5 дней: температура будет близкой к сегодняшней."


def _build_precipitation_hint(hourly: dict, lang: str) -> str:
    times = hourly.get("time") or []
    probs = hourly.get("precipitation_probability") or []
    amounts = hourly.get("precipitation") or []

    if not times or not probs or not amounts:
        return ""

    candidate_indexes: list[int] = []
    for i, _ in enumerate(times[:24]):
        p = float(probs[i]) if i < len(probs) and probs[i] is not None else 0.0
        a = float(amounts[i]) if i < len(amounts) and amounts[i] is not None else 0.0
        if p >= 40.0 or a >= 0.2:
            candidate_indexes.append(i)

    if not candidate_indexes:
        return "Осадков в ближайшие 24 часа не ожидается." if lang == "ru" else "No precipitation expected in the next 24 hours."

    start = min(candidate_indexes)
    end = max(candidate_indexes)
    start_h = times[start][11:16] if len(times[start]) >= 16 else times[start]
    end_h = times[end][11:16] if len(times[end]) >= 16 else times[end]

    if lang == "ru":
        if start == end:
            return f"Осадки вероятны около {start_h}."
        return f"Осадки вероятны в интервале {start_h}-{end_h}."
    if start == end:
        return f"Precipitation is likely around {start_h}."
    return f"Precipitation is likely between {start_h} and {end_h}."


async def _fetch_gismeteo_moscow_summary(lang: str) -> str | None:
    xml_text = await request_text(
        service="gismeteo",
        method="GET",
        url=GISMETEO_MOSCOW_RSS,
        timeout=4.0,
        retries=0,
    )
    root = ET.fromstring(xml_text)
    item = root.find(".//item")
    if item is None:
        return None

    title = (item.findtext("title") or "").strip()
    description = _strip_html(item.findtext("description") or "")
    if not title and not description:
        return None

    if lang == "en":
        return f"Weather in Moscow (Gismeteo): {title}. {description}".strip()
    return f"Погода в Москве (Gismeteo): {title}. {description}".strip()


async def _fetch_open_meteo_bundle(city: str, lang: str) -> tuple[str, str]:
    city_norm = (city or "").strip().lower()
    if city_norm in {"moscow", "москва"}:
        lat, lon = MOSCOW_COORDS
        city_name = "Moscow" if lang == "en" else "Москва"
    else:
        geo = await request_json(
            service="open_meteo_geocode",
            method="GET",
            url=GEOCODE_URL,
            params={"name": city, "count": 1, "language": lang, "format": "json"},
            timeout=FAST_TIMEOUT_SECONDS,
            retries=0,
        )
        results = geo.get("results") or []
        if not results:
            if lang == "en":
                return f"Weather: city '{city}' not found", ""
            return f"Погода: город '{city}' не найден", ""

        loc = results[0]
        lat = loc["latitude"]
        lon = loc["longitude"]
        city_name = loc.get("name", city)

    forecast = await request_json(
        service="open_meteo_forecast",
        method="GET",
        url=FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,precipitation,wind_speed_10m,weather_code",
            "hourly": "precipitation_probability,precipitation",
            "daily": "temperature_2m_max,temperature_2m_min",
            "forecast_days": 6,
            "timezone": "auto",
        },
        timeout=FAST_TIMEOUT_SECONDS,
        retries=0,
    )

    current = forecast.get("current", {})
    temp = current.get("temperature_2m")
    feels = current.get("apparent_temperature")
    wind = current.get("wind_speed_10m")
    precipitation = current.get("precipitation")
    code = int(current.get("weather_code", -1))
    w_text = _weather_text(code, lang)

    daily = forecast.get("daily", {})
    max_values = daily.get("temperature_2m_max") or []
    today_max = float(max_values[0]) if max_values else None
    next_five = [float(v) for v in max_values[1:6]] if len(max_values) > 1 else []
    trend = _build_5d_trend(today_max, next_five, lang)
    precip_hint = _build_precipitation_hint(forecast.get("hourly") or {}, lang)

    if lang == "en":
        summary = (
            f"Weather in {city_name}: {temp}C, feels like {feels}C, "
            f"{w_text}, wind {wind} km/h, precipitation {precipitation} mm"
        )
    else:
        summary = (
            f"Погода в {_city_locative(city_name, lang)}: {temp}C, ощущается как {feels}C, "
            f"{w_text}, ветер {wind} км/ч, осадки {precipitation} мм"
        )

    detail_lines = [x for x in [precip_hint, trend] if x]
    return summary, "\n".join(detail_lines)


async def fetch_weather_summary(city: str, lang: str = "ru") -> str:
    city_norm = (city or "").strip().lower()

    gismeteo_task = None
    if city_norm in {"moscow", "москва"}:
        gismeteo_task = asyncio.create_task(_fetch_gismeteo_moscow_summary(lang))

    open_task = asyncio.create_task(_fetch_open_meteo_bundle(city, lang))

    gismeteo_summary: str | None = None
    open_summary = ""
    trend = ""

    try:
        open_summary, trend = await open_task
    except Exception:
        if gismeteo_task:
            try:
                gismeteo_summary = await gismeteo_task
            except Exception as exc:
                logger.debug("event=weather_gismeteo_fallback error=%s", exc.__class__.__name__)
                gismeteo_summary = None
        if gismeteo_summary:
            return clean_weather_summary(gismeteo_summary)
        raise

    if gismeteo_task:
        try:
            gismeteo_summary = await gismeteo_task
        except Exception as exc:
            logger.debug("event=weather_gismeteo_fallback error=%s", exc.__class__.__name__)
            gismeteo_summary = None

    if gismeteo_summary:
        if trend:
            return clean_weather_summary(f"{gismeteo_summary}\n{trend}")
        return clean_weather_summary(gismeteo_summary)

    if trend:
        return clean_weather_summary(f"{open_summary}\n{trend}")
    return clean_weather_summary(open_summary)
