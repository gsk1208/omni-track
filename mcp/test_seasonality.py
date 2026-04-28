import unittest

import seasonality


class TestSeasonality(unittest.TestCase):
    def test_weekday_and_month_buckets(self):
        # 2026-04-06 is Monday; 2026-04-11 is Saturday; 2026-05-03 is Sunday.
        readings = [
            {"timestamp": "2026-04-06T10:00:00Z", "value": 10},
            {"timestamp": "2026-04-07T10:00:00Z", "value": 20},
            {"timestamp": "2026-04-11T10:00:00Z", "value": 30},
            {"timestamp": "2026-05-03T10:00:00Z", "value": 50},
        ]
        out = seasonality.compute_seasonality(readings, viz_type="line")
        self.assertEqual(len(out["weekday"]), 7)
        self.assertEqual(len(out["month"]), 12)

        # Monday bucket should have a value.
        mon = out["weekday"][0]
        self.assertEqual(mon["label"], "Mon")
        self.assertEqual(mon["count"], 1)
        self.assertAlmostEqual(mon["value"], 10.0)

        # April and May month buckets
        apr = out["month"][3]  # 4th entry = April
        may = out["month"][4]
        self.assertEqual(apr["label"], "Apr")
        self.assertEqual(apr["count"], 3)
        self.assertEqual(may["label"], "May")
        self.assertEqual(may["count"], 1)

        # Weekend vs weekday should be computable
        wvw = out["weekend_vs_weekday"]
        self.assertIsNotNone(wvw["weekday_avg"])
        self.assertIsNotNone(wvw["weekend_avg"])

    def test_bar_viz_sums_daily(self):
        readings = [
            {"timestamp": "2026-04-06T01:00:00Z", "value": 1},
            {"timestamp": "2026-04-06T23:00:00Z", "value": 2},
        ]
        out = seasonality.compute_seasonality(readings, viz_type="bar")
        mon = out["weekday"][0]
        self.assertAlmostEqual(mon["value"], 3.0)
        self.assertEqual(mon["count"], 1)  # daily point count


if __name__ == "__main__":
    unittest.main()

