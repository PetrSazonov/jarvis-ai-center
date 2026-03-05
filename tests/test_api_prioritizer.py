import unittest
from datetime import date, timedelta

try:
    from app.api import _daily_priority_action_text, _daily_priority_items

    API_AVAILABLE = True
except Exception:  # noqa: BLE001
    API_AVAILABLE = False
    _daily_priority_items = None
    _daily_priority_action_text = None


@unittest.skipUnless(API_AVAILABLE, "api module is not available in this environment")
class ApiPrioritizerTests(unittest.TestCase):
    def test_daily_priority_prefers_dated_tasks(self):
        today = date.today().isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        tasks = [
            {"id": 3, "text": "Без даты", "created_at": "2026-03-05T08:00:00", "due_date": ""},
            {"id": 1, "text": "Срок сегодня", "created_at": "2026-03-05T07:00:00", "due_date": today},
            {"id": 2, "text": "Срок завтра", "created_at": "2026-03-05T09:00:00", "due_date": tomorrow},
        ]
        ranked = _daily_priority_items(tasks, limit=3)
        self.assertEqual(len(ranked), 3)
        self.assertEqual(str(ranked[0].get("text")), "Срок сегодня")
        self.assertEqual(str(ranked[1].get("text")), "Срок завтра")

    def test_daily_priority_action_text_builds_top3(self):
        ranked = [
            {"id": 1, "text": "Разобрать почту"},
            {"id": 2, "text": "Подготовить план недели"},
            {"id": 3, "text": "Проверить рынок"},
        ]
        action = _daily_priority_action_text(ranked, fallback="fallback")
        self.assertIn("Top-3 на сегодня", action)
        self.assertIn("Разобрать почту", action)
        self.assertIn("Старт:", action)
        self.assertIn("Микро-шаг", action)


if __name__ == "__main__":
    unittest.main()
