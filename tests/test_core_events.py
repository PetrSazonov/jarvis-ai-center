import unittest
from unittest.mock import patch

from core.coordinator import handle_command


class CoordinatorEventsTests(unittest.TestCase):
    def test_tasks_add_returns_event_when_enabled(self):
        with patch("core.coordinator.tasks.add_task", return_value=7):
            result = handle_command(
                118100880,
                "tasks:add",
                {"text": "MIT", "created_at": "2026-03-03T10:00:00"},
                return_events=True,
            )
        self.assertIn("result", result)
        self.assertIn("events", result)
        self.assertEqual(result["result"], {"id": 7})
        self.assertEqual(result["events"][0]["name"], "tasks.added")
        self.assertEqual(result["events"][0]["payload"]["task_id"], 7)

    def test_tasks_done_returns_completed_event(self):
        with patch("core.coordinator.tasks.mark_task_done", return_value=True):
            result = handle_command(
                1,
                "tasks:done",
                {"task_id": 42, "done_at": "2026-03-03T10:01:00"},
                return_events=True,
            )
        self.assertEqual(result["result"], {"ok": True})
        names = [event["name"] for event in result["events"]]
        self.assertIn("tasks.completed", names)

    def test_subs_roll_returns_rolled_event(self):
        with patch("core.coordinator.subs.roll_subscription_date", return_value="2026-04-01"):
            result = handle_command(
                1,
                "subs:roll",
                {"sub_id": 9, "steps": 1, "updated_at": "2026-03-03T10:02:00"},
                return_events=True,
            )
        self.assertEqual(result["result"], {"ok": True, "new_date": "2026-04-01"})
        names = [event["name"] for event in result["events"]]
        self.assertIn("subs.rolled", names)

    def test_backward_compatibility_default_return(self):
        with patch("core.coordinator.tasks.add_task", return_value=55):
            result = handle_command(2, "tasks:add", {"text": "x"})
        self.assertEqual(result, {"id": 55})


if __name__ == "__main__":
    unittest.main()

