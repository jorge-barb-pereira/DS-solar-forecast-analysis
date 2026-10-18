"""Chronological window and paired block-inference invariants."""

import unittest
import numpy as np
import pandas as pd

from solar_forecast.history import evaluate_history
from solar_forecast.robustness import (
    aggregate_report,
    paired_interval,
    rolling_partitions,
)
import test_history


class RobustnessTests(unittest.TestCase):
    def test_rolling_windows_have_gaps_and_no_repeated_test_hours(self):
        index = pd.date_range("2050-01-01", periods=365 * 24, freq="h", tz="UTC")
        windows = rolling_partitions(index)
        self.assertEqual(len(windows), 7)
        self.assertEqual(len(windows[0]["train"]), 120 * 24)
        for fold in windows:
            self.assertEqual(fold["validation"][0] - fold["train"][-1] - 1, 7 * 24)
            self.assertEqual(fold["test"][0] - fold["validation"][-1] - 1, 7 * 24)
        tests = np.concatenate([fold["test"] for fold in windows])
        self.assertEqual(len(np.unique(tests)), 201 * 24)
        self.assertGreater(len(windows[-1]["train"]), len(windows[0]["train"]))

    def test_constant_paired_differences_have_exact_weighted_interval(self):
        result = paired_interval(
            [np.ones(14), np.full(28, 3.0)], block_days=7, repetitions=100
        )
        for key in ("mean_mae_reduction", "lower_95", "upper_95"):
            self.assertAlmostEqual(result[key], 7 / 3)
        negative = paired_interval([np.full(21, -2.0)], repetitions=100)
        self.assertEqual(negative["upper_95"], -2)
        zeros = paired_interval([np.zeros(21)], repetitions=100)
        self.assertEqual(zeros["lower_95"], 0)

    def test_bootstrap_is_reproducible_and_rejects_short_nonfinite_blocks(self):
        values = [np.random.default_rng(5).normal(size=30)]
        self.assertEqual(paired_interval(values), paired_interval(values))
        for invalid in ([np.ones(3)], [np.full(20, np.nan)], []):
            with self.assertRaises(ValueError):
                paired_interval(invalid)

    def test_explicit_partition_validation_and_future_label_separation(self):
        frame = test_history.HistoricalEvaluationTests().fixture()
        parts = {
            "train": np.arange(24 * 30),
            "validation": np.arange(24 * 31, 24 * 45),
            "test": np.arange(24 * 46, 24 * 60),
        }
        report, forecast = evaluate_history(frame, parts)
        changed = frame.copy()
        for name in ("shortwave_radiation", "temperature_2m"):
            changed.iloc[parts["test"], changed.columns.get_loc(name + "_era5")] += 100
        updated, predictions = evaluate_history(changed, parts)
        for name in report["variables"]:
            self.assertEqual(
                report["variables"][name]["selection"],
                updated["variables"][name]["selection"],
            )
            for variant in ("means_only", "means_plus_variance"):
                np.testing.assert_array_equal(
                    forecast[name + "_" + variant], predictions[name + "_" + variant]
                )
        overlapping = dict(parts, validation=parts["train"])
        with self.assertRaises(ValueError):
            evaluate_history(frame, overlapping)

    def test_aggregate_estimand_matches_pooled_scores_and_omits_private_metadata(self):
        import json

        source = test_history.HistoricalEvaluationTests().fixture()
        frame = pd.DataFrame(
            np.resize(source.to_numpy(), (240 * 24, len(source.columns))),
            columns=source.columns,
            index=pd.date_range("2050-01-01", periods=240 * 24, freq="h", tz="UTC"),
        )
        frame.attrs["location"] = "PRIVATE_LOCATION_SENTINEL"
        # A valid reference can have no positive radiation (e.g. polar night).
        frame["shortwave_radiation_era5"] = 0.0
        report = aggregate_report(frame, repetitions=100)
        self.assertNotIn("PRIVATE_LOCATION_SENTINEL", json.dumps(report))
        self.assertEqual(report["rolling"]["test_days"], 76)
        radiation = report["rolling"]["variables"]["shortwave_radiation"]
        self.assertEqual(radiation["positive_reference_hours_count"], 0)
        self.assertEqual(radiation["positive_reference_radiation_hours"], {})
        for variable, scores in report["rolling"]["variables"].items():
            for baseline, sensitivity in scores["paired_mae_reduction_vs"].items():
                expected = (
                    scores["pooled_test"][baseline]["mae"]
                    - scores["pooled_test"]["means_plus_variance"]["mae"]
                )
                self.assertAlmostEqual(sensitivity["7"]["mean_mae_reduction"], expected)


if __name__ == "__main__":
    unittest.main()
