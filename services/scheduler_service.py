import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta

from aiogram import Bot

from core.settings import Settings
from db import (
    daily_checkin_recent,
    fitness_current_streak_days,
    fitness_stats_recent,
    set_cache_value,
    subs_due_within,
    todo_due_reminders,
    todo_mark_reminder_sent,
    todo_stats_recent,
    user_settings_get_full,
)
from services.crypto_service import fetch_prices
from services.digest_service import safe_build_digest_render
from services.forex_service import fetch_usd_eur_to_rub
from services.fuel_service import fetch_fuel95_moscow_data
from services.time_service import now_dt
from services.weather_service import fetch_weather_summary


CACHE_KEY_PRICE_COINGECKO = "price:last:coingecko"
CACHE_KEY_PRICE_FX = "price:last:fx"
CACHE_KEY_PRICE_FUEL95 = "price:last:fuel95"
CACHE_KEY_WEATHER = "weather:last:summary"


def _parse_hhmm(value: str) -> tuple[int, int]:
    hh, mm = value.split(":")
    return int(hh), int(mm)


def _next_run(now: datetime, slots: tuple[str, ...]) -> tuple[datetime, str]:
    candidates: list[tuple[datetime, str]] = []
    for slot in slots:
        hour, minute = _parse_hhmm(slot)
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        candidates.append((candidate, slot))

    candidates.sort(key=lambda x: x[0])
    return candidates[0]


def _in_quiet_hours(now: datetime, start_hhmm: str | None, end_hhmm: str | None) -> bool:
    if not start_hhmm or not end_hhmm:
        return False
    try:
        sh, sm = [int(x) for x in start_hhmm.split(":")]
        eh, em = [int(x) for x in end_hhmm.split(":")]
    except Exception:
        return False
    now_m = now.hour * 60 + now.minute
    start_m = sh * 60 + sm
    end_m = eh * 60 + em
    if start_m == end_m:
        return False
    if start_m < end_m:
        return start_m <= now_m < end_m
    return now_m >= start_m or now_m < end_m


def _build_weekly_reset_text(*, user_id: int, lang: str) -> str:
    since_iso = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
    done_count, open_count = todo_stats_recent(user_id=user_id, since_iso=since_iso)
    fit_total, _fit_rows = fitness_stats_recent(user_id=user_id, since_iso=since_iso)
    streak = fitness_current_streak_days(user_id=user_id)
    checkins = daily_checkin_recent(user_id=user_id, since_iso=since_iso, limit=7)
    subs_due = subs_due_within(user_id=user_id, days=7)
    energies = [int(x[3]) for x in checkins if x[3] is not None]
    avg_energy = (sum(energies) / len(energies)) if energies else None

    focuses: list[str] = []
    if open_count >= 5:
        focuses.append("Сократить открытый бэклог минимум на 3 задачи." if lang == "ru" else "Reduce open backlog by at least 3 tasks.")
    if fit_total < 3:
        focuses.append("Запланировать 2 тренировки на новую неделю." if lang == "ru" else "Plan 2 workouts for next week.")
    if avg_energy is not None and avg_energy < 6:
        focuses.append("Восстановление: 2 вечера без перегруза и ранний сон." if lang == "ru" else "Recovery: 2 lighter evenings and earlier sleep.")
    if subs_due:
        focuses.append(
            f"Проверить подписки: {', '.join(str(row[1]) for row in subs_due[:2])}."
            if lang == "ru"
            else f"Review subscriptions: {', '.join(str(row[1]) for row in subs_due[:2])}."
        )
    while len(focuses) < 3:
        focuses.append(
            "Каждый день закрывать один главный приоритет до обеда."
            if lang == "ru"
            else "Close one top priority before midday each day."
        )

    lines = ["📅 Sunday Reset / Weekly Review", ""]
    lines.append(f"✅ {'Задачи закрыто' if lang == 'ru' else 'Tasks done'}: {done_count}")
    lines.append(f"🗂 {'Открытые задачи' if lang == 'ru' else 'Open tasks'}: {open_count}")
    lines.append(f"🏋️ {'Тренировок' if lang == 'ru' else 'Workouts'}: {fit_total} | 🔥 {'серия' if lang == 'ru' else 'streak'} {streak}")
    if avg_energy is not None:
        lines.append(f"🔋 {'Средняя энергия' if lang == 'ru' else 'Avg energy'}: {avg_energy:.1f}/10")
    lines.append(f"💳 {'Подписок на 7 дней' if lang == 'ru' else 'Subscriptions due in 7d'}: {len(subs_due)}")
    lines.append("")
    lines.append("🎯 3 фокуса на неделю:" if lang == "ru" else "🎯 3 focuses for next week:")
    lines.extend([f"• {item}" for item in focuses[:3]])
    return "\n".join(lines)


async def auto_digest_worker(bot: Bot, settings: Settings, logger) -> None:
    if settings.digest_chat_id is None:
        logger.warning("event=auto_digest_skip reason=no_digest_chat_id")
        return

    logger.info(
        "event=auto_digest_start chat_id=%s slots=%s",
        settings.digest_chat_id,
        ",".join(settings.digest_times),
    )

    while True:
        try:
            now = now_dt(settings.timezone_name)
            target_dt, slot = _next_run(now, settings.digest_times)
            sleep_seconds = max(1.0, (target_dt - now).total_seconds())

            logger.info(
                "event=auto_digest_wait until=%s slot=%s sleep_seconds=%.0f",
                target_dt.isoformat(),
                slot,
                sleep_seconds,
            )
            await asyncio.sleep(sleep_seconds)

            profile = user_settings_get_full(settings.digest_chat_id) if settings.digest_chat_id > 0 else {}
            lang = str(profile.get("lang") or settings.default_lang)
            tz = profile.get("timezone_name") or settings.timezone_name
            city = profile.get("weather_city") or settings.weather_city
            digest_format = str(profile.get("digest_format") or "compact")
            quiet_start = str(profile.get("quiet_start") or "") or None
            quiet_end = str(profile.get("quiet_end") or "") or None

            runtime_settings = replace(
                settings,
                default_lang=lang,
                timezone_name=tz,
                weather_city=city,
            )
            now_slot = now_dt(runtime_settings.timezone_name)
            if _in_quiet_hours(now_slot, quiet_start, quiet_end):
                logger.info(
                    "event=auto_digest_skipped reason=quiet_hours chat_id=%s slot=%s quiet=%s-%s",
                    settings.digest_chat_id,
                    slot,
                    quiet_start,
                    quiet_end,
                )
                continue

            morning_mode = slot == "07:00"
            render = await safe_build_digest_render(runtime_settings, morning_mode=morning_mode)
            payload = render.expanded if digest_format == "expanded" else render.compact

            await bot.send_message(
                chat_id=settings.digest_chat_id,
                text=payload.text,
                parse_mode=payload.parse_mode,
                disable_web_page_preview=True,
            )
            logger.info("event=auto_digest_sent chat_id=%s slot=%s", settings.digest_chat_id, slot)
            if settings.digest_chat_id > 0 and now_slot.weekday() == 6 and slot == "21:00":
                weekly_text = _build_weekly_reset_text(user_id=settings.digest_chat_id, lang=lang)
                await bot.send_message(
                    chat_id=settings.digest_chat_id,
                    text=weekly_text,
                    disable_web_page_preview=True,
                )
                logger.info("event=auto_weekly_sent chat_id=%s", settings.digest_chat_id)
        except asyncio.CancelledError:
            logger.info("event=auto_digest_cancelled")
            raise
        except Exception as exc:
            logger.exception("event=auto_digest_error error=%s", exc)
            await asyncio.sleep(30)


async def auto_todo_reminder_worker(bot: Bot, settings: Settings, logger) -> None:
    if not bool(getattr(settings, "enable_task_reminders", True)):
        logger.info("event=todo_reminder_skip enabled=false")
        return

    interval = max(20, int(getattr(settings, "task_reminder_interval_seconds", 45)))
    logger.info("event=todo_reminder_start interval_seconds=%s", interval)

    while True:
        try:
            now_iso = now_dt(settings.timezone_name).isoformat(timespec="seconds")
            rows = todo_due_reminders(now_iso=now_iso, limit=40)
            if rows:
                logger.info("event=todo_reminder_batch size=%s", len(rows))
            for todo_id, user_id, text, due_date, remind_at in rows:
                task_title = " ".join(str(text or "").split())
                task_title = task_title[:180] + "..." if len(task_title) > 180 else task_title
                due_line = f"Срок: {due_date}" if due_date else "Срок не указан"
                reminder_line = f"Напоминание: {remind_at}" if remind_at else ""
                parts = [
                    "Напоминание по задаче",
                    f"#{todo_id} {task_title}",
                    due_line,
                ]
                if reminder_line:
                    parts.append(reminder_line)
                parts.append("Открыть Day OS: /today -> /todo")
                message = "\n".join(parts)
                try:
                    await bot.send_message(chat_id=user_id, text=message, disable_web_page_preview=True)
                    todo_mark_reminder_sent(todo_id=todo_id, sent_at=now_iso)
                    logger.info("event=todo_reminder_sent user_id=%s todo_id=%s", user_id, todo_id)
                except Exception as send_exc:  # noqa: BLE001
                    logger.warning(
                        "event=todo_reminder_send_failed user_id=%s todo_id=%s error=%s",
                        user_id,
                        todo_id,
                        send_exc.__class__.__name__,
                    )
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("event=todo_reminder_cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("event=todo_reminder_error error=%s", exc)
            await asyncio.sleep(30)


async def _prewarm_once(settings: Settings, logger) -> None:
    now_iso = datetime.now().isoformat(timespec="seconds")
    prices_res, fx_res, fuel_res, weather_res, digest_res = await asyncio.gather(
        fetch_prices(settings.coingecko_vs),
        fetch_usd_eur_to_rub(),
        fetch_fuel95_moscow_data(settings),
        fetch_weather_summary(settings.weather_city, settings.default_lang),
        safe_build_digest_render(settings, morning_mode=False),
        return_exceptions=True,
    )

    if not isinstance(prices_res, Exception):
        btc_data = prices_res.get("bitcoin", {})
        eth_data = prices_res.get("ethereum", {})
        btc_price = btc_data.get(settings.coingecko_vs)
        eth_price = eth_data.get(settings.coingecko_vs)
        if btc_price is not None and eth_price is not None:
            set_cache_value(
                CACHE_KEY_PRICE_COINGECKO,
                json.dumps(
                    {
                        "vs": settings.coingecko_vs,
                        "btc_price": float(btc_price),
                        "eth_price": float(eth_price),
                        "btc_change": btc_data.get(f"{settings.coingecko_vs}_24h_change"),
                        "eth_change": eth_data.get(f"{settings.coingecko_vs}_24h_change"),
                    },
                    ensure_ascii=False,
                ),
                now_iso,
            )

    if not isinstance(fx_res, Exception):
        usd_rub = fx_res.get("usd_rub")
        eur_rub = fx_res.get("eur_rub")
        if usd_rub is not None and eur_rub is not None:
            set_cache_value(
                CACHE_KEY_PRICE_FX,
                json.dumps(
                    {
                        "usd_rub": float(usd_rub),
                        "eur_rub": float(eur_rub),
                        "usd_change": fx_res.get("usd_rub_24h_change"),
                        "eur_change": fx_res.get("eur_rub_24h_change"),
                    },
                    ensure_ascii=False,
                ),
                now_iso,
            )

    if not isinstance(fuel_res, Exception):
        set_cache_value(
            CACHE_KEY_PRICE_FUEL95,
            json.dumps(
                {
                    "price_rub": float(fuel_res.get("price_rub") or 0),
                    "change_24h_pct": fuel_res.get("change_24h_pct"),
                },
                ensure_ascii=False,
            ),
            now_iso,
        )

    if not isinstance(weather_res, Exception):
        set_cache_value(
            CACHE_KEY_WEATHER,
            json.dumps({"summary": weather_res, "city": settings.weather_city}, ensure_ascii=False),
            now_iso,
        )

    if isinstance(digest_res, Exception):
        logger.debug("event=prewarm_digest_failed error=%s", digest_res.__class__.__name__)


async def auto_prewarm_worker(settings: Settings, logger) -> None:
    if not settings.enable_prewarm:
        logger.info("event=prewarm_skip enabled=false")
        return

    interval = max(60, int(settings.prewarm_interval_seconds))
    logger.info("event=prewarm_start interval_seconds=%s", interval)
    while True:
        try:
            await _prewarm_once(settings, logger)
            logger.info("event=prewarm_done")
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("event=prewarm_cancelled")
            raise
        except Exception as exc:
            logger.exception("event=prewarm_error error=%s", exc.__class__.__name__)
            await asyncio.sleep(30)
