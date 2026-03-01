import unittest

from services.text_clean_service import normalize_display_text


class TextCleanServiceTests(unittest.TestCase):
    def test_keeps_clean_russian_text(self):
        text = "Биткоин: USD 67885.00 | 24ч 🟢 +0.4%"
        self.assertEqual(normalize_display_text(text), text)

    def test_repairs_cp1251_mojibake(self):
        source = "Биткоин: USD 67885.00 | 24ч 🟢 +0.4%"
        bad = source.encode("utf-8").decode("cp1251")
        self.assertEqual(normalize_display_text(bad), source)

    def test_keeps_english_text(self):
        text = "Bitcoin: USD 67885.00 | 24h +0.4%"
        self.assertEqual(normalize_display_text(text), text)


if __name__ == "__main__":
    unittest.main()
