"""Complete training year, frozen evaluation and availability cutoff checks."""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd

import test_history
from solar_forecast.yearly import (
    available_prefix,
    evaluate_test_year,
    fit_training_year,
    selection_folds,
    validate_year,
    write_report,
)


class YearlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = test_history.HistoricalEvaluationTests().fixture()
        cls.training = pd.DataFrame(
            np.resize(source.to_numpy(), (365 * 24, len(source.columns))),
            columns=source.columns,
            index=pd.date_range("2025-01-01", periods=365 * 24, freq="h", tz="UTC"),
        )
        cls.testing = cls.training.iloc[: 31 * 24].copy()
        cls.testing.index = pd.date_range(
            "2026-01-01", periods=31 * 24, freq="h", tz="UTC"
        )
        cls.frozen, cls.protocol = fit_training_year(cls.training)

    def test_complete_year_refit_and_selection_stay_in_2025(self):
        self.assertEqual(self.protocol["training_hours"], 8760)
        self.assertEqual(self.protocol["last_training_time"][:10], "2025-12-31")
        for train, validation in selection_folds(self.training.index):
            self.assertEqual(validation[0] - train[-1] - 1, 7 * 24)
            self.assertTrue((self.training.index[validation].year == 2025).all())
        for models in self.frozen.values():
            for model in models.values():
                if hasattr(model, "named_steps"):
                    self.assertEqual(
                        model.named_steps["standardscaler"].n_samples_seen_, 8760
                    )

    def test_rejects_partial_training_and_non_january_test_prefix(self):
        with self.assertRaises(ValueError):
            validate_year(self.training.iloc[:-24], 2025, complete=True)
        with self.assertRaises(ValueError):
            validate_year(self.testing.iloc[24:], 2026)
        with self.assertRaises(ValueError):
            validate_year(self.testing.drop(self.testing.index[5]), 2026)

    def test_frozen_predictions_ignore_test_labels_and_unused_gem(self):
        report, predicted = evaluate_test_year(
            self.frozen, self.protocol, self.testing, repetitions=100
        )
        modified = self.testing.copy()
        for col in modified:
            if col.endswith("_era5") or col.endswith("_gem_global"):
                modified[col] += 100
        updated, again = evaluate_test_year(
            self.frozen, self.protocol, modified, repetitions=100
        )
        self.assertEqual(
            report["training"]["selection"], updated["training"]["selection"]
        )
        for variable in ("shortwave_radiation", "temperature_2m"):
            for variant in ("means_only", "means_plus_variance"):
                np.testing.assert_array_equal(
                    predicted[variable + "_" + variant], again[variable + "_" + variant]
                )
        self.assertFalse(report["model_updates_during_test"])
        self.assertEqual(report["test_days"], 31)
        self.assertEqual(
            report["variables"]["temperature_2m"]["availability_buffered"][
                "means_only"
            ]["samples"],
            24 * 24,
        )

    def test_evaluation_never_calls_fit(self):
        models = {}
        for variable, variants in self.frozen.items():
            models[variable] = {
                name: Mock(wraps=model) for name, model in variants.items()
            }
        evaluate_test_year(models, self.protocol, self.testing, repetitions=100)
        for variants in models.values():
            for model in variants.values():
                model.fit.assert_not_called()

    def test_availability_removes_only_trailing_incomplete_days(self):
        index = pd.date_range("2026-01-01", periods=5 * 24, freq="h", tz="UTC")
        forecast = pd.DataFrame({"forecast": [1.0] * len(index)}, index=index)
        reference = pd.DataFrame({"reference": [1.0] * len(index)}, index=index)
        reference.iloc[-2 * 24 :] = np.nan
        trimmed, excluded = available_prefix(forecast, reference)
        self.assertEqual(len(trimmed), 3 * 24)
        self.assertEqual(excluded, 2)
        reference.iloc[24] = np.nan
        with self.assertRaises(ValueError):
            available_prefix(forecast, reference)

    def test_availability_rejects_non_calendar_grids(self):
        valid = self.testing.iloc[:48]
        grids = [
            valid.index + pd.Timedelta(hours=1),
            valid.index.tz_localize(None),
            valid.index[::-1],
            valid.index[:24].append(valid.index[:24]),
            pd.Index(range(48)),
        ]
        for index in grids:
            with self.subTest(index_type=type(index).__name__):
                frame = pd.DataFrame({"forecast": np.ones(48)}, index=index)
                reference = frame.rename(columns={"forecast": "reference"})
                with self.assertRaises(ValueError):
                    available_prefix(frame, reference)
        with self.assertRaises(ValueError):
            available_prefix(valid.iloc[:0], valid.iloc[:0])

    def test_zero_radiation_subset_is_explicitly_empty(self):
        frame = self.testing.iloc[:24].copy()
        frame["shortwave_radiation_era5"] = 0.0
        report, _ = evaluate_test_year(self.frozen, self.protocol, frame)
        radiation = report["variables"]["shortwave_radiation"]
        self.assertEqual(radiation["positive_reference_hours_count"], 0)
        self.assertEqual(radiation["positive_reference_hours"], {})
        self.assertEqual(radiation["all_hours"]["means_only"]["samples"], 24)
        self.assertEqual(radiation["paired_mae_reduction_vs"], {})

    def test_mismatched_training_member_identity_is_rejected(self):
        protocol = dict(self.protocol, input_models=["different_model"] * 4)
        with self.assertRaisesRegex(ValueError, "identities"):
            evaluate_test_year(self.frozen, protocol, self.testing)

    def test_report_uses_actual_replicates_and_cache_scope(self):
        report, _ = evaluate_test_year(
            self.frozen, self.protocol, self.testing, repetitions=100
        )
        with tempfile.TemporaryDirectory() as folder:
            write_report(report, folder)
            text = (Path(folder) / "YEARLY_RESULTS.md").read_text(encoding="utf-8")
        self.assertIn("100 paired circular", text)
        self.assertIn("cache is not checked for newer provider data", text)
        self.assertNotIn("2,000 paired", text)

    def test_complete_test_year_status(self):
        testing = self.training.copy()
        testing.index = pd.date_range("2026-01-01", periods=8760, freq="h", tz="UTC")
        report, _ = evaluate_test_year(
            self.frozen, self.protocol, testing, repetitions=100
        )
        self.assertEqual(report["test_status"], "Complete calendar test year")


if __name__ == "__main__":
    unittest.main()
