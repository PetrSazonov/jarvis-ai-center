import asyncio
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.api import (
        CopilotActionRequest,
        CopilotMessageRequest,
        _AI_ACTION_TIMEOUT_TEXT,
        _AI_MESSAGE_EMPTY_TEXT,
        _assistant_action,
        _assistant_message,
    )

    API_AVAILABLE = True
except Exception:  # noqa: BLE001
    API_AVAILABLE = False


@unittest.skipUnless(API_AVAILABLE, "app.api is not available in this environment")
class APIChatReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_message_timeout_returns_unified_fallback(self):
        payload = CopilotMessageRequest(user_id=1, message="привет", mode="normal", chat_mode="full")
        with patch("app.api._gemma_full_reply", new=AsyncMock(side_effect=asyncio.TimeoutError())):
            result = await _assistant_message(payload)

        self.assertEqual(result.get("status"), "fallback")
        self.assertEqual(result.get("error_kind"), "timeout")
        self.assertTrue(str(result.get("answer") or "").strip())
        self.assertTrue(isinstance(result.get("quick_actions"), list))
        self.assertGreater(len(result.get("quick_actions") or []), 0)

    async def test_message_empty_llm_answer_is_normalized(self):
        payload = CopilotMessageRequest(user_id=1, message="что делать", mode="normal", chat_mode="full")
        with patch("app.api._gemma_full_reply", new=AsyncMock(return_value={"answer": "", "quick_actions": []})):
            result = await _assistant_message(payload)

        self.assertEqual(result.get("status"), "ok")
        self.assertEqual(str(result.get("answer") or ""), _AI_MESSAGE_EMPTY_TEXT)
        self.assertTrue(isinstance(result.get("quick_actions"), list))
        self.assertGreater(len(result.get("quick_actions") or []), 0)

    async def test_action_replan_timeout_returns_clear_status(self):
        payload = CopilotActionRequest(user_id=1, action="replan_day", mode="normal")
        with patch("app.api._copilot_reply", new=AsyncMock(side_effect=asyncio.TimeoutError())):
            result = await _assistant_action(payload)

        self.assertFalse(bool(result.get("ok")))
        self.assertEqual(result.get("status"), "fallback")
        self.assertEqual(result.get("error_kind"), "timeout")
        self.assertEqual(str(result.get("message") or ""), _AI_ACTION_TIMEOUT_TEXT)
        self.assertTrue(isinstance(result.get("quick_actions"), list))
        self.assertGreater(len(result.get("quick_actions") or []), 0)

    async def test_action_unknown_returns_validation_error(self):
        payload = CopilotActionRequest(user_id=1, action="unsupported_action", mode="normal")
        result = await _assistant_action(payload)

        self.assertFalse(bool(result.get("ok")))
        self.assertEqual(result.get("status"), "validation_error")
        self.assertEqual(result.get("error_kind"), "unknown_action")
        self.assertIn("task_add", str(result.get("message") or ""))

    async def test_gemma_full_reply_blocks_personal_query_without_sources(self):
        payload = CopilotMessageRequest(user_id=1, message="что в моей почте по проекту", mode="normal", chat_mode="full")
        with (
            patch("app.api._settings", return_value=object()),
            patch("app.api._handle", side_effect=[{"day_mode": "workday", "energy": 6}, {"items": []}]),
            patch("app.api._trend_panel", return_value={"summary": "stable"}),
            patch(
                "app.api.resolve_rag_for_query",
                new=AsyncMock(
                    return_value={
                        "personal": True,
                        "required": True,
                        "context": "",
                        "citations_block": "",
                        "block_message": "Не могу отвечать без источников.",
                    }
                ),
            ),
            patch("app.api.call_ollama", new=AsyncMock(return_value="should_not_run")) as call_mock,
        ):
            result = await _assistant_message(payload)

        self.assertEqual(result.get("status"), "ok")
        self.assertIn("без источников", str(result.get("answer") or ""))
        call_mock.assert_not_called()

    async def test_gemma_full_reply_appends_citations(self):
        payload = CopilotMessageRequest(user_id=1, message="что у меня в заметках по тренировкам", mode="normal", chat_mode="full")
        with (
            patch("app.api._settings", return_value=object()),
            patch("app.api._handle", side_effect=[{"day_mode": "workday", "energy": 6}, {"items": []}]),
            patch("app.api._trend_panel", return_value={"summary": "stable"}),
            patch("app.api._chat_history_load", return_value=[]),
            patch("app.api._chat_history_save"),
            patch("app.api.build_prompt", return_value="prompt"),
            patch("app.api.call_ollama", new=AsyncMock(return_value="Сводка по заметкам")),
            patch(
                "app.api.resolve_rag_for_query",
                new=AsyncMock(
                    return_value={
                        "personal": True,
                        "required": True,
                        "context": "Личные источники [1] ...",
                        "citations_block": "Источники:\n[1] note (local_file:file:note.txt, 2026-03-04T10:00:00)",
                        "block_message": None,
                    }
                ),
            ),
        ):
            result = await _assistant_message(payload)

        self.assertEqual(result.get("status"), "ok")
        answer = str(result.get("answer") or "")
        self.assertIn("Сводка по заметкам", answer)
        self.assertIn("Источники:", answer)
        self.assertIn("[1]", answer)


if __name__ == "__main__":
    unittest.main()
