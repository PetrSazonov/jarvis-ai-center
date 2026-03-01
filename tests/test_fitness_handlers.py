import unittest
from datetime import date

from handlers.fitness import (
    _next_hint_by_context,
    _next_hint_by_rpe,
    _parse_duration_to_seconds,
    _parse_fit_edit,
    _program_summary,
    _program_week,
    _render_plain_workout_plan,
    _weekday_plan_slot,
)


class FitnessHandlerTests(unittest.TestCase):
    def test_parse_duration_seconds(self):
        self.assertEqual(_parse_duration_to_seconds("22m"), 1320)
        self.assertEqual(_parse_duration_to_seconds("22min"), 1320)
        self.assertEqual(_parse_duration_to_seconds("1320"), 1320)

    def test_parse_fit_edit(self):
        workout_id, updates = _parse_fit_edit(
            "/fit edit 5 title=Ноги дома tags=legs,home equipment=bands difficulty=3 duration=22m notes=без прыжков"
        )
        self.assertEqual(workout_id, 5)
        self.assertEqual(updates["title"], "Ноги дома")
        self.assertEqual(updates["tags"], "legs,home")
        self.assertEqual(updates["equipment"], "bands")
        self.assertEqual(updates["difficulty"], 3)
        self.assertEqual(updates["duration_sec"], 1320)
        self.assertEqual(updates["notes"], "без прыжков")

    def test_program_week_rollover(self):
        self.assertEqual(_program_week(date(2026, 1, 5)), 1)
        self.assertEqual(_program_week(date(2026, 1, 12)), 2)
        self.assertEqual(_program_week(date(2026, 1, 19)), 3)
        self.assertEqual(_program_week(date(2026, 1, 26)), 4)
        self.assertEqual(_program_week(date(2026, 2, 2)), 1)

    def test_weekday_plan_slot(self):
        self.assertEqual(_weekday_plan_slot(date(2026, 2, 23))[1], "pull")
        self.assertEqual(_weekday_plan_slot(date(2026, 2, 25))[1], "legs")
        self.assertEqual(_weekday_plan_slot(date(2026, 2, 27))[1], "burpee")
        self.assertEqual(_weekday_plan_slot(date(2026, 2, 22))[1], "recovery")

    def test_program_summary_has_focus_tag(self):
        text = _program_summary(date(2026, 2, 27))
        self.assertIn("неделя", text)
        self.assertIn("#burpee", text)
        self.assertIn("Неделя 4", text)

    def test_next_hint_by_rpe(self):
        self.assertIn("легко", _next_hint_by_rpe(5))
        self.assertIn("рабочая", _next_hint_by_rpe(7))
        self.assertIn("пределу", _next_hint_by_rpe(9))
        self.assertIn("технику", _next_hint_by_rpe(None))

    def test_next_hint_by_context_trend(self):
        self.assertIn("снизь объем", _next_hint_by_context(8, [9, 8, 8]))
        self.assertIn("добавь подход", _next_hint_by_context(6, [6, 5, 6]))
        self.assertIn("рабочая", _next_hint_by_context(7, [7, None]))

    def test_plain_plan_render(self):
        plan = _render_plain_workout_plan(
            {
                "title": "База",
                "duration_sec": 1800,
                "difficulty": 3,
                "equipment": "турник",
                "notes": "5 кругов: подтягивания и отжимания",
            }
        )
        self.assertIn("План", plan)
        self.assertIn("Разминка", plan)
        self.assertIn("Основной блок", plan)


if __name__ == "__main__":
    unittest.main()
