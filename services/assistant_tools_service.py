import asyncio
from dataclasses import dataclass
from datetime import datetime
from html import escape as html_escape
from urllib.parse import quote_plus

from core.settings import Settings
from db import memory_list, todo_list_open
from services.assistant_intent_service import (
    INTENT_DIGEST,
    INTENT_PRICE,
    INTENT_PROFILE,
    INTENT_ROUTE,
    INTENT_STATUS,
    INTENT_TODAY,
    INTENT_WEATHER,
)
from services.crypto_service import fetch_prices
from services.digest_service import safe_build_digest_render
from services.fitness_plan_service import pick_workout_of_day
from services.forex_service import fetch_usd_eur_to_rub
from services.fuel_service import fetch_fuel95_moscow_data
from services.http_service import ExternalAPIError, healthcheck_json
from services.text_clean_service import normalize_display_text
from services.weather_service import clean_weather_summary, fetch_weather_summary, weather_emoji
from db import ping_db


HOME_COORDS = (55.688177, 37.865975)
WORK_COORDS = (55.468433, 37.576555)


@dataclass(frozen=True)
class ToolResult:
    text: str
    parse_mode: str | None = None
    disable_web_page_preview: bool = True


def _currency_code(code: str) -> str:
    return (code or "").upper()


def _fmt_change(value: float | None) -> str:
    if value is None:
        return "⚪ н/д"
    v = float(value or 0)
    icon = "🟢" if v > 0 else "🔴" if v < 0 else "⚪"
    return f"{icon} {v:+.1f}%"


def _updated_line(lang: str) -> str:
    now = datetime.now()
    if lang == "ru":
        return f"⏱ Обновлено: {now:%d.%m %H:%M}"
    return f"⏱ Updated: {now:%Y-%m-%d %H:%M}"


async def _tool_price(*, settings: Settings, lang: str) -> ToolResult:
    btc_label = "Биткоин" if lang == "ru" else "Bitcoin"
    eth_label = "Эфириум" if lang == "ru" else "Ethereum"
    usd_label = "Доллар/Рубль" if lang == "ru" else "USD/RUB"
    eur_label = "Евро/Рубль" if lang == "ru" else "EUR/RUB"
    fuel_label = "AI-95 Москва (средняя)" if lang == "ru" else "AI-95 Moscow (avg)"
    title = "📊 Рынок" if lang == "ru" else "📊 Market"
    lines: list[str] = [title, ""]

    prices_result, fx_result, fuel_result = await asyncio.gather(
        fetch_prices(settings.coingecko_vs),
        fetch_usd_eur_to_rub(),
        fetch_fuel95_moscow_data(settings),
        return_exceptions=True,
    )

    if not isinstance(prices_result, Exception):
        prices = prices_result
        btc = prices.get("bitcoin", {})
        eth = prices.get("ethereum", {})
        code = _currency_code(settings.coingecko_vs)
        lines.append(f"{btc_label}: {code} {float(btc.get(settings.coingecko_vs, 0)):.2f} | 24ч {_fmt_change(btc.get(f'{settings.coingecko_vs}_24h_change'))}")
        lines.append(f"{eth_label}: {code} {float(eth.get(settings.coingecko_vs, 0)):.2f} | 24ч {_fmt_change(eth.get(f'{settings.coingecko_vs}_24h_change'))}")
    if not isinstance(fx_result, Exception):
        fx = fx_result
        lines.append(f"{usd_label}: RUB {float(fx.get('usd_rub', 0)):.2f} | 24ч {_fmt_change(fx.get('usd_rub_24h_change'))}")
        lines.append(f"{eur_label}: RUB {float(fx.get('eur_rub', 0)):.2f} | 24ч {_fmt_change(fx.get('eur_rub_24h_change'))}")
    if not isinstance(fuel_result, Exception):
        fuel = fuel_result
        lines.append(f"{fuel_label}: RUB {float(fuel.get('price_rub') or 0):.2f} | 24ч {_fmt_change(fuel.get('change_24h_pct'))}")

    if len(lines) <= 2:
        msg = "Сервисы рынка временно недоступны." if lang == "ru" else "Market services are temporarily unavailable."
        lines.append(msg)
    lines.append("")
    lines.append(_updated_line(lang))
    return ToolResult(text="\n".join(lines))


async def _tool_weather(*, settings: Settings, lang: str) -> ToolResult:
    title = "🌦 Погода" if lang == "ru" else "🌦 Weather"
    try:
        summary = clean_weather_summary(await fetch_weather_summary(settings.weather_city, lang))
    except ExternalAPIError:
        msg = "Не удалось получить погоду." if lang == "ru" else "Could not fetch weather."
        return ToolResult(text=f"{title}\n\n{msg}")
    return ToolResult(text=f"{title}\n\n{weather_emoji(summary)} {summary}\n\n{_updated_line(lang)}")


async def _tool_digest(*, settings: Settings, lang: str) -> ToolResult:
    render = await safe_build_digest_render(settings, morning_mode=False)
    title = "📰 Дайджест" if lang == "ru" else "📰 Digest"
    return ToolResult(text=f"{title}\n\n{render.compact.text}", parse_mode=render.compact.parse_mode)


async def _tool_status(*, settings: Settings, lang: str) -> ToolResult:
    db_ok, db_note = ping_db()
    ollama_res, coingecko_res, cbr_res = await asyncio.gather(
        healthcheck_json(service="ollama", method="GET", url=settings.ollama_api_url.replace("/api/generate", "/api/tags")),
        healthcheck_json(service="coingecko", method="GET", url="https://api.coingecko.com/api/v3/ping"),
        healthcheck_json(service="cbr", method="GET", url="https://www.cbr-xml-daily.ru/daily_json.js"),
    )
    ollama_ok, ollama_note = ollama_res
    coingecko_ok, coingecko_note = coingecko_res
    cbr_ok, cbr_note = cbr_res
    title = "<b>Статус сервисов</b>" if lang == "ru" else "<b>Service Status</b>"
    core_ok = all([db_ok, ollama_ok, coingecko_ok, cbr_ok])
    lines = [
        title,
        "",
        f"Система: {'🟢' if core_ok else '🔴'}" if lang == "ru" else f"Core: {'🟢' if core_ok else '🔴'}",
        "",
        f"• Ollama: {'🟢' if ollama_ok else '🔴 (' + html_escape(ollama_note) + ')'}",
        f"• CoinGecko: {'🟢' if coingecko_ok else '🔴 (' + html_escape(coingecko_note) + ')'}",
        f"• CBR FX: {'🟢' if cbr_ok else '🔴 (' + html_escape(cbr_note) + ')'}",
        f"• DB: {'🟢' if db_ok else '🔴 (' + html_escape(db_note) + ')'}",
        "",
        _updated_line(lang),
    ]
    return ToolResult(text="\n".join(lines), parse_mode="HTML")


async def _tool_today(*, settings: Settings, user_id: int, lang: str) -> ToolResult:
    title = "🎯 Фокус дня" if lang == "ru" else "🎯 Focus of the day"
    lines = [title, ""]
    todos = todo_list_open(user_id=user_id, limit=3) if user_id > 0 else []
    if not todos:
        lines.append("🗂 Нет активных задач." if lang == "ru" else "🗂 No active tasks.")
    else:
        lines.append("🗂 Топ-3 задачи:" if lang == "ru" else "🗂 Top-3 tasks:")
        for todo_id, todo_text, _created_at in todos:
            lines.append(f"• #{int(todo_id)} {str(todo_text).strip()}")

    workout_row = pick_workout_of_day()
    if workout_row:
        lines.append("")
        lines.append(
            f"🏋️ Тренировка дня: #{int(workout_row[0])} {str(workout_row[1] or '').strip()}"
            if lang == "ru"
            else f"🏋️ Workout of the day: #{int(workout_row[0])} {str(workout_row[1] or '').strip()}"
        )

    lines.append("")
    lines.append(_updated_line(lang))
    return ToolResult(text=normalize_display_text("\n".join(lines)))


def _tool_route(*, target: str, lang: str) -> ToolResult:
    if target == "work":
        lat, lon = WORK_COORDS
        title = "Работа" if lang == "ru" else "Work"
    else:
        lat, lon = HOME_COORDS
        title = "Дом" if lang == "ru" else "Home"
    url = f"https://yandex.ru/maps/?mode=routes&rtext=~{quote_plus(f'{lat:.6f},{lon:.6f}')}&rtt=auto"
    if lang == "ru":
        text = f"🧭 Маршрут до точки «{title}»:\n{url}"
    else:
        text = f"🧭 Route to '{title}':\n{url}"
    return ToolResult(text=text, disable_web_page_preview=False)


def _tool_profile(*, user_id: int, lang: str) -> ToolResult:
    rows = memory_list(user_id=user_id, limit=20)
    title = "<b>Профиль памяти</b>" if lang == "ru" else "<b>Memory Profile</b>"
    if not rows:
        body = "Память пока пустая. Используйте /remember." if lang == "ru" else "Memory is empty. Use /remember."
        return ToolResult(text=f"{title}\n\n{body}", parse_mode="HTML")
    lines = [title, ""]
    for key, value, _updated_at in rows:
        lines.append(f"• <b>{key}</b>: {value}")
    lines.append("")
    lines.append(_updated_line(lang))
    return ToolResult(text="\n".join(lines), parse_mode="HTML")


async def run_assistant_tool(
    *,
    intent: str,
    settings: Settings,
    user_id: int,
    lang: str,
    args: dict[str, str] | None = None,
) -> ToolResult | None:
    data = args or {}
    if intent == INTENT_PRICE:
        return await _tool_price(settings=settings, lang=lang)
    if intent == INTENT_WEATHER:
        return await _tool_weather(settings=settings, lang=lang)
    if intent == INTENT_DIGEST:
        return await _tool_digest(settings=settings, lang=lang)
    if intent == INTENT_STATUS:
        return await _tool_status(settings=settings, lang=lang)
    if intent == INTENT_TODAY:
        return await _tool_today(settings=settings, user_id=user_id, lang=lang)
    if intent == INTENT_ROUTE:
        target = (data.get("target") or "").strip().lower()
        if target not in {"home", "work"}:
            target = "home"
        return _tool_route(target=target, lang=lang)
    if intent == INTENT_PROFILE:
        return _tool_profile(user_id=user_id, lang=lang)
    return None
