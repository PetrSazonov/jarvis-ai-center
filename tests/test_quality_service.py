import unittest

from services.quality_service import detect_ood_topic, sanitize_history, score_response


class QualityServiceTests(unittest.TestCase):
    def test_sanitize_history_removes_service_noise(self):
        history = [
            {"role": "assistant", "content": "Сервис LLM временно недоступен. Пока доступны /price"},
            {"role": "user", "content": "Привет"},
            {"role": "assistant", "content": "Привет, чем помочь?"},
        ]
        out = sanitize_history(history, max_items=10)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["content"], "Привет")

    def test_detect_ood_topic(self):
        self.assertEqual(detect_ood_topic("Подскажи дозировку лекарства"), "medical")
        self.assertEqual(detect_ood_topic("Нужен шаблон иска в суд"), "legal")
        self.assertEqual(detect_ood_topic("Куда вложить деньги завтра"), "financial")
        self.assertIsNone(detect_ood_topic("Расскажи анекдот"))

    def test_score_response(self):
        good = score_response("Давай начнем с плана: цель, ограничения, шаги.", "ru")
        bad = score_response("I do not have a response yet.", "ru")
        self.assertGreater(good.score, 0.6)
        self.assertLess(bad.score, 0.5)


if __name__ == "__main__":
    unittest.main()
