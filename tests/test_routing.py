import unittest

from services.routing import RouteType, determine_route, should_persist_history


class RoutingTests(unittest.TestCase):
    def test_known_command_detected(self):
        decision = determine_route("/price", {"price", "reset"}, False)
        self.assertEqual(decision.route_type, RouteType.KNOWN_COMMAND)

    def test_unknown_slash_ephemeral(self):
        decision = determine_route("/unknown test", {"price", "reset"}, False)
        self.assertEqual(decision.route_type, RouteType.UNKNOWN_COMMAND)
        self.assertFalse(should_persist_history(decision))

    def test_plain_text_persists(self):
        decision = determine_route("hello", {"price"}, False)
        self.assertEqual(decision.route_type, RouteType.PLAIN_TEXT)
        self.assertTrue(should_persist_history(decision))


if __name__ == "__main__":
    unittest.main()
