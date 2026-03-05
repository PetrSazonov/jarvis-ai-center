import re
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.settings import Settings
from handlers.commands import build_commands_router
from handlers.growth import build_growth_router
from handlers.ux_router import build_ux_router
from services.messages import t


CORE_FIRST_LAYER = [
    "start",
    "menu",
    "today",
    "todo",
    "focus",
    "checkin",
    "week",
    "review",
    "decide",
]


def _settings() -> Settings:
    return Settings(
        bot_token="x",
        coingecko_vs="usd",
        price_currencies=("usd", "eur", "rub"),
        ollama_api_url="http://localhost",
        ollama_model="test",
        ollama_timeout_seconds=60.0,
        max_history_messages=24,
        system_prompt="system",
        default_lang="ru",
        enable_crypto_watcher=False,
        log_level="INFO",
        timezone_name=None,
        weather_city="Moscow",
        home_address=None,
        work_address=None,
        enable_auto_digest=True,
        digest_times=("07:00", "14:00", "21:00"),
        digest_chat_id=1,
        birth_date=date(1984, 12, 15),
        moto_season_start_mmdd=(4, 15),
        fuel95_source_url="https://example.com/fuel95",
        fuel95_moscow_rub=62.5,
        feedback_min_chars=280,
        style_mode="neutral",
    )


def _handler_names(router, observer: str) -> set[str]:
    return {h.callback.__name__ for h in router.observers[observer].handlers}


def _find_handler(router, observer: str, callback_name: str):
    for h in router.observers[observer].handlers:
        if h.callback.__name__ == callback_name:
            return h.callback
    raise AssertionError(f"Handler not found: {callback_name}")


class DayOSSmokeSyncTests(unittest.TestCase):
    def test_first_layer_bot_commands_core_only(self):
        source = Path("bot.py").read_text(encoding="utf-8")
        matches = re.findall(r'BotCommand\(command="([a-z0-9_]+)"', source)
        # Check only set_my_commands payload.
        start = matches.index("start")
        first_layer = matches[start : start + len(CORE_FIRST_LAYER)]
        self.assertEqual(first_layer, CORE_FIRST_LAYER)
        self.assertEqual(len(first_layer), len(CORE_FIRST_LAYER))

    def test_start_message_is_core_oriented(self):
        msg = t("ru", "start_welcome")
        self.assertIn("/today", msg)
        self.assertIn("/menu", msg)
        self.assertNotIn("/fit", msg)
        self.assertNotIn("/subs", msg)

    def test_help_mentions_weekly_canonical_path(self):
        msg = t("ru", "help")
        self.assertIn("/week", msg)
        self.assertIn("/review week", msg)
        self.assertIn("/weekly", msg)

    def test_core_handlers_are_registered(self):
        ctx = SimpleNamespace(settings=_settings(), bot=SimpleNamespace(), logger=SimpleNamespace(), known_commands=set())
        commands_router = build_commands_router(ctx)
        ux_router = build_ux_router(ctx)
        growth_router = build_growth_router(ctx)

        commands_handlers = _handler_names(commands_router, "message")
        ux_handlers = _handler_names(ux_router, "message")
        growth_handlers = _handler_names(growth_router, "message")

        self.assertIn("start_cmd", commands_handlers)
        self.assertIn("menu_cmd", commands_handlers)
        self.assertIn("basic_text_cmds", commands_handlers)  # /todo, /checkin etc.
        self.assertIn("today_command", ux_handlers)
        self.assertIn("focus_command", ux_handlers)
        self.assertIn("week_command", ux_handlers)
        self.assertIn("review_command", growth_handlers)

    def test_secondary_price_handler_still_registered(self):
        ctx = SimpleNamespace(settings=_settings(), bot=SimpleNamespace(), logger=SimpleNamespace(), known_commands=set())
        commands_router = build_commands_router(ctx)
        commands_handlers = _handler_names(commands_router, "message")
        self.assertIn("price_cmd", commands_handlers)


class DayOSSmokeAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_weekly_alias_soft_redirect(self):
        ctx = SimpleNamespace(settings=_settings(), bot=SimpleNamespace(), logger=SimpleNamespace(), known_commands=set())
        router = build_commands_router(ctx)
        callback = _find_handler(router, "message", "weekly_alias_cmd")

        message = SimpleNamespace(
            from_user=SimpleNamespace(id=118100880),
            text="/weekly",
            reply=AsyncMock(),
        )
        with patch("handlers.commands.user_settings_get_full", return_value={}):
            await callback(message)

        message.reply.assert_awaited_once()
        text = message.reply.await_args.args[0]
        self.assertIn("/week", text)
        self.assertIn("/review week", text)

    async def test_review_default_and_week_arg(self):
        ctx = SimpleNamespace(settings=_settings(), bot=SimpleNamespace(), logger=SimpleNamespace(), known_commands=set())
        router = build_growth_router(ctx)
        callback = _find_handler(router, "message", "review_command")

        msg_default = SimpleNamespace(
            from_user=SimpleNamespace(id=118100880),
            text="/review",
            reply=AsyncMock(),
        )
        msg_week = SimpleNamespace(
            from_user=SimpleNamespace(id=118100880),
            text="/review week",
            reply=AsyncMock(),
        )

        with (
            patch("handlers.growth.user_settings_get_full", return_value={}),
            patch("handlers.growth.build_review_text", return_value="ok") as build_review,
        ):
            await callback(msg_default)
            await callback(msg_week)

        self.assertEqual(build_review.call_count, 2)
        self.assertEqual(build_review.call_args_list[0].kwargs["horizon"], "week")
        self.assertEqual(build_review.call_args_list[1].kwargs["horizon"], "week")


if __name__ == "__main__":
    unittest.main()
