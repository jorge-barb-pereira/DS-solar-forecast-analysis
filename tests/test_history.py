"""Offline historical request, alignment and excluded-comparator checks."""

import io
import json
import unittest
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pandas as pd

from solar_forecast.history import (
    COMPARATOR,
    INPUT_MODELS,
    acquire_history,
    evaluate_history,
    historical_partitions,
    weather_features,
)
from solar_forecast.open_meteo import (
    VARIABLES,
    WeatherError,
    build_request,
    fetch_weather,
)


class HistoricalRequestTests(unittest.TestCase):
    def test_historical_hosts_and_date_ranges(self):
        for mode, host in (
            ("historical-weather", "archive-api.open-meteo.com"),
            ("historical-forecast", "historical-forecast-api.open-meteo.com"),
            ("previous-runs", "previous-runs-api.open-meteo.com"),
        ):
            url, _ = build_request(
                latitude=0,
                longitude=0,
                mode=mode,
                start_date="2025-01-01",
                end_date="2025-12-31",
            )
            self.assertEqual(urlsplit(url).hostname, host)
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(query["end_date"], ["2025-12-31"])
            self.assertNotIn("forecast_days", query)
        for options in (
            {},
            {"start_date": "2025-01-01"},
            {"start_date": "2025-02-01", "end_date": "2025-01-01"},
            {"start_date": "2025-01-01", "end_date": "2026-12-31"},
        ):
            with self.assertRaises(WeatherError):
                build_request(
                    latitude=0, longitude=0, mode="historical-weather", **options
                )

    def test_response_must_cover_the_requested_range(self):
        columns = [v + "_era5" for v in VARIABLES]
        payload = {
            "hourly": {
                "time": list(range(0, 24 * 3600, 3600)),
                **{c: [1] * 24 for c in columns},
            },
            "hourly_units": {c: "test" for c in columns},
        }
        options = dict(
            latitude=0,
            longitude=0,
            mode="historical-weather",
            models="era5",
            start_date="1970-01-01",
            end_date="1970-01-01",
        )
        opener = lambda url, timeout: io.StringIO(json.dumps(payload))
        frame, _ = fetch_weather(**options, opener=opener)
        self.assertEqual(len(frame), 24)
        payload["hourly"]["time"].pop()
        for column in columns:
            payload["hourly"][column].pop()
        with self.assertRaises(WeatherError):
            fetch_weather(**options, opener=opener)

    def test_acquisition_rejects_unit_mismatch(self):
        def fake_fetcher(**kwargs):
            model = (
                "era5" if kwargs["mode"] == "historical-weather" else INPUT_MODELS[0]
            )
            columns = [
                v + ("_era5" if model == "era5" else "_previous_day1_" + model)
                for v in VARIABLES
            ]
            index = pd.date_range("2025-01-01", periods=24, freq="h", tz="UTC")
            return pd.DataFrame(1.0, index=index, columns=columns), {
                "units": {c: model for c in columns}
            }

        with self.assertRaises(WeatherError):
            acquire_history(
                latitude=0,
                longitude=0,
                start_date="2025-01-01",
                end_date="2025-01-01",
                fetcher=fake_fetcher,
            )


class HistoricalEvaluationTests(unittest.TestCase):
    def fixture(self):
        rng = np.random.default_rng(12)
        index = pd.date_range("2050-01-01", periods=72 * 24, freq="h", tz="UTC")
        frame = pd.DataFrame(index=index)
        for variable in VARIABLES:
            actual = (
                20
                + 4 * np.sin(np.arange(len(index)) / 24)
                + rng.normal(0, 0.1, len(index))
            )
            frame[variable + "_era5"] = actual
            for i, model in enumerate((*INPUT_MODELS, COMPARATOR)):
                frame[variable + "_" + model] = actual + rng.normal(i, 1, len(index))
        return frame

    def test_comparator_and_reference_never_enter_predictors(self):
        frame = self.fixture()
        original = weather_features(frame)
        changed = frame.copy()
        for column in changed:
            if column.endswith("_era5") or column.endswith("_" + COMPARATOR):
                changed[column] += 1000
        for name, values in weather_features(changed).items():
            pd.testing.assert_frame_equal(values, original[name])
        with self.assertRaises(ValueError):
            weather_features(frame, input_models=(*INPUT_MODELS, COMPARATOR))

    def test_comparator_and_holdout_changes_cannot_change_selection(self):
        frame = self.fixture()
        report, predictions = evaluate_history(frame)
        changed = frame.copy()
        test = historical_partitions(frame.index)["test"]
        for variable in VARIABLES:
            changed[variable + "_" + COMPARATOR] += 100
            changed.iloc[test, changed.columns.get_loc(variable + "_era5")] += 10
        updated, updated_predictions = evaluate_history(changed)
        for variable in report["variables"]:
            self.assertEqual(
                report["variables"][variable]["selection"],
                updated["variables"][variable]["selection"],
            )
            for variant in ("means_only", "means_plus_spread"):
                np.testing.assert_array_equal(
                    predictions[variable + "_" + variant],
                    updated_predictions[variable + "_" + variant],
                )


if __name__ == "__main__":
    unittest.main()
