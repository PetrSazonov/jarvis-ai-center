import unittest

from services.news_service import _match_topic, _parse_published_ts, _sort_items


class NewsServiceTests(unittest.TestCase):
    def test_parse_published_ts_rfc2822(self):
        ts = _parse_published_ts("Sat, 28 Feb 2026 10:15:00 +0300")
        self.assertGreater(ts, 0.0)

    def test_sort_items_prefers_fresher_news(self):
        older_but_relevant = {
            "title": "OpenAI выпустила новую модель",
            "url": "https://example.com/old",
            "published_ts": "1700000000",
        }
        newer_generic = {
            "title": "Обновление продукта",
            "url": "https://example.com/new",
            "published_ts": "1800000000",
        }
        items = _sort_items([older_but_relevant, newer_generic])
        self.assertEqual(items[0]["url"], "https://example.com/new")

    def test_match_topic_dota2(self):
        self.assertTrue(_match_topic("Dota 2: Team Spirit выиграла матч", "дота2"))

    def test_match_topic_motogp(self):
        self.assertTrue(_match_topic("MotoGP sprint race results", "motogp"))


if __name__ == "__main__":
    unittest.main()
