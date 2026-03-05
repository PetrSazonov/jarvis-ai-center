import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

import db
from services.growth_service import (
    build_plan_text,
    build_review_text,
    build_score_text,
    calculate_growth_scores,
)


class GrowthServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_name = db.DATABASE_NAME
        fd, path = tempfile.mkstemp(prefix="growth_", suffix=".db")
        os.close(fd)
        self._tmp_path = path
        db.DATABASE_NAME = self._tmp_path
        db.init_db()
        self.user_id = 909
        self.today = date(2026, 3, 1)
        self.now = datetime(2026, 3, 1, 9, 0, 0)

        workout_id = db.fitness_create_workout(
            title="Test workout",
            tags="pull",
            equipment="none",
            difficulty=2,
            duration_sec=1200,
            notes="",
            vault_chat_id=1,
            vault_message_id=1001,
            file_id="",
            created_at=self.now.isoformat(timespec="seconds"),
        )
        self.workout_id = int(workout_id)

    def tearDown(self) -> None:
        db.DATABASE_NAME = self._orig_db_name
        try:
            os.remove(self._tmp_path)
        except OSError:
            pass

    def _add_done_task(self, when: datetime, text: str) -> None:
        todo_id = db.todo_add(
            user_id=self.user_id,
            text=text,
            created_at=when.isoformat(timespec="seconds"),
        )
        db.todo_mark_done(
            user_id=self.user_id,
            todo_id=int(todo_id),
            done_at=when.isoformat(timespec="seconds"),
        )

    def _add_focus_done(self, when: datetime, minutes: int) -> None:
        focus_id = db.focus_session_start(
            user_id=self.user_id,
            duration_min=minutes,
            started_at=when.isoformat(timespec="seconds"),
        )
        db.focus_session_finish(
            user_id=self.user_id,
            focus_id=focus_id,
            finished_at=(when + timedelta(minutes=minutes)).isoformat(timespec="seconds"),
            status="done",
        )

    def _add_checkin(self, day: date, energy: int) -> None:
        stamp = datetime.combine(day, datetime.min.time()).replace(hour=21)
        db.daily_checkin_upsert(
            user_id=self.user_id,
            check_date=day.isoformat(),
            done_text="done",
            carry_text="carry",
            energy=energy,
            created_at=stamp.isoformat(timespec="seconds"),
            updated_at=stamp.isoformat(timespec="seconds"),
        )

    def _add_reflection(self, day: date) -> None:
        stamp = datetime.combine(day, datetime.min.time()).replace(hour=22)
        db.reflection_upsert(
            user_id=self.user_id,
            reflection_date=day.isoformat(),
            done_text="done",
            drain_text="drain",
            remove_text="remove",
            tomorrow_rule="rule",
            created_at=stamp.isoformat(timespec="seconds"),
            updated_at=stamp.isoformat(timespec="seconds"),
        )

    def test_calculate_scores_and_weighted_index(self):
        self._add_done_task(self.now - timedelta(days=1), "task-1")
        self._add_done_task(self.now, "task-2")
        db.todo_add(user_id=self.user_id, text="open-task", created_at=self.now.isoformat(timespec="seconds"))
        self._add_focus_done(self.now, 45)
        self._add_focus_done(self.now - timedelta(days=2), 30)
        db.fitness_add_session(
            user_id=self.user_id,
            workout_id=self.workout_id,
            done_at=self.now.isoformat(timespec="seconds"),
            rpe=7,
            comment="ok",
        )
        for shift, energy in [(0, 7), (1, 6), (2, 8), (3, 7)]:
            self._add_checkin(self.today - timedelta(days=shift), energy)
        self._add_reflection(self.today)
        self._add_reflection(self.today - timedelta(days=2))

        scores = calculate_growth_scores(user_id=self.user_id, today=self.today)
        expected_index = round(
            scores.execution * 0.30
            + scores.focus * 0.25
            + scores.recovery * 0.20
            + scores.consistency * 0.15
            + scores.growth * 0.10
        )
        self.assertEqual(scores.index, expected_index)
        self.assertGreaterEqual(scores.execution, 1)
        self.assertGreaterEqual(scores.focus_minutes_7d, 75)
        self.assertEqual(scores.reflections_7d, 2)
        self.assertEqual(scores.checkin_days_7d, 4)

    def test_renderers_have_expected_sections(self):
        text_score = build_score_text(user_id=self.user_id, lang="ru", today=self.today)
        text_plan = build_plan_text(user_id=self.user_id, horizon="day", lang="ru", today=self.today)
        text_review = build_review_text(user_id=self.user_id, horizon="week", lang="ru", today=self.today)

        self.assertIn("Score Engine", text_score)
        self.assertIn("Growth Index", text_score)
        self.assertIn("План на день", text_plan)
        self.assertIn("MIT:", text_plan)
        self.assertIn("Review: неделя", text_review)
        self.assertIn("/today", text_review)


if __name__ == "__main__":
    unittest.main()
