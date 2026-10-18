"""Analytic ensemble summaries, daily availability and held-out selection checks."""

import unittest
import numpy as np
import pandas as pd

from solar_forecast.ensemble import weather_summaries
from solar_forecast.day_ahead import (
    synthetic_weather,
    daily_samples,
    daily_partitions,
    evaluate_daily,
)


class EnsembleTests(unittest.TestCase):
    def test_pairwise_and_three_member_statistics(self):
        frame = pd.DataFrame({"solar_a": [2.0], "solar_b": [6.0], "solar_c": [4.0]})
        pair = weather_summaries(frame, ("a", "b"), ("solar",)).iloc[0]
        self.assertAlmostEqual(pair.solar_mean, 4)
        self.assertAlmostEqual(pair.solar_std, np.sqrt(8))
        self.assertAlmostEqual(pair.solar_variance, 8)
        self.assertAlmostEqual(pair.solar_abs_difference, 4)
        self.assertAlmostEqual(pair.solar_range, 4)
        triple = weather_summaries(frame, ("a", "b", "c"), ("solar",)).iloc[0]
        self.assertAlmostEqual(triple.solar_std, 2)
        self.assertAlmostEqual(triple.solar_variance, 4)

    def test_four_member_variance_uses_every_member(self):
        frame = pd.DataFrame({"v_a": [1.0], "v_b": [2.0], "v_c": [3.0], "v_d": [4.0]})
        summary = weather_summaries(frame, ("a", "b", "c", "d"), ("v",))
        self.assertAlmostEqual(summary.v_variance.iloc[0], 5 / 3)
        changed = frame.copy()
        changed["v_d"] = 20
        self.assertGreater(
            weather_summaries(changed, ("a", "b", "c", "d"), ("v",)).v_variance.iloc[0],
            summary.v_variance.iloc[0],
        )
        with self.assertRaises(ValueError):
            weather_summaries(frame.drop(columns="v_d"), ("a", "b", "c", "d"), ("v",))

    def test_missing_members_and_values_are_not_silently_dropped(self):
        for frame, models in (
            (pd.DataFrame({"v_a": [1]}), ("a", "b")),
            (pd.DataFrame({"v_a": [1], "v_b": [np.nan]}), ("a", "b")),
            (pd.DataFrame({"v_a": [1]}), ("a",)),
        ):
            with self.assertRaises(ValueError):
                weather_summaries(frame, models, ("v",))


class DailyTests(unittest.TestCase):
    def test_generator_is_reproducible_and_has_no_night_power(self):
        frame = synthetic_weather(80)
        pd.testing.assert_frame_equal(frame, synthetic_weather(80))
        self.assertTrue((frame.loc[frame.envelope == 0, "power"] == 0).all())
        self.assertTrue((frame.power <= frame.envelope).all())

    def test_daily_historical_profiles_and_target_day_availability(self):
        frame = synthetic_weather(80)
        samples = daily_samples(frame)
        self.assertEqual(samples["actual"].shape, (73, 96))
        self.assertEqual(samples["issued_at"][0], frame.index[7 * 96])
        np.testing.assert_allclose(
            samples["actual"][0], frame.power.iloc[7 * 96 : 8 * 96]
        )
        modified = frame.copy()
        modified.iloc[7 * 96 : 8 * 96, modified.columns.get_loc("power")] *= 0.5
        changed = daily_samples(modified)
        for variant in ("means_only", "means_plus_variance"):
            np.testing.assert_array_equal(samples[variant][0], changed[variant][0])
        self.assertFalse(
            np.array_equal(samples["target_index"][0], changed["target_index"][0])
        )
        self.assertFalse(
            np.array_equal(samples["means_only"][1], changed["means_only"][1])
        )

    def test_rejects_missing_duplicate_and_unaligned_days(self):
        frame = synthetic_weather(80)
        bad_frames = (
            frame.iloc[1:],
            frame.drop(frame.index[50]),
            pd.concat([frame.iloc[:1], frame]),
            frame.tz_convert("Europe/London"),
        )
        for bad in bad_frames:
            with self.assertRaises(ValueError):
                daily_samples(bad)

    def test_holdout_cannot_change_tuning_or_calibration(self):
        samples = daily_samples(synthetic_weather(80))
        report, forecasts = evaluate_daily(samples)
        changed = {k: v.copy() for k, v in samples.items()}
        test = daily_partitions(len(samples["issued_at"]))["test"]
        changed["actual"][test] *= 0.5
        changed["target_index"][test] *= 0.5
        modified_report, modified_forecasts = evaluate_daily(changed)
        for variant in ("means_only", "means_plus_variance"):
            first, second = (
                report["variants"][variant],
                modified_report["variants"][variant],
            )
            self.assertEqual(first["training_cv"], second["training_cv"])
            self.assertEqual(first["alpha"], second["alpha"])
            self.assertEqual(first["interval"]["radius"], second["interval"]["radius"])
            np.testing.assert_array_equal(
                forecasts[variant], modified_forecasts[variant]
            )
            self.assertTrue((forecasts[variant + "_lower"] <= forecasts[variant]).all())
            self.assertTrue((forecasts[variant] <= forecasts[variant + "_upper"]).all())
        self.assertEqual(len(forecasts), len(test) * 96)
        self.assertTrue(np.isfinite(report["variance_ablation_mae_reduction"]))


if __name__ == "__main__":
    unittest.main()
