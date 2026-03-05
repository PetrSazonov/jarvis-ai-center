import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.settings import Settings
from handlers.commands import _subs_markup, _todo_markup, build_commands_router


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


def _find_handler(router, observer: str, callback_name: str):
    for h in router.observers[observer].handlers:
        if h.callback.__name__ == callback_name:
            return h.callback
    raise AssertionError(f"Handler not found: {callback_name}")


class TodoPanelMarkupTests(unittest.TestCase):
    def test_todo_markup_builds_for_ru_and_en(self):
        for lang in ("ru", "en"):
            markup = _todo_markup(lang)
            self.assertTrue(markup.inline_keyboard)
            callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
            self.assertIn("cmd:todo:list", callbacks)
            self.assertIn("cmd:todo:done_top", callbacks)
            self.assertIn("cmd:todo:del_top", callbacks)
            self.assertIn("cmd:todo:add_hint", callbacks)

    def test_subs_markup_builds_for_ru_and_en(self):
        for lang in ("ru", "en"):
            markup = _subs_markup(lang)
            self.assertTrue(markup.inline_keyboard)
            callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
            self.assertIn("cmd:subs:list", callbacks)
            self.assertIn("cmd:subs:check", callbacks)
            self.assertIn("cmd:subs:add_hint", callbacks)


class TodoCommandRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_todo_command_no_name_error(self):
        ctx = SimpleNamespace(settings=_settings(), bot=SimpleNamespace(), logger=SimpleNamespace(), known_commands=set())
        router = build_commands_router(ctx)
        callback = _find_handler(router, "message", "basic_text_cmds")

        message = SimpleNamespace(
            from_user=SimpleNamespace(id=118100880),
            text="/todo",
            reply=AsyncMock(),
        )

        with (
            patch("handlers.commands.user_settings_get_full", return_value={}),
            patch("handlers.commands.todo_list_open", return_value=[]),
        ):
            await callback(message)

        message.reply.assert_awaited_once()
        kwargs = message.reply.await_args.kwargs
        self.assertIn("reply_markup", kwargs)
        self.assertIsNotNone(kwargs["reply_markup"])

    async def test_subs_command_no_name_error(self):
        ctx = SimpleNamespace(settings=_settings(), bot=SimpleNamespace(), logger=SimpleNamespace(), known_commands=set())
        router = build_commands_router(ctx)
        callback = _find_handler(router, "message", "basic_text_cmds")

        message = SimpleNamespace(
            from_user=SimpleNamespace(id=118100880),
            text="/subs",
            reply=AsyncMock(),
        )

        with (
            patch("handlers.commands.user_settings_get_full", return_value={}),
            patch("handlers.commands.subs_list", return_value=[]),
        ):
            await callback(message)

        message.reply.assert_awaited_once()
        kwargs = message.reply.await_args.kwargs
        self.assertIn("reply_markup", kwargs)
        self.assertIsNotNone(kwargs["reply_markup"])

    async def test_subs_callback_list_runtime_smoke(self):
        ctx = SimpleNamespace(settings=_settings(), bot=SimpleNamespace(), logger=SimpleNamespace(), known_commands=set())
        router = build_commands_router(ctx)
        callback_handler = _find_handler(router, "callback_query", "subs_panel_callback")

        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=118100880),
            data="cmd:subs:list",
            message=SimpleNamespace(edit_text=AsyncMock(), reply=AsyncMock()),
            answer=AsyncMock(),
        )

        with (
            patch("handlers.commands.user_settings_get_full", return_value={}),
            patch("handlers.commands.subs_list", return_value=[]),
        ):
            await callback_handler(callback)

        callback.message.edit_text.assert_awaited_once()
        edit_kwargs = callback.message.edit_text.await_args.kwargs
        self.assertIn("reply_markup", edit_kwargs)
        self.assertIsNotNone(edit_kwargs["reply_markup"])
        callback.answer.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
