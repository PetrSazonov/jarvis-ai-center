import unittest

from db import _normalize_history


class DBNormalizeTests(unittest.TestCase):
    def test_normalize_dict_items(self):
        raw = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
        normalized = _normalize_history(raw)
        self.assertEqual(normalized[0]["role"], "user")
        self.assertEqual(normalized[1]["role"], "assistant")

    def test_normalize_legacy_strings(self):
        raw = ["User: hello", "AI: world", "other"]
        normalized = _normalize_history(raw)
        self.assertEqual(normalized[0], {"role": "user", "content": "hello"})
        self.assertEqual(normalized[1], {"role": "assistant", "content": "world"})
        self.assertEqual(normalized[2], {"role": "user", "content": "other"})


if __name__ == "__main__":
    unittest.main()
