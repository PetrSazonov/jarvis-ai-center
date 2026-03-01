import unittest

from services.time_service import is_date_or_time_question


class TimeServiceTests(unittest.TestCase):
    def test_detects_russian_date_question(self):
        self.assertTrue(is_date_or_time_question("какое сегодня число?"))

    def test_detects_english_time_question(self):
        self.assertTrue(is_date_or_time_question("what time is it now"))

    def test_ignores_regular_question(self):
        self.assertFalse(is_date_or_time_question("расскажи анекдот"))


if __name__ == "__main__":
    unittest.main()
