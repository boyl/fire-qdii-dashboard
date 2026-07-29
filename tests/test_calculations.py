from __future__ import annotations

import unittest
from datetime import date, timedelta

from server.calculations import (
    portfolio_summary,
    premium_rate,
    stress_portfolio,
    sustainability_runway,
    tracking_error,
)


class PortfolioCalculationsTest(unittest.TestCase):
    def test_rebalance_boundaries_are_inclusive(self):
        low = portfolio_summary({"nasdaq100": 40, "cash": 60})
        target = portfolio_summary({"nasdaq100": 50, "cash": 50})
        high = portfolio_summary({"nasdaq100": 60, "cash": 40})

        self.assertEqual(low["status"], "inside")
        self.assertEqual(target["transfer_to_target"], 0)
        self.assertEqual(high["status"], "inside")
        self.assertEqual(low["distance_to_lower_pp"], 0)
        self.assertEqual(high["distance_to_upper_pp"], 0)

    def test_zero_assets_returns_empty_summary(self):
        summary = portfolio_summary({})
        self.assertEqual(summary["status"], "empty")
        self.assertEqual(summary["equity_ratio"], 0)

    def test_extreme_stress_never_creates_negative_assets(self):
        result = stress_portfolio(
            {"nasdaq100": 100, "digital": 50},
            [
                {
                    "name": "extreme",
                    "shocks": {"nasdaq100": -100, "digital": -200},
                }
            ],
        )[0]
        self.assertEqual(result["total_after"], 0)
        self.assertEqual(result["values"]["digital"], 0)

    def test_sustainability_handles_zero_spend_and_negative_return(self):
        zero_spend = sustainability_runway(100_000, [0], -2)[0]
        finite = sustainability_runway(
            100_000,
            [24_000],
            -2,
            start_date=date(2026, 1, 1),
        )[0]
        self.assertTrue(zero_spend["sustainable"])
        self.assertFalse(finite["sustainable"])
        self.assertLess(finite["years"], 5)

    def test_premium_prefers_iopv(self):
        premium, basis = premium_rate(1.10, 1.00, 0.90)
        self.assertEqual(basis, "IOPV")
        self.assertAlmostEqual(premium, 10)

    def test_tracking_error_needs_30_overlapping_returns(self):
        start = date(2025, 1, 1)
        fund = {}
        benchmark = {}
        for index in range(65):
            key = (start + timedelta(days=index)).isoformat()
            benchmark[key] = 100 * (1.001**index)
            fund[key] = 100 * (1.0012**index)
        error = tracking_error(fund, benchmark)
        self.assertIsNotNone(error)
        self.assertGreaterEqual(error, 0)
        self.assertIsNone(
            tracking_error(
                dict(list(fund.items())[:20]),
                dict(list(benchmark.items())[:20]),
            )
        )


if __name__ == "__main__":
    unittest.main()
