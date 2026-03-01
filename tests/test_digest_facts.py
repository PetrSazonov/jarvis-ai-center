import unittest
from datetime import date, timedelta

from services.digest_service import _daily_unique_fact, day_number_on_planet


class DigestFactsTests(unittest.TestCase):
    def test_fallback_fact_has_cooldown_no_recent_repeats(self):
        birth = date(1984, 12, 15)
        start = date(2026, 2, 1)
        seen: list[str] = []
        for i in range(20):
            current = start + timedelta(days=i)
            day_number = day_number_on_planet(birth, current)
            fact = _daily_unique_fact(current, day_number)
            recent = seen[-7:]
            self.assertNotIn(fact, recent)
            seen.append(fact)


if __name__ == "__main__":
    unittest.main()
