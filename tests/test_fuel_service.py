import unittest

from services.fuel_service import _extract_change_pct_from_html, _extract_prices_from_html


class FuelServiceTests(unittest.TestCase):
    def test_extract_ai95_prices(self):
        html = """
        <tr><td>АИ-95</td><td>61,49</td></tr>
        <tr><td>AI-95</td><td>62.10</td></tr>
        <tr><td>ДТ</td><td>70,00</td></tr>
        """
        prices = _extract_prices_from_html(html)
        self.assertIn(61.49, prices)
        self.assertIn(62.10, prices)
        self.assertNotIn(70.00, prices)

    def test_prefers_ai95_not_ai100(self):
        html = """
        <div>АИ-95 Сейчас 68,66 р.</div>
        <div>АИ-100 Сейчас 105,70 р.</div>
        """
        prices = _extract_prices_from_html(html)
        self.assertIn(68.66, prices)
        self.assertNotIn(105.70, prices)

    def test_extract_change_pct_direct_percent(self):
        html = """
        <div>АИ-95 сейчас 68,66 р.</div>
        <div>Изменение за 24 часа: -0,45%</div>
        """
        pct = _extract_change_pct_from_html(html, current_price=68.66)
        self.assertIsNotNone(pct)
        self.assertAlmostEqual(float(pct), -0.45, places=2)

    def test_extract_change_pct_from_rub_delta(self):
        html = """
        <div>АИ-95 сейчас 68,66 р.</div>
        <div>Изменение за сутки: +0,34 руб</div>
        """
        pct = _extract_change_pct_from_html(html, current_price=68.66)
        self.assertIsNotNone(pct)
        self.assertAlmostEqual(float(pct), (0.34 / 68.66) * 100.0, places=2)


if __name__ == "__main__":
    unittest.main()
