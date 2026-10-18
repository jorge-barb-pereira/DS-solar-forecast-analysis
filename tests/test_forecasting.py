import unittest
import numpy as np
import pandas as pd
from solar_forecast.data import synthetic_series, validate_series
from solar_forecast.features import make_samples, chronological_partitions
from solar_forecast.study import metrics, residual_radius, run_study


class DataTests(unittest.TestCase):
    def test_generator_is_reproducible_and_bounded(self):
        a, b = synthetic_series(30), synthetic_series(30)
        pd.testing.assert_series_equal(a, b)
        self.assertTrue(a.between(0, 1).all())
        self.assertEqual(len(a), 30 * 96)
        self.assertTrue((a[a.index.hour < 6] == 0).all())
        self.assertTrue((a[a.index.hour >= 18] == 0).all())

    def test_invalid_generation_length(self):
        for days in [0, 29, True, 30.5]:
            with self.assertRaises(ValueError):
                synthetic_series(days)

    def test_missing_duplicate_or_disordered_timestamps_rejected(self):
        s = synthetic_series(30)
        for invalid in [s.drop(s.index[100]), pd.concat([s, s.iloc[:1]]), s.iloc[::-1]]:
            with self.assertRaises(ValueError):
                validate_series(invalid)

    def test_nonfinite_or_out_of_range_values_rejected(self):
        for value in [np.nan, np.inf, -0.1, 1.1]:
            s = synthetic_series(30)
            s.iloc[100] = value
            with self.assertRaises(ValueError):
                validate_series(s)


class FeatureTests(unittest.TestCase):
    def test_known_lags_targets_and_daily_reference(self):
        s = synthetic_series(30)
        frame = make_samples(s, horizon=4)
        row = frame.iloc[100]
        pos = s.index.get_loc(frame.index[100])
        self.assertEqual(row.observed_now, s.iloc[pos])
        self.assertEqual(row.lag_1, s.iloc[pos - 1])
        self.assertEqual(row.target, s.iloc[pos + 4])
        self.assertEqual(row.daily_reference, s.iloc[pos + 4 - 96])

    def test_future_perturbations_cannot_change_issue_time_features(self):
        s = synthetic_series(30)
        t = s.index[1000]
        a = make_samples(s).loc[t]
        changed = s.copy()
        changed.loc[changed.index > t] = 0.123
        b = make_samples(changed).loc[t]
        pd.testing.assert_series_equal(a.drop(["target"]), b.drop(["target"]))
        self.assertNotEqual(a.target, b.target)

    def test_partitions_purge_all_boundary_crossing_targets(self):
        for horizon in [1, 4, 96]:
            parts = chronological_partitions(
                make_samples(synthetic_series(30), horizon)
            )
            blocks = list(parts.values())
            for before, after in zip(blocks, blocks[1:]):
                self.assertLess(before.target_time.max(), after.index.min())
                self.assertTrue(before.index.intersection(after.index).empty)

    def test_invalid_horizons_rejected(self):
        for h in [0, 97, True, 1.5]:
            with self.assertRaises(ValueError):
                make_samples(synthetic_series(30), h)


class MetricTests(unittest.TestCase):
    def test_hand_calculated_errors(self):
        m = metrics([0, 1], [0.2, 0.6])
        self.assertAlmostEqual(m["mae"], 0.3)
        self.assertAlmostEqual(m["rmse"], np.sqrt(0.1))
        self.assertAlmostEqual(m["bias"], -0.1)

    def test_zero_power_is_well_defined(self):
        self.assertEqual(metrics([0, 0], [0, 0])["mae"], 0)

    def test_invalid_metric_inputs_rejected(self):
        for a, b in [([], []), ([1], [1, 2]), ([np.nan], [0])]:
            with self.assertRaises(ValueError):
                metrics(a, b)

    def test_finite_sample_residual_rank(self):
        self.assertEqual(residual_radius(np.zeros(9), np.arange(1, 10), 0.8), 8)
        with self.assertRaises(ValueError):
            residual_radius([0], [1], 0.99)

    def test_complete_chronological_experiment(self):
        report, forecast = run_study(synthetic_series(30))
        self.assertEqual(
            report["selected_model"], report["validation_comparison"][0]["model"]
        )
        self.assertEqual(len(report["validation_comparison"]), 6)
        self.assertEqual(report["holdout"]["samples"], len(forecast))
        self.assertTrue(forecast.prediction.between(0, 1).all())
        self.assertTrue((forecast.lower <= forecast.upper).all())
        self.assertTrue((forecast.lower <= forecast.prediction).all())
        self.assertTrue((forecast.prediction <= forecast.upper).all())
        self.assertTrue(0 <= report["interval"]["observed_coverage"] <= 1)

    def test_holdout_changes_do_not_affect_selection_or_calibration(self):
        series = synthetic_series(30)
        before, _ = run_study(series)
        boundary = pd.Timestamp(before["partitions"]["test"]["first_issue"])
        modified = series.copy()
        modified.loc[modified.index >= boundary] = 0.123
        after, _ = run_study(modified)
        self.assertEqual(before["selected_model"], after["selected_model"])
        self.assertEqual(
            before["validation_comparison"], after["validation_comparison"]
        )
        self.assertEqual(
            before["interval"]["residual_radius"], after["interval"]["residual_radius"]
        )


if __name__ == "__main__":
    unittest.main()
