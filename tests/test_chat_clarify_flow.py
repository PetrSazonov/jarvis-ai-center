import unittest

from handlers.chat import (
    _compose_clarified_query,
    _is_contextual_clarification_reply,
    _looks_like_new_standalone_query,
    _should_answer_with_general_caveat,
)


class ChatClarifyFlowTests(unittest.TestCase):
    def test_contextual_short_reply_is_detected(self):
        self.assertTrue(_is_contextual_clarification_reply("в целом"))
        self.assertTrue(_is_contextual_clarification_reply("для меня"))
        self.assertTrue(_is_contextual_clarification_reply("скорее про людей"))

    def test_new_standalone_query_is_not_treated_as_clarification(self):
        self.assertTrue(_looks_like_new_standalone_query("расскажи анекдот"))
        self.assertTrue(_looks_like_new_standalone_query("сколько стоит бензин"))
        self.assertFalse(_is_contextual_clarification_reply("расскажи анекдот"))

    def test_merge_keeps_original_and_clarification(self):
        merged = _compose_clarified_query(
            original_query="Как мне стать лучше?",
            clarification_reply="в целом",
            lang="ru",
        )
        self.assertIn("Как мне стать лучше?", merged)
        self.assertIn("в целом", merged)
        self.assertIn("Уточнение пользователя", merged)

    def test_general_caveat_for_safe_non_fact_query(self):
        self.assertTrue(_should_answer_with_general_caveat("Как мне лучше организовать день без перегруза"))
        self.assertFalse(_should_answer_with_general_caveat("Какая сегодня погода в Москве"))
        self.assertFalse(_should_answer_with_general_caveat("Куда инвестировать деньги прямо сейчас"))


if __name__ == "__main__":
    unittest.main()
