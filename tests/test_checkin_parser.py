import unittest

from handlers.commands import _parse_checkin_payload


class CheckinParserTests(unittest.TestCase):
    def test_parses_expected_format(self):
        parsed = _parse_checkin_payload(
            "done=закрыл 3 задачи; carry=перенести звонок; energy=8"
        )
        self.assertEqual(parsed, ("закрыл 3 задачи", "перенести звонок", 8))

    def test_parses_show_like_lines_with_newlines(self):
        parsed = _parse_checkin_payload(
            "done=закрыл 1 задачу\ncarry=доделать отчет\nenergy=6"
        )
        self.assertEqual(parsed, ("закрыл 1 задачу", "доделать отчет", 6))

    def test_rejects_invalid_energy(self):
        self.assertIsNone(_parse_checkin_payload("done=сделал; carry=перенести; energy=11"))
        self.assertIsNone(_parse_checkin_payload("done=сделал; carry=перенести; energy=abc"))

    def test_rejects_no_known_fields(self):
        self.assertIsNone(_parse_checkin_payload("foo=bar; baz=qux"))


if __name__ == "__main__":
    unittest.main()
