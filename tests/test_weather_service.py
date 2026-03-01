import unittest

from services.weather_service import clean_weather_summary


class WeatherServiceSanitizerTests(unittest.TestCase):
    def test_removes_broken_cache_suffix(self):
        text = (
            "Погода в Москве: 1.3C, ощущается как -1.0C, пасмурно\n"
            "Тренд на 5 дней: в среднем холоднее примерно на 2.2C, чем сегодня. (кэш 1Р’В РІР‚в„ў Р В)"
        )
        cleaned = clean_weather_summary(text)
        self.assertNotIn("(кэш", cleaned.lower())
        self.assertIn("Тренд на 5 дней", cleaned)

    def test_keeps_normal_cache_suffix(self):
        text = "Тренд на 5 дней: в среднем холоднее примерно на 2.2C, чем сегодня. (кэш 3м)"
        cleaned = clean_weather_summary(text)
        self.assertEqual(cleaned, text)

    def test_removes_only_mojibake_tail(self):
        text = (
            "Осадков в ближайшие 24 часа не ожидается.\n"
            "Тренд на 5 дней: температура будет близкой к сегодняшней. (кэш 2Р’В РІР‚в„ў)"
        )
        cleaned = clean_weather_summary(text)
        self.assertIn("Осадков в ближайшие 24 часа не ожидается.", cleaned)
        self.assertTrue(cleaned.endswith("Тренд на 5 дней: температура будет близкой к сегодняшней."))


if __name__ == "__main__":
    unittest.main()
