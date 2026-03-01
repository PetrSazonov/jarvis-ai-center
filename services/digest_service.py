import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
import logging
import re

from core.settings import Settings
from db import get_cache_value, set_cache_value
from services.crypto_service import fetch_prices
from services.facts_service import fetch_interesting_fact
from services.fitness_plan_service import pick_workout_of_day, weekday_plan_slot
from services.forex_service import fetch_usd_eur_to_rub
from services.fuel_service import fetch_fuel95_moscow_data
from services.http_service import ExternalAPIError
from services.llm_enhancer_service import enhance_news_titles
from services.messages import t
from services.news_service import fetch_headlines, fetch_topic_links
from services.text_clean_service import normalize_display_text
from services.time_service import now_dt
from services.weather_service import clean_weather_summary, fetch_weather_summary


logger = logging.getLogger("purecompanybot")

COMPACT_MAX_CHARS = 1500
EXPANDED_MAX_CHARS = 3200
COMPACT_NEWS_ITEMS = 3
EXPANDED_NEWS_ITEMS = 4
CACHE_KEY_WEATHER = "weather:last:summary"
CACHE_WEATHER_TTL_MINUTES = 180


@dataclass(frozen=True)
class DigestPayload:
    text: str
    parse_mode: str | None = None


@dataclass(frozen=True)
class DigestRender:
    compact: DigestPayload
    expanded: DigestPayload
    workout_id: int | None = None


def _fmt_change(value: float | None) -> str:
    if value is None:
        return "⚪ н/д"
    v = float(value or 0)
    icon = "🟢" if v > 0 else "🔴" if v < 0 else "⚪"
    return f"{icon} {v:+.1f}%"


def _currency_code(code: str) -> str:
    return (code or "").upper()


def day_number_on_planet(birth_date: date, today: date) -> int:
    return (today - birth_date).days + 1


def _days_word_ru(n: int) -> str:
    rem10 = n % 10
    rem100 = n % 100
    if rem10 == 1 and rem100 != 11:
        return "день"
    if rem10 in {2, 3, 4} and rem100 not in {12, 13, 14}:
        return "дня"
    return "дней"


def _shorten_title(title: str, max_len: int = 170) -> str:
    clean = " ".join((title or "").split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"


def _news_line_with_source(emoji: str, title: str, url: str | None = None) -> str:
    short = escape(_shorten_title(title))
    if url:
        return f"{emoji} <a href=\"{escape(url, quote=True)}\">{short}</a>"
    return f"{emoji} {short}"


def _news_emoji(title: str, topic: str | None = None) -> str:
    t = (title or "").lower()
    if any(k in t for k in ("dota", "дота", "киберспорт", "esports", "the international")):
        return "🎮"
    if any(k in t for k in ("ufc", "mma", "бой", "поедин", "нокаут", "fight")):
        return "🥊"
    if any(k in t for k in ("openai", "chatgpt", "llm", "нейросет", "искусствен")):
        return "🧠"
    if any(k in t for k in ("bitcoin", "ethereum", "крипт", "blockchain", "btc", "eth")):
        return "₿"
    if any(k in t for k in ("мото", "байк", "motogp", "ducati", "yamaha", "honda", "kawasaki", "ktm")):
        return "🏍️"
    if any(k in t for k in ("робот", "технолог", "it", "software", "разработ", "ai ", "ии ")):
        return "🛠️"
    if any(k in t for k in ("лекар", "меди", "allerg", "здоров")):
        return "🧬"
    if (topic or "").lower() == "спорт":
        return "🥊"
    return "📰"


def _news_freshness_line(items: list[dict[str, str]], lang: str) -> str | None:
    latest_ts = 0.0
    for item in items:
        raw = str(item.get("published_ts", "0") or "0")
        try:
            ts = float(raw)
        except ValueError:
            ts = 0.0
        if ts > latest_ts:
            latest_ts = ts
    if latest_ts <= 0:
        return None
    updated = datetime.fromtimestamp(latest_ts)
    if lang == "ru":
        return f"⏱️ Новости обновлены: {updated:%d.%m %H:%M}"
    return f"⏱️ News updated: {updated:%Y-%m-%d %H:%M}"


def _weather_emoji(summary: str) -> str:
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


def _pick_by_seed(options: list[str], seed: int) -> str:
    if not options:
        return ""
    return options[seed % len(options)]


def _moto_block(settings: Settings, today: date, seed: int) -> list[str]:
    start_month, start_day = settings.moto_season_start_mmdd
    start_this_year = date(today.year, start_month, start_day)
    season_end = date(today.year, 10, 15)

    def countdown_line(target: date) -> str:
        days = (target - today).days
        return f"🏁 До мотосезона {target.year} осталось {days} {_days_word_ru(days)}."

    april_first = date(today.year, 4, 1)
    if today < april_first:
        return [countdown_line(start_this_year)]
    if april_first <= today < start_this_year:
        days = (start_this_year - today).days
        return [f"🏍️ Уже скоро: до старта сезона {days} {_days_word_ru(days)}."]
    if start_this_year <= today <= season_end:
        return [
            _pick_by_seed(
                [
                    "🏍️ Сезон идет: кайфуй от дороги, но держи запас дистанции.",
                    "🏍️ Сезон в деле: плавный темп и дисциплина важнее скорости.",
                    "🏍️ Проверь технику перед выездом и катай осознанно.",
                ],
                seed,
            )
        ]
    if season_end < today <= date(today.year, 11, 30):
        return [
            _pick_by_seed(
                [
                    "🤝 Финал сезона: время аккуратно закрывать байк в межсезонье.",
                    "🤝 Заверши сезон спокойно: техобслуживание и восстановление.",
                    "🤝 Сезон позади: подготовь план апгрейдов и тренировок на зиму.",
                ],
                seed,
            )
        ]
    next_start = date(today.year + 1, start_month, start_day)
    return [countdown_line(next_start)]


def _extract_temp_c(text: str) -> float | None:
    m = re.search(r"(-?\d+(?:[\.,]\d+)?)\s*C", text)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def _cache_weather_get_fresh() -> str | None:
    row = get_cache_value(CACHE_KEY_WEATHER)
    if not row or not row[0] or not row[1]:
        return None
    try:
        payload = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary")
    if not summary:
        return None
    try:
        updated_at = datetime.fromisoformat(str(row[1]))
    except ValueError:
        return None
    age_min = (datetime.now() - updated_at).total_seconds() / 60
    if age_min > CACHE_WEATHER_TTL_MINUTES:
        return None
    clean = clean_weather_summary(str(summary))
    if not clean:
        return None
    if clean != str(summary):
        set_cache_value(
            CACHE_KEY_WEATHER,
            json.dumps({"summary": clean, "city": str(payload.get("city") or "")}, ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds"),
        )
    return clean


def _cache_weather_set(summary: str, city: str) -> None:
    clean = clean_weather_summary(summary)
    if not clean:
        return
    set_cache_value(
        CACHE_KEY_WEATHER,
        json.dumps({"summary": clean, "city": city}, ensure_ascii=False),
        datetime.now().isoformat(timespec="seconds"),
    )


def _daypart(timezone_name: str | None) -> str:
    hour = now_dt(timezone_name).hour
    if 5 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 16:
        return "day"
    if 17 <= hour <= 22:
        return "evening"
    return "night"


def _build_practical_recommendation(weather_text: str, daypart: str) -> str:
    lower = (weather_text or "").lower()
    temp = _extract_temp_c(weather_text)

    if "снег" in lower:
        by_part = {
            "morning": "Снег: выйди на 15 минут раньше и выбери нескользкую обувь.",
            "day": "Снег: сгруппируй дела в один выход и оставь запас времени.",
            "evening": "Снег: вечером оставь только важные поездки.",
            "night": "Снег: поздние выезды лучше отменить.",
        }
        return by_part.get(daypart, by_part["day"])
    if "дожд" in lower or "лив" in lower or "rain" in lower:
        by_part = {
            "morning": "Дождь: возьми зонт и начни с задач, которые можно закрыть из дома.",
            "day": "Дождь: собери офлайн-дела в один маршрут.",
            "evening": "Дождь: к вечеру лучше завершить дела в помещении.",
            "night": "Дождь: в позднее время минимизируй перемещения.",
        }
        return by_part.get(daypart, by_part["day"])
    if "гроза" in lower or "thunder" in lower:
        return "Гроза: отмени лишние поездки и закрой ключевые дела заранее."
    if temp is not None and temp <= -7:
        return "Мороз: одевайся слоями и планируй короткие переходы между точками."
    if temp is not None and temp >= 27:
        return "Жара: держи воду рядом и сложные задачи делай в первой половине дня."

    generic = {
        "morning": "Начни с одной сложной задачи и закрой ее до первого отвлечения.",
        "day": "Сгруппируй звонки и организационные задачи в один короткий блок.",
        "evening": "Закрой 1-2 хвоста и подготовь короткий план на завтра.",
        "night": "Закрой только критичное и оставь силы на восстановление.",
    }
    return generic.get(daypart, generic["day"])


def _decorate_weather_block(weather_text: str) -> list[str]:
    parts = [line.strip() for line in (weather_text or "").splitlines() if line.strip()]
    if not parts:
        return ["Погода: временно недоступна"]

    lines: list[str] = [f"{_weather_emoji(parts[0])} {parts[0]}"]
    for extra in parts[1:]:
        lower = extra.lower()
        if "осад" in lower or "precip" in lower:
            lines.append(f"Осадки: {extra}")
        elif "тренд" in lower:
            lines.append(f"Тренд 5д: {extra}")
    return lines[:3]


def _daily_unique_fact(today: date, day_number: int) -> str:
    _ = day_number
    facts = [
        "Свет от Солнца до Земли идет примерно 8 минут 20 секунд.",
        "Международная космическая станция делает один оборот вокруг Земли примерно за 90 минут.",
        "На МКС за сутки можно увидеть около 16 восходов Солнца.",
        "Вода достигает максимальной плотности при температуре около +4°C.",
        "Тихий океан — самый большой и самый глубокий океан Земли.",
        "Полярная звезда находится почти точно над северным полюсом мира.",
        "Взрослый человек обычно делает около 12-20 вдохов в минуту в состоянии покоя.",
        "У Земли один естественный спутник — Луна.",
        "Венера вращается в сторону, противоположную большинству планет.",
        "Самая высокая точка Земли над уровнем моря — Эверест.",
    ]
    return facts[today.toordinal() % len(facts)]


def _daily_challenge(today: date, daypart: str, seed: int) -> str:
    common = [
        "Сделай 10 минут быстрой ходьбы после любого приема пищи.",
        "Выдели 15 минут на задачу, которую давно откладывал.",
        "Отключи уведомления на 60 минут и закрой один приоритет.",
        "Сделай 20 приседаний и 20 отжиманий в удобном темпе.",
        "Выпей 2 стакана воды до обеда.",
        "Запиши 3 коротких итога дня в заметки.",
    ]
    by_part = {
        "morning": "С утра 5 минут планирования: 1 главная цель и 2 второстепенные.",
        "day": "Днем сделай 3 минуты дыхания 4-6 перед следующей задачей.",
        "evening": "Вечером 10 минут без экрана перед сном.",
        "night": "Ночью заверши день: 1 мысль благодарности и отбой без ленты.",
    }
    options = [by_part.get(daypart, by_part["day"]), *common]
    return _pick_by_seed(options, seed + today.timetuple().tm_yday)


def _apply_char_budget(lines: list[str], max_chars: int) -> str:
    out: list[str] = []
    total = 0
    for line in lines:
        extra = len(line) + (1 if out else 0)
        if total + extra > max_chars:
            break
        out.append(line)
        total += extra
    if not out:
        return ""
    text = "\n".join(out).rstrip()
    if len(text) < max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


def _fit_difficulty(level: int | None) -> str:
    return "⚡" * max(1, min(5, int(level or 1)))


def _fit_minutes(duration_sec: int | None) -> int:
    if not duration_sec:
        return 30
    return max(1, round(int(duration_sec) / 60))


def _short_notes(value: str, max_len: int = 120) -> str:
    clean = " ".join((value or "").split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"


def _workout_day_block() -> tuple[list[str], list[str], int | None]:
    day_name, focus_tag = weekday_plan_slot()
    row = pick_workout_of_day()
    if not row:
        fallback = ["🏋️ Тренировка дня: открой /fit today, чтобы получить вариант.", ""]
        return fallback, fallback, None

    workout_id = int(row[0])
    title = str(row[1] or "").strip() or "Тренировка"
    difficulty = _fit_difficulty(int(row[4] or 2))
    minutes = _fit_minutes(int(row[5] or 0))
    notes = _short_notes(str(row[6] or ""))

    compact = [
        f"🏋️ Тренировка дня: {escape(title)} (~{minutes} мин, {difficulty})",
        f"Фокус: {escape(day_name)}. Открыть: /fit show {workout_id}",
        "",
    ]
    expanded = [
        f"🏋️ Тренировка дня: {escape(title)} (~{minutes} мин, {difficulty})",
        f"Фокус: {escape(day_name)}. Тег дня: #{escape(focus_tag)}",
        (f"План: {escape(notes)}" if notes else "План: открой /fit show для полной структуры."),
        f"Команды: /fit show {workout_id} или /fit done {workout_id}",
        "",
    ]
    return compact, expanded, workout_id


async def _load_market(settings: Settings, *, lang: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    lines: list[str] = []
    btc_label = t(lang, "market_btc")
    eth_label = t(lang, "market_eth")
    usd_rub_label = t(lang, "market_usd_rub")
    eur_rub_label = t(lang, "market_eur_rub")
    fuel95_label = t(lang, "market_fuel95")

    prices_result, fx_result, fuel_result = await asyncio.gather(
        fetch_prices(settings.coingecko_vs),
        fetch_usd_eur_to_rub(),
        fetch_fuel95_moscow_data(settings),
        return_exceptions=True,
    )

    try:
        if isinstance(prices_result, Exception):
            raise prices_result
        prices = prices_result
        btc = prices.get("bitcoin", {})
        eth = prices.get("ethereum", {})
        code = _currency_code(settings.coingecko_vs)
        lines.append(
            f"{btc_label}: {code} {float(btc.get(settings.coingecko_vs, 0)):.2f} | "
            f"24ч {_fmt_change(btc.get(f'{settings.coingecko_vs}_24h_change'))}"
        )
        lines.append(
            f"{eth_label}: {code} {float(eth.get(settings.coingecko_vs, 0)):.2f} | "
            f"24ч {_fmt_change(eth.get(f'{settings.coingecko_vs}_24h_change'))}"
        )
    except ExternalAPIError as exc:
        errors.append(f"coin:{exc.kind}")
    except Exception as exc:
        errors.append(f"coin:{exc.__class__.__name__}")

    try:
        if isinstance(fx_result, Exception):
            raise fx_result
        fx = fx_result
        lines.append(f"{usd_rub_label}: RUB {float(fx.get('usd_rub', 0)):.2f} | 24ч {_fmt_change(fx.get('usd_rub_24h_change'))}")
        lines.append(f"{eur_rub_label}: RUB {float(fx.get('eur_rub', 0)):.2f} | 24ч {_fmt_change(fx.get('eur_rub_24h_change'))}")
    except ExternalAPIError as exc:
        errors.append(f"fx:{exc.kind}")
    except Exception as exc:
        errors.append(f"fx:{exc.__class__.__name__}")

    try:
        if isinstance(fuel_result, Exception):
            raise fuel_result
        fuel95 = fuel_result
        lines.append(
            f"{fuel95_label}: RUB {float(fuel95.get('price_rub') or 0):.2f} | "
            f"24ч {_fmt_change(fuel95.get('change_24h_pct'))}"
        )
    except ExternalAPIError as exc:
        errors.append(f"fuel95:{exc.kind}")
        lines.append(f"{fuel95_label}: н/д")
    except Exception as exc:
        errors.append(f"fuel95:{exc.__class__.__name__}")
        lines.append(f"{fuel95_label}: н/д")

    if not lines:
        lines.append("Данные рынка временно недоступны" if lang == "ru" else "Market data is temporarily unavailable")

    return [normalize_display_text(x) for x in lines], errors


async def build_digest_render(settings: Settings, *, morning_mode: bool) -> DigestRender:
    cached_weather = _cache_weather_get_fresh()
    if cached_weather:
        market_result, topic_links_result = await asyncio.gather(
            _load_market(settings, lang=settings.default_lang),
            fetch_topic_links(limit_total=4),
            return_exceptions=True,
        )
        weather_result = cached_weather
    else:
        market_result, weather_result, topic_links_result = await asyncio.gather(
            _load_market(settings, lang=settings.default_lang),
            fetch_weather_summary(settings.weather_city, settings.default_lang),
            fetch_topic_links(limit_total=4),
            return_exceptions=True,
        )
    market_lines = (
        market_result[0]
        if not isinstance(market_result, Exception)
        else (["Данные рынка временно недоступны"] if settings.default_lang == "ru" else ["Market data is temporarily unavailable"])
    )
    weather = (
        weather_result
        if not isinstance(weather_result, Exception)
        else ("Погода временно недоступна" if settings.default_lang == "ru" else "Weather is temporarily unavailable")
    )
    if isinstance(weather_result, str):
        _cache_weather_set(weather_result, settings.weather_city)
    topic_links = topic_links_result if not isinstance(topic_links_result, Exception) else []

    if not topic_links:
        try:
            headlines = await fetch_headlines(limit=4)
            topic_links = [{"topic": "", "title": h, "url": ""} for h in headlines]
        except ExternalAPIError:
            topic_links = [
                {
                    "topic": "",
                    "title": ("Новости временно недоступны" if settings.default_lang == "ru" else "News is temporarily unavailable"),
                    "url": "",
                }
            ]

    today = date.today()
    day_number = day_number_on_planet(settings.birth_date, today)
    part = _daypart(settings.timezone_name)
    recommendation = _build_practical_recommendation(weather, part)

    fact_result = await asyncio.gather(
        fetch_interesting_fact(today=today, lang=settings.default_lang),
        return_exceptions=True,
    )
    fact_raw = fact_result[0]
    if isinstance(fact_raw, Exception):
        fact = _daily_unique_fact(today, day_number)
    else:
        fact = str(fact_raw)

    challenge = _daily_challenge(today, part, seed=day_number)
    workout_compact, workout_expanded, workout_id = _workout_day_block()

    weather_lines = _decorate_weather_block(weather)
    raw_titles = [str(item.get("title", "")) for item in topic_links[:EXPANDED_NEWS_ITEMS]]
    try:
        enhanced_titles = await asyncio.wait_for(
            enhance_news_titles(settings=settings, titles=raw_titles, mode="fast"),
            timeout=min(2.0, max(0.7, settings.llm_enhancer_timeout_seconds)),
        )
    except asyncio.TimeoutError:
        logger.info("event=digest_news_enhancer_timeout")
        enhanced_titles = raw_titles
    news_items = topic_links[:EXPANDED_NEWS_ITEMS]
    news_lines: list[str] = []
    for item, title in zip(news_items, enhanced_titles):
        emoji = _news_emoji(item.get("title", ""), item.get("topic"))
        url = item.get("url") or None
        news_lines.append(_news_line_with_source(emoji, title, url))
    freshness_line = _news_freshness_line(news_items, settings.default_lang)

    if morning_mode:
        header = [f"🪐 Доброе утро. Сегодня твой {day_number}-й день на этой планете.", ""]
    else:
        header = [f"🪐 Сегодня твой {day_number}-й день на этой планете.", ""]

    moto = [*_moto_block(settings, today, seed=day_number), ""]
    market = ["💹 Рынок:", *market_lines, ""]
    weather_block = [*weather_lines, ""]
    news_block_expanded = ["🗞️ Новости:", *news_lines]
    news_block_compact = ["🗞️ Новости:", *news_lines[:COMPACT_NEWS_ITEMS]]
    if freshness_line:
        news_block_expanded.append(freshness_line)
        news_block_compact.append(freshness_line)
    news_block_expanded.append("")
    news_block_compact.append("")

    bottom_compact = [
        f"Рекомендация: {escape(recommendation)}",
        f"Факт дня: {escape(fact)}",
    ]
    if morning_mode:
        bottom_compact.append(f"Задание дня: {escape(challenge)}")

    bottom_expanded = [
        f"Рекомендация: {escape(recommendation)}",
        f"Факт дня: {escape(fact)}",
        f"Задание дня: {escape(challenge)}",
    ]

    compact_lines = [*header, *moto, *market, *workout_compact, *weather_block[:2], *news_block_compact, *bottom_compact]
    expanded_lines = [*header, *moto, *market, *workout_expanded, *weather_block, *news_block_expanded, *bottom_expanded]

    return DigestRender(
        compact=DigestPayload(text=_apply_char_budget(compact_lines, COMPACT_MAX_CHARS), parse_mode="HTML"),
        expanded=DigestPayload(text=_apply_char_budget(expanded_lines, EXPANDED_MAX_CHARS), parse_mode="HTML"),
        workout_id=workout_id,
    )


async def safe_build_digest_render(settings: Settings, *, morning_mode: bool) -> DigestRender:
    try:
        return await build_digest_render(settings, morning_mode=morning_mode)
    except Exception as exc:
        logger.exception("event=digest_build_failed error=%s", exc)
        today = date.today()
        day_number = day_number_on_planet(settings.birth_date, today)
        lines = [
            f"🪐 Сегодня твой {day_number}-й день на этой планете.",
            "",
            "Погода: временно недоступна",
            "",
            "Рекомендация: Проверь приоритеты и закрой одну важную задачу без переключений.",
            f"Факт дня: {escape(_daily_unique_fact(today, day_number))}",
            "Задание дня: 10 минут фокус-режима без уведомлений.",
        ]
        payload = DigestPayload(text="\n".join(lines), parse_mode="HTML")
        return DigestRender(compact=payload, expanded=payload, workout_id=None)


async def build_digest_text(settings: Settings, *, morning_mode: bool) -> DigestPayload:
    return (await build_digest_render(settings, morning_mode=morning_mode)).compact


async def safe_build_digest_payload(settings: Settings, *, morning_mode: bool) -> DigestPayload:
    return (await safe_build_digest_render(settings, morning_mode=morning_mode)).compact


async def safe_build_digest_text(settings: Settings, *, morning_mode: bool) -> str:
    payload = await safe_build_digest_payload(settings, morning_mode=morning_mode)
    return payload.text



