import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from services.ingest_service import collect_ingest_signals


class IngestServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_root = Path("ops/ingest_test_data").resolve()
        if self.test_root.exists():
            shutil.rmtree(self.test_root, ignore_errors=True)
        self.test_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.test_root, ignore_errors=True)

    def test_local_files_ingest_returns_unified_records(self):
        file_path = self.test_root / "daily_note.txt"
        file_path.write_text("Daily plan\nMIT 1\nMIT 2\n", encoding="utf-8")

        with patch.dict(
            os.environ,
            {
                "INGEST_IMAP_ENABLED": "0",
                "INGEST_LOCAL_ENABLED": "1",
                "INGEST_LOCAL_PATHS": str(self.test_root),
                "INGEST_LOCAL_GLOBS": "*.txt",
                "INGEST_LOCAL_MAX_FILES": "10",
            },
            clear=False,
        ):
            payload = collect_ingest_signals(limit=10)

        self.assertTrue(payload.get("enabled"))
        self.assertEqual(payload.get("status"), "ok")
        self.assertGreaterEqual(int(payload.get("count") or 0), 1)

        items = payload.get("items")
        self.assertIsInstance(items, list)
        self.assertGreaterEqual(len(items), 1)

        item = items[0]
        self.assertEqual(item.get("source"), "local_file")
        self.assertEqual(item.get("kind"), "document")
        self.assertTrue(str(item.get("id") or "").startswith("file:"))
        self.assertTrue(str(item.get("title") or "").strip())
        self.assertTrue(str(item.get("snippet") or "").strip())
        self.assertTrue(str(item.get("ts") or "").strip())
        self.assertIsInstance(item.get("tags"), list)
        self.assertIsInstance(item.get("meta"), dict)

    def test_ingest_off_when_sources_disabled(self):
        with patch.dict(
            os.environ,
            {
                "INGEST_IMAP_ENABLED": "0",
                "INGEST_LOCAL_ENABLED": "0",
                "INGEST_LOCAL_PATHS": "",
            },
            clear=False,
        ):
            payload = collect_ingest_signals(limit=5)

        self.assertEqual(payload.get("enabled"), False)
        self.assertEqual(payload.get("status"), "off")
        self.assertEqual(payload.get("count"), 0)
        self.assertEqual(payload.get("items"), [])


if __name__ == "__main__":
    unittest.main()
