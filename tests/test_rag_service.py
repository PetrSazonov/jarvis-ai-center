import json
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from db import init_db, rag_upsert_vectors
from services.rag_service import (
    build_embedding,
    is_personal_data_query,
    resolve_rag_for_query,
    retrieve_matches,
)


class RagServiceSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        init_db()
        self.user_id = 910001

    def test_personal_query_detection(self):
        self.assertTrue(is_personal_data_query("что в моих документах по тренировкам"))
        self.assertTrue(is_personal_data_query("summarize my email about project"))
        self.assertFalse(is_personal_data_query("какая сегодня погода"))

    def test_retrieve_matches_prefers_relevant_doc(self):
        now_iso = datetime.now().isoformat(timespec="seconds")
        rows = [
            {
                "record_id": "doc-1",
                "title": "Workout note",
                "snippet": "Plan for squats and pull-ups this week",
                "ts": now_iso,
                "meta_json": json.dumps({"path": "notes/workout.txt"}, ensure_ascii=False),
                "embedding_json": json.dumps(build_embedding("squats pull-ups workout week"), ensure_ascii=False),
            },
            {
                "record_id": "doc-2",
                "title": "Finance note",
                "snippet": "Subscription renewals and fuel budget",
                "ts": now_iso,
                "meta_json": json.dumps({"path": "notes/finance.txt"}, ensure_ascii=False),
                "embedding_json": json.dumps(build_embedding("subscription finance fuel budget"), ensure_ascii=False),
            },
        ]
        rag_upsert_vectors(user_id=self.user_id, source="local_file", rows=rows, updated_at=now_iso)

        matches = retrieve_matches(
            user_id=self.user_id,
            query="что у меня по подтягиваниям и тренировкам",
            top_k=2,
            min_score=0.01,
        )
        self.assertGreaterEqual(len(matches), 1)
        self.assertEqual(matches[0].get("record_id"), "doc-1")


class RagServiceAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_personal_query_without_sources_returns_block(self):
        with (
            patch.dict(os.environ, {"RAG_ENABLED": "1", "RAG_REQUIRE_CITATIONS": "1"}, clear=False),
            patch("services.rag_service.refresh_rag_index", new=AsyncMock(return_value={"status": "ok"})),
            patch("services.rag_service.retrieve_matches", return_value=[]),
        ):
            payload = await resolve_rag_for_query(
                user_id=118100880,
                query="что в моей почте про проект",
                lang="ru",
            )

        self.assertTrue(payload.get("personal"))
        self.assertTrue(payload.get("required"))
        self.assertTrue(str(payload.get("block_message") or "").strip())

    async def test_non_personal_query_does_not_require_sources(self):
        with patch.dict(os.environ, {"RAG_ENABLED": "1", "RAG_REQUIRE_CITATIONS": "1"}, clear=False):
            payload = await resolve_rag_for_query(
                user_id=118100880,
                query="какая сегодня погода",
                lang="ru",
            )
        self.assertFalse(payload.get("personal"))
        self.assertFalse(payload.get("required"))
        self.assertEqual(payload.get("block_message"), None)


if __name__ == "__main__":
    unittest.main()
