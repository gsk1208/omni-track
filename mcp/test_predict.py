import unittest
from datetime import datetime, timedelta

import predict


class TestPredict(unittest.TestCase):
    def test_aggregate_daily_sums_same_day(self):
        readings = [
            {"timestamp": "2026-04-01T01:00:00Z", "value": 1},
            {"timestamp": "2026-04-01T23:00:00Z", "value": 2},
            {"timestamp": "2026-04-02T01:00:00Z", "value": 5},
        ]
        out = predict.aggregate_daily(readings)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][0].date().isoformat(), "2026-04-01")
        self.assertAlmostEqual(out[0][1], 3.0)
        self.assertEqual(out[1][0].date().isoformat(), "2026-04-02")
        self.assertAlmostEqual(out[1][1], 5.0)

    def test_detect_cadence_daily_weekly_monthly_other(self):
        base = datetime(2026, 1, 1)

        daily = [(base + timedelta(days=i), float(i)) for i in range(12)]
        self.assertEqual(predict.detect_cadence(daily), "daily")

        weekly = [(base + timedelta(days=7 * i), float(i)) for i in range(12)]
        self.assertEqual(predict.detect_cadence(weekly), "weekly")

        monthly = [(base + timedelta(days=30 * i), float(i)) for i in range(12)]
        self.assertEqual(predict.detect_cadence(monthly), "monthly")

        other = [(base + timedelta(days=i * 4), float(i)) for i in range(12)]
        self.assertEqual(predict.detect_cadence(other), "other")

    def test_forecast_ml_need_more_data(self):
        base = datetime(2026, 1, 1)
        series = [(base + timedelta(days=i), float(i)) for i in range(9)]
        fc = predict.forecast_ml(series, cadence="daily")
        self.assertEqual(fc.model, "need_more_data")
        self.assertEqual(fc.points, [])

    def test_forecast_ml_fallback_mean(self):
        base = datetime(2026, 1, 1)
        series = [(base + timedelta(days=i), float(i % 3)) for i in range(20)]

        # Force fallback mode by monkeypatching numpy to None
        orig = predict.np
        try:
            predict.np = None
            fc = predict.forecast_ml(series, cadence="daily")
        finally:
            predict.np = orig

        self.assertEqual(fc.model, "fallback_mean")
        self.assertEqual(len(fc.points), predict.horizon_points("daily"))
        self.assertTrue(all("timestamp" in p for p in fc.points))
        self.assertTrue(all(len(p["timestamp"]) == 10 for p in fc.points))  # YYYY-MM-DD

    def test_forecast_ml_numpy_path_shapes(self):
        # If numpy isn't installed, this test is skipped.
        if predict.np is None:
            self.skipTest("numpy not available")

        base = datetime(2026, 1, 1)
        series = [(base + timedelta(days=i), float(i)) for i in range(60)]
        fc = predict.forecast_ml(series, cadence="daily")
        self.assertEqual(fc.model, "ridge(poly2)")
        self.assertEqual(len(fc.points), predict.horizon_points("daily"))
        # monotonic timestamps
        ts = [p["timestamp"] for p in fc.points]
        self.assertEqual(ts, sorted(ts))


if __name__ == "__main__":
    unittest.main()
