import json
import unittest
from unittest.mock import patch

try:
    from app.api import (
        _GEMMA_HISTORY_MAX_ITEMS,
        _chat_history_append_exchange,
        _chat_history_load,
    )

    API_AVAILABLE = True
except Exception:  # noqa: BLE001
    API_AVAILABLE = False
    _GEMMA_HISTORY_MAX_ITEMS = 80
    _chat_history_append_exchange = None
    _chat_history_load = None


@unittest.skipUnless(API_AVAILABLE, "api module is not available in this environment")
class ApiChatHistoryContinuityTests(unittest.TestCase):
    def test_append_exchange_deduplicates_last_pair(self):
        store: dict[str, str] = {}

        def fake_get(key):
            val = store.get(str(key), "")
            return (val, "2026-03-05T10:00:00")

        def fake_set(key, value, _updated_at):
            store[str(key)] = str(value)

        with (
            patch("app.api.get_cache_value", side_effect=fake_get),
            patch("app.api.set_cache_value", side_effect=fake_set),
        ):
            _chat_history_append_exchange(1, user_text="привет", assistant_text="привет!")
            _chat_history_append_exchange(1, user_text="привет", assistant_text="привет!")
            items = _chat_history_load(1)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["role"], "user")
        self.assertEqual(items[1]["role"], "assistant")

    def test_history_is_trimmed_to_max_items(self):
        store: dict[str, str] = {}

        def fake_get(key):
            val = store.get(str(key), "")
            return (val, "2026-03-05T10:00:00")

        def fake_set(key, value, _updated_at):
            store[str(key)] = str(value)

        with (
            patch("app.api.get_cache_value", side_effect=fake_get),
            patch("app.api.set_cache_value", side_effect=fake_set),
        ):
            for idx in range(_GEMMA_HISTORY_MAX_ITEMS + 12):
                _chat_history_append_exchange(2, user_text=f"u{idx}", assistant_text=f"a{idx}")
            key = next(iter(store.keys()))
            payload = json.loads(store[key])

        self.assertEqual(len(payload), _GEMMA_HISTORY_MAX_ITEMS)
        start_exchange = (_GEMMA_HISTORY_MAX_ITEMS + 12) - (_GEMMA_HISTORY_MAX_ITEMS // 2)
        self.assertEqual(payload[0]["content"], f"u{start_exchange}")


if __name__ == "__main__":
    unittest.main()
