"""Offline tests on synthetic series: each case targets one rule in analysis.py.

Run from the skill folder:  .venv/bin/python -m unittest discover tests
"""

import datetime as dt
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import analysis  # noqa: E402
import report  # noqa: E402

START, END = dt.date(2021, 9, 1), dt.date(2026, 8, 31)  # 60 whole months


def series(views_on) -> dict[str, int]:
    """Daily series built from a function of (day, years since START)."""
    days = (END - START).days + 1
    out = {}
    for i in range(days):
        day = START + dt.timedelta(days=i)
        out[day.isoformat()] = max(0, round(views_on(day, i / 365.25)))
    return out


def flat_project(views: float = 1e8) -> dict[str, int]:
    return {k: int(views) for k in analysis.monthly(series(lambda d, y: 1))}


def run(daily, project=None, months=24, proxy=False, bot_geo=None) -> dict:
    return analysis.rate(analysis.metrics(daily, project or flat_project(), months), proxy, bot_geo)


class Metrics(unittest.TestCase):
    def test_seasonal_without_growth_is_flat(self):
        # Strong January peak every year, same level each year.
        r = run(series(lambda d, y: 200 * (1 + 0.8 * math.cos((d.month - 1) / 12 * 2 * math.pi))))
        self.assertEqual(r["trend"], "flat")
        self.assertLess(abs(r["yoy"]), 0.02)
        self.assertIn("stable", [x["code"] for x in r["reasons"]])

    def test_steady_growth_is_high_confidence(self):
        r = run(series(lambda d, y: 200 * 1.3 ** y))
        self.assertEqual(r["trend"], "growing")
        self.assertAlmostEqual(r["yoy"], 0.3, delta=0.03)
        self.assertEqual(r["months_up"], 12)
        self.assertEqual(r["confidence"], "HIGH")

    def test_single_spike_is_flagged(self):
        daily = series(lambda d, y: 200)
        daily["2026-03-10"] = 60_000  # one viral day
        r = run(daily)
        self.assertGreater(r["yoy"], 0.2)
        self.assertLess(abs(r["yoy_clean"]), 0.01)
        self.assertIn("spikes", [x["code"] for x in r["reasons"]])
        self.assertNotEqual(r["confidence"], "HIGH")

    def test_growth_of_whole_wiki_is_not_topic_growth(self):
        daily = series(lambda d, y: 200 * 1.25 ** y)
        project = {k: int(1e8 * 1.25 ** (i / 12)) for i, k in enumerate(analysis.monthly(daily))}
        r = run(daily, project)
        self.assertEqual(r["trend"], "growing")
        self.assertLess(abs(r["norm_yoy"]), 0.03)
        self.assertIn("wiki_trend", [x["code"] for x in r["reasons"]])
        self.assertEqual(r["confidence"], "MEDIUM")

    def test_low_volume_caps_confidence(self):
        r = run(series(lambda d, y: 5 * 1.3 ** y))
        self.assertEqual(r["confidence"], "LOW")
        self.assertIn("low_volume", [x["code"] for x in r["reasons"]])

    def test_new_article_is_flagged(self):
        r = run(series(lambda d, y: 0 if d < dt.date(2025, 3, 1) else 300))
        self.assertEqual(r["first_month"], "2025-03")
        self.assertEqual(r["confidence"], "LOW")

    def test_window_change_only_for_long_windows(self):
        daily = series(lambda d, y: 200 * 1.3 ** y)
        self.assertIsNone(run(daily, months=24)["window_change"])
        self.assertAlmostEqual(run(daily, months=36)["window_change"], 1.3 ** 2 - 1, delta=0.05)

    def test_sign_test(self):
        self.assertAlmostEqual(analysis.sign_test(12, 0), 2 / 4096)
        self.assertEqual(analysis.sign_test(6, 6), 1.0)


class Text(unittest.TestCase):
    def result(self):
        good = {**run(series(lambda d, y: 200 * 1.3 ** y)), "lang": "cs", "name": "Czech",
                "name_uk": "чеська", "status": "ok", "coverage": "1/1"}
        missing = {"lang": "pl", "name": "Polish", "name_uk": "польська", "status": "not_found"}
        return {"topic": "Intermittent fasting", "languages": [good, missing]}

    def test_findings_in_both_languages(self):
        en = analysis.findings(self.result(), "en")
        self.assertIn("Czech: growing, +30% year over year and +30% relative to the whole Czech Wikipedia", en[0])
        self.assertIn("12/12 months above the same month last year", en[0])
        self.assertIn("content gap", en[1])
        uk = analysis.findings(self.result(), "uk")
        self.assertIn("Чеська: інтерес зростає", uk[0])

    def test_decline_is_described_in_its_direction(self):
        r = {**run(series(lambda d, y: 2000 * 0.6 ** y)), "name": "Ukrainian", "name_uk": "українська"}
        self.assertEqual(analysis.months_text(r, short=True), "12/12 down")
        self.assertIn("12/12 місяців нижче", analysis.months_text(r, "uk"))

    def test_bot_like_geography_is_not_ranked(self):
        result = self.result()
        daily = series(lambda d, y: 900 * 1.3 ** y)
        bots = analysis.bot_geography("vi", [["US", 0.47], ["SG", 0.05]])
        vi = {**run(daily, bot_geo=bots), "lang": "vi", "name": "Vietnamese", "name_uk": "в'єтнамська",
              "status": "ok", "coverage": "1/1"}
        result["languages"].append(vi)
        text = " ".join(analysis.findings(result))
        self.assertIn("Not ranked, because reader geography suggests bots (numbers marked ?): Vietnamese", text)
        summary = analysis.findings(result, per_language=False)
        self.assertFalse(any(line.startswith("Czech:") for line in summary))  # table has these numbers
        self.assertIsNone(analysis.bot_geography("en", [["US", 0.47]]))

    def test_topic_comparison_ranks_topics_per_language(self):
        small = {**run(series(lambda d, y: 50)), "lang": "pl", "name": "Polish", "name_uk": "польська",
                 "status": "ok", "topic": "Computer vision"}
        big = {**run(series(lambda d, y: 300)), "lang": "pl", "name": "Polish", "name_uk": "польська",
               "status": "ok", "topic": "Neural network"}
        result = {"topic": "Computer vision vs Neural network", "compare": True, "languages": [small, big]}
        line = analysis.findings(result)[0]
        self.assertTrue(line.startswith("Polish, most read topic first: Neural network"))
        self.assertLess(line.index("Neural network"), line.index("Computer vision"))

    def test_claims_check_flags_invented_numbers(self):
        result = self.result()
        ok = "Czech interest grew +30% year over year."
        bad = "Czech interest grew 45% and reached 90,000 readers."
        self.assertEqual(report.check_claims(ok, result), [])
        self.assertEqual(report.check_claims(bad, result), ["45%", "90,000"])
        self.assertEqual(report.check_claims("see section 1..2", result), [])


if __name__ == "__main__":
    unittest.main()
