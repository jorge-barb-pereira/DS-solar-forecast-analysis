"""Offline contract and privacy checks for the optional weather provider."""

import io
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from solar_forecast.open_meteo import (
    VARIABLES,
    WeatherError,
    build_request,
    fetch_weather,
)


class WeatherTests(unittest.TestCase):
    def payload(self, resolution="hourly", columns=VARIABLES):
        step = 900 if resolution == "minutely_15" else 3600
        return {
            "latitude": "PRIVATE_ECHO",
            "longitude": "PRIVATE_ECHO",
            "elevation": "PRIVATE_ECHO",
            "unrequested": "PRIVATE_ECHO",
            resolution: {"time": [0, step], **{c: [1, None] for c in columns}},
            resolution + "_units": {c: "test_unit" for c in columns},
        }

    def acquire(self, payload, **kwargs):
        return fetch_weather(
            latitude=0,
            longitude=0,
            opener=lambda url, timeout: io.StringIO(json.dumps(payload)),
            **kwargs,
        )

    def test_request_modes_and_model_columns(self):
        url, columns = build_request(
            latitude=0, longitude=0, models="icon_eu,ecmwf_ifs025"
        )
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["timeformat"], ["unixtime"])
        self.assertEqual(params["timezone"], ["GMT"])
        self.assertEqual(len(columns), 6)
        url, columns = build_request(
            latitude=0, longitude=0, mode="previous-runs", previous_days=3
        )
        self.assertEqual(urlsplit(url).hostname, "previous-runs-api.open-meteo.com")
        self.assertTrue(all(c.endswith("_previous_day3") for c in columns))
        url, _ = build_request(
            latitude=0,
            longitude=0,
            mode="single-run",
            models="icon_eu",
            run="2026-10-01T00:00",
        )
        self.assertEqual(parse_qs(urlsplit(url).query)["run"], ["2026-10-01T00:00"])

    def test_utc_missing_values_and_no_site_echo(self):
        for resolution in ("hourly", "minutely_15"):
            with self.subTest(resolution=resolution):
                frame, metadata = self.acquire(
                    self.payload(resolution), resolution=resolution
                )
                self.assertEqual(str(frame.index.tz), "UTC")
                self.assertTrue(frame.iloc[1].isna().all())
                self.assertNotIn("PRIVATE_ECHO", frame.to_csv() + json.dumps(metadata))
                self.assertEqual(set(metadata["units"]), set(VARIABLES))

    def test_explicit_single_and_multiple_models(self):
        frame, _ = self.acquire(self.payload(), models="icon_eu")
        self.assertEqual(list(frame.columns), [v + "_icon_eu" for v in VARIABLES])
        columns = tuple(
            v + "_" + m for v in VARIABLES for m in ("icon_eu", "ecmwf_ifs025")
        )
        frame, _ = self.acquire(
            self.payload(columns=columns), models="icon_eu,ecmwf_ifs025"
        )
        self.assertEqual(tuple(frame.columns), columns)

    def test_bad_requests_fail_before_network(self):
        for options in (
            {"latitude": float("nan")},
            {"longitude": 181},
            {"days": 0},
            {"models": "bad&parameter"},
            {"mode": "single-run"},
            {"run": "2026-10-01T00:00"},
            {"mode": "previous-runs", "resolution": "minutely_15"},
            {"mode": "previous-runs", "previous_days": 8},
        ):
            with self.subTest(options=options), self.assertRaises(WeatherError):
                build_request(**({"latitude": 0, "longitude": 0} | options))

    def test_ambiguous_multimodel_response_is_rejected(self):
        with self.assertRaises(WeatherError):
            self.acquire(self.payload(), models="icon_global,ecmwf_ifs025")

    def test_bad_responses_are_rejected(self):
        for fault in (
            "missing",
            "length",
            "duplicate",
            "gap",
            "nonnumeric",
            "infinite",
        ):
            payload = self.payload()
            if fault == "missing":
                del payload["hourly"][VARIABLES[0]]
            elif fault == "length":
                payload["hourly"][VARIABLES[0]] = [1]
            elif fault == "duplicate":
                payload["hourly"]["time"] = [0, 0]
            elif fault == "gap":
                payload["hourly"]["time"] = [0, 7200]
            elif fault == "nonnumeric":
                payload["hourly"][VARIABLES[0]][0] = "PRIVATE_ECHO"
            else:
                payload["hourly"][VARIABLES[0]][0] = float("inf")
            with self.subTest(fault=fault), self.assertRaises(WeatherError):
                self.acquire(payload)

    def test_network_errors_do_not_disclose_request(self):
        def failure(url, timeout):
            raise OSError("PRIVATE_REQUEST_URL " + url)

        with self.assertRaises(WeatherError) as caught:
            fetch_weather(latitude=0, longitude=0, opener=failure)
        self.assertNotIn("PRIVATE_REQUEST_URL", str(caught.exception))
        self.assertNotIn("latitude", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)


if __name__ == "__main__":
    unittest.main()
