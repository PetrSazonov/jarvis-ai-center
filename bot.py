import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from dotenv import load_dotenv

from core.logging_setup import setup_logging
from core.settings import load_settings
from crypto_watch import crypto_worker
from db import init_db
from handlers.chat import build_chat_router
from handlers.commands import build_commands_router
from handlers.context import AppContext
from handlers.fitness import build_fitness_router
from handlers.growth import build_growth_router
from handlers.advanced_ops import build_advanced_ops_router
from handlers.ux_router import build_ux_router
from services.http_service import close_http_client
from services.scheduler_service import auto_digest_worker, auto_prewarm_worker, auto_todo_reminder_worker


async def main() -> None:
    load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)
    settings = load_settings()

    setup_logging(settings.log_level)
    logger = logging.getLogger("purecompanybot")

    init_db()
    logger.info("event=startup db_initialized=true")

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    known_commands = {
        "start",
        "menu",
        "price",
        "weather",
        "digest",
        "reset",
        "help",
        "status",
        "clean",
        "route",
        "fit",
        "todo",
        "today",
        "mission",
        "checkin",
        "startnow",
        "focus",
        "autopilot",
        "simulate",
        "premortem",
        "negotiate",
        "life360",
        "goal",
        "drift",
        "futureme",
        "crisis",
        "manual",
        "decide",
        "rule",
        "radar",
        "state",
        "reflect",
        "redteam",
        "scenario",
        "legacy",
        "score",
        "plan",
        "review",
        "weekly",
        "week",
        "settings",
        "export",
        "pro",
        "mode",
        "confidence",
        "profile",
        "timeline",
        "remember",
        "forget",
        "subs",
        "session",
        "boss",
        "arena",
        "rescue",
        "recap",
        "chronotwin",
        "boardroom",
        "legend",
    }
    app_ctx = AppContext(bot=bot, settings=settings, logger=logger, known_commands=known_commands)

    dp.include_router(build_fitness_router(app_ctx))
    dp.include_router(build_ux_router(app_ctx))
    dp.include_router(build_growth_router(app_ctx))
    dp.include_router(build_advanced_ops_router(app_ctx))
    dp.include_router(build_commands_router(app_ctx))
    dp.include_router(build_chat_router(app_ctx))

    crypto_task: asyncio.Task | None = None
    digest_task: asyncio.Task | None = None
    prewarm_task: asyncio.Task | None = None
    reminder_task: asyncio.Task | None = None

    async def on_startup() -> None:
        nonlocal crypto_task, digest_task, prewarm_task, reminder_task
        logger.info("event=bot_startup")
        if settings.fitness_vault_chat_id:
            logger.warning(
                "event=fitness_channel_watch chat_id=%s note='Проверь, что бот админ канала и получает channel_post'",
                settings.fitness_vault_chat_id,
            )

        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Открыть меню"),
                BotCommand(command="menu", description="Разделы Day OS"),
                BotCommand(command="today", description="Фокус дня"),
                BotCommand(command="todo", description="Задачи"),
                BotCommand(command="focus", description="Фокус-сессия"),
                BotCommand(command="checkin", description="Вечерний чек-ин"),
                BotCommand(command="week", description="Обзор недели"),
                BotCommand(command="review", description="Ретро недели"),
                BotCommand(command="decide", description="AI-помощь в решениях"),
            ]
        )

        if settings.enable_crypto_watcher:
            logger.info("event=crypto_worker_start enabled=true")

            async def send_signal(symbol: str, price: float, change: float, prev_price: float) -> None:
                logger.info(
                    "event=crypto_signal symbol=%s price=%s prev_price=%s change_pct=%.4f",
                    symbol,
                    price,
                    prev_price,
                    change,
                )

            crypto_task = asyncio.create_task(crypto_worker(send_signal, logger))

        if settings.enable_auto_digest:
            digest_task = asyncio.create_task(auto_digest_worker(bot, settings, logger))
        prewarm_task = asyncio.create_task(auto_prewarm_worker(settings, logger))
        reminder_task = asyncio.create_task(auto_todo_reminder_worker(bot, settings, logger))

    async def on_shutdown() -> None:
        nonlocal crypto_task, digest_task, prewarm_task, reminder_task
        logger.info("event=bot_shutdown")

        if crypto_task:
            crypto_task.cancel()
            try:
                await crypto_task
            except asyncio.CancelledError:
                logger.info("event=crypto_worker_stopped")

        if digest_task:
            digest_task.cancel()
            try:
                await digest_task
            except asyncio.CancelledError:
                logger.info("event=auto_digest_stopped")

        if prewarm_task:
            prewarm_task.cancel()
            try:
                await prewarm_task
            except asyncio.CancelledError:
                logger.info("event=prewarm_stopped")

        if reminder_task:
            reminder_task.cancel()
            try:
                await reminder_task
            except asyncio.CancelledError:
                logger.info("event=todo_reminder_stopped")

        await close_http_client()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Normal stop via Ctrl+C.
        pass

