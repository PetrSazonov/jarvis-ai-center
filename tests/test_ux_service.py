import unittest

from services.ux_service import (
    WeekPlaybackMetrics,
    adaptive_menu_rows,
    build_digest_story_screens,
    build_week_playback_screens,
    daypart_by_hour,
)


class UXServiceTests(unittest.TestCase):
    def test_daypart_by_hour(self):
        self.assertEqual(daypart_by_hour(7), "morning")
        self.assertEqual(daypart_by_hour(14), "day")
        self.assertEqual(daypart_by_hour(21), "evening")
        self.assertEqual(daypart_by_hour(2), "night")

    def test_adaptive_menu_rows_shape(self):
        morning = adaptive_menu_rows(8)
        day = adaptive_menu_rows(15)
        evening = adaptive_menu_rows(21)
        self.assertEqual(morning[0], ["/today", "/startnow", "/price"])
        self.assertEqual(day[0], ["/today", "/focus", "/todo"])
        self.assertEqual(evening[0], ["/today", "/checkin", "/digest"])
        self.assertEqual(morning[2], ["/fit", "/arena", "/week"])
        self.assertEqual(evening[1], ["/weekly", "/recap", "/todo"])

    def test_build_digest_story_screens(self):
        text = "\n".join(
            [
                "🪐 Сегодня твой 15000-й день на этой планете.",
                "🏁 До мотосезона осталось 50 дней.",
                "",
                "💹 Рынок:",
                "Bitcoin: USD 68000.00 | 24ч 🟢 +1.2%",
                "",
                "🏋️ Тренировка дня: База",
                "",
                "☁️ Погода в Москве: -2C, пасмурно",
                "",
                "🗞️ Новости:",
                "🧠 <a href=\"https://example.com\">Новая ИИ-модель</a>",
                "",
                "Рекомендация: закрой 1 приоритет до обеда.",
                "Факт дня: свет от Солнца идет 8 минут 20 секунд.",
            ]
        )
        screens = build_digest_story_screens(text)
        self.assertGreaterEqual(len(screens), 3)
        self.assertTrue(any("💹 Рынок" in item for item in screens))
        self.assertTrue(any("🗞️ Новости" in item for item in screens))

    def test_build_digest_story_screens_deduplicates_first_screen(self):
        text = "\n".join(
            [
                "🪐 Доброе утро. Сегодня твой 15052-й день на этой планете.",
                "🏁 До мотосезона 2026 осталось 45 дней.",
                "💹 Рынок:",
                "Bitcoin: USD 68000.00 | 24ч 🟢 +1.2%",
                "Рекомендация: закрой 1 приоритет до обеда.",
                "🪐 Доброе утро. Сегодня твой 15052-й день на этой планете.",
                "🏁 До мотосезона 2026 осталось 45 дней.",
            ]
        )
        screens = build_digest_story_screens(text)
        self.assertGreaterEqual(len(screens), 1)
        first = screens[0]
        self.assertEqual(first.count("🪐 Доброе утро. Сегодня твой 15052-й день на этой планете."), 1)
        self.assertEqual(first.count("🏁 До мотосезона 2026 осталось 45 дней."), 1)

    def test_build_week_playback_screens(self):
        metrics = WeekPlaybackMetrics(
            done_tasks=7,
            open_tasks=3,
            fitness_done=4,
            streak_days=3,
            avg_energy=6.5,
            best_day="2026-03-01",
            leaks=["шум в чатах"],
            next_focus=["Закрыть отчет", "Тренировка", "Разобрать инбокс"],
        )
        screens = build_week_playback_screens(metrics)
        self.assertEqual(len(screens), 5)
        self.assertIn("Сделано задач: 7", screens[0])
        self.assertIn("Энергия (средняя): 6.5/10", screens[1])


if __name__ == "__main__":
    unittest.main()
