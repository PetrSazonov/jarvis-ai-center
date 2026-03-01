import unittest
from datetime import datetime, timedelta
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.settings import Settings
from handlers.commands import (
    _cache_age_minutes,
    _fitness_latest_note,
    _fitness_latest_session_note,
    _fitness_status,
    _is_cache_fresh,
)


def _settings(*, vault_chat_id: int | None, admin_user_id: int | None) -> Settings:
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
        fitness_vault_chat_id=vault_chat_id,
        fitness_admin_user_id=admin_user_id,
        fitness_log_chat_id=None,
    )


class CommandsStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_fitness_status_missing_env(self):
        ctx = SimpleNamespace(
            settings=_settings(vault_chat_id=None, admin_user_id=None),
            bot=SimpleNamespace(get_chat=AsyncMock()),
        )
        with patch("handlers.commands.fitness_workouts_count", return_value=0):
            ok, note = await _fitness_status(ctx)
        self.assertTrue(ok)
        self.assertEqual(note, "ready")
        ctx.bot.get_chat.assert_not_called()

    async def test_fitness_status_text_only(self):
        ctx = SimpleNamespace(
            settings=_settings(vault_chat_id=None, admin_user_id=None),
            bot=SimpleNamespace(get_chat=AsyncMock()),
        )
        with patch("handlers.commands.fitness_workouts_count", return_value=5):
            ok, note = await _fitness_status(ctx)
        self.assertTrue(ok)
        self.assertEqual(note, "text-only")
        ctx.bot.get_chat.assert_not_called()

    async def test_fitness_status_ok(self):
        ctx = SimpleNamespace(
            settings=_settings(vault_chat_id=-10012345, admin_user_id=777),
            bot=SimpleNamespace(get_chat=AsyncMock(return_value=SimpleNamespace(id=-10012345))),
        )
        ok, note = await _fitness_status(ctx)
        self.assertTrue(ok)
        self.assertEqual(note, "ok")
        ctx.bot.get_chat.assert_awaited_once_with(-10012345)

    async def test_fitness_status_error(self):
        ctx = SimpleNamespace(
            settings=_settings(vault_chat_id=-10012345, admin_user_id=777),
            bot=SimpleNamespace(get_chat=AsyncMock(side_effect=RuntimeError("boom"))),
        )
        ok, note = await _fitness_status(ctx)
        self.assertFalse(ok)
        self.assertEqual(note, "RuntimeError")

    def test_fitness_latest_note_empty(self):
        with patch("handlers.commands.fitness_get_latest_workout", return_value=None):
            self.assertEqual(_fitness_latest_note(), "нет данных")

    def test_fitness_latest_note_with_row(self):
        row = (
            9,
            "Upper Body",
            "",
            "",
            2,
            900,
            "",
            -100,
            123,
            "file",
            "2026-02-23T09:30:00",
        )
        with patch("handlers.commands.fitness_get_latest_workout", return_value=row):
            self.assertEqual(_fitness_latest_note(), "#9 Upper Body (2026-02-23 09:30)")

    def test_fitness_latest_session_note_empty(self):
        with patch("handlers.commands.fitness_get_latest_session_for_user", return_value=None):
            self.assertEqual(_fitness_latest_session_note(118100880), "нет сессий")

    def test_fitness_latest_session_note_with_rpe(self):
        row = (4, "Leg Day", "2026-02-23T12:40:00", 8)
        with patch("handlers.commands.fitness_get_latest_session_for_user", return_value=row):
            self.assertEqual(_fitness_latest_session_note(118100880), "#4 Leg Day (2026-02-23 12:40, rpe=8)")

    def test_cache_age_minutes_parses_iso(self):
        ts = (datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds")
        age = _cache_age_minutes(ts)
        self.assertIsNotNone(age)
        self.assertGreaterEqual(age or 0, 1)

    def test_cache_fresh_true_for_recent(self):
        ts = (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds")
        self.assertTrue(_is_cache_fresh(ts))

    def test_cache_fresh_false_for_old(self):
        ts = (datetime.now() - timedelta(hours=4)).isoformat(timespec="seconds")
        self.assertFalse(_is_cache_fresh(ts))


if __name__ == "__main__":
    unittest.main()
