import unittest

from handlers.advanced_ops import _fmt_delta, _scenario_params


class AdvancedOpsHelpersTests(unittest.TestCase):
    def test_fmt_delta_positive_negative_zero(self) -> None:
        self.assertEqual(_fmt_delta(7.2, 5.0), "+2.2")
        self.assertEqual(_fmt_delta(4.1, 6.6), "-2.5")
        self.assertEqual(_fmt_delta(3.0, 3.0), "0.0")

    def test_scenario_params_energy_high(self) -> None:
        plan_a, plan_b, plan_c, risk = _scenario_params(avg_energy=7.5, open_count=4)
        self.assertEqual((plan_a, plan_b, plan_c), (4, 3, 1))
        self.assertEqual(risk, "контекстные переключения")

    def test_scenario_params_energy_low_and_bounds(self) -> None:
        plan_a, plan_b, plan_c, risk = _scenario_params(avg_energy=4.0, open_count=10)
        self.assertEqual((plan_a, plan_b, plan_c), (5, 3, 1))
        self.assertEqual(risk, "перегруз")


if __name__ == "__main__":
    unittest.main()

