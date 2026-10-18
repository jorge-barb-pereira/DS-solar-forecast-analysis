"""Optional public weather acquisition; no site configuration is stored here."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

ENDPOINTS = {
    "forecast": "https://api.open-meteo.com/v1/forecast",
    "previous-runs": "https://previous-runs-api.open-meteo.com/v1/forecast",
    "single-run": "https://single-runs-api.open-meteo.com/v1/forecast",
}
VARIABLES = ("temperature_2m", "cloud_cover", "shortwave_radiation")


class WeatherError(ValueError):
    """Safe message suitable for logging without a private request URL."""


def build_request(
    *,
    latitude,
    longitude,
    mode="forecast",
    resolution="hourly",
    models=None,
    days=2,
    run=None,
    previous_days=1,
):
    """Construct one site request; callers must treat the returned URL as private."""
    if not all(
        isinstance(v, (int, float)) and math.isfinite(v) for v in (latitude, longitude)
    ):
        raise WeatherError("Location settings must be finite numbers.")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise WeatherError("Location settings are outside valid ranges.")
    if mode not in ENDPOINTS or resolution not in {"hourly", "minutely_15"}:
        raise WeatherError("Unsupported acquisition mode or resolution.")
    if not isinstance(days, int) or not 1 <= days <= 16:
        raise WeatherError("Forecast days must be between 1 and 16.")
    if models is not None and not re.fullmatch(r"[a-z0-9_]+(?:,[a-z0-9_]+)*", models):
        raise WeatherError("Models must be comma-separated provider model identifiers.")
    variables = VARIABLES
    if mode == "previous-runs":
        if (
            resolution != "hourly"
            or not isinstance(previous_days, int)
            or not 0 <= previous_days <= 7
        ):
            raise WeatherError(
                "Previous runs require hourly data and a day offset from 0 to 7."
            )
        variables = tuple(f"{v}_previous_day{previous_days}" for v in VARIABLES)
    elif previous_days != 1:
        raise WeatherError("Day offsets apply only to previous runs.")
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": "GMT",
        "timeformat": "unixtime",
        resolution: ",".join(variables),
        "forecast_days": days,
    }
    if models:
        params["models"] = models
    if mode == "single-run":
        if not models or "," in models:
            raise WeatherError("Select one explicit model for a single run.")
        try:
            parsed = datetime.strptime(run or "", "%Y-%m-%dT%H:%M")
        except ValueError:
            raise WeatherError(
                "Single runs require a UTC run in YYYY-MM-DDTHH:MM format."
            ) from None
        if parsed.strftime("%Y-%m-%dT%H:%M") != run:
            raise WeatherError("Invalid UTC run format.")
        params["run"] = run
    elif run is not None:
        raise WeatherError("Run initialization applies only to single-run mode.")
    columns = (
        tuple(f"{v}_{m}" for v in variables for m in models.split(","))
        if models
        else variables
    )
    return ENDPOINTS[mode] + "?" + urlencode(params), columns


def fetch_weather(
    *,
    latitude,
    longitude,
    mode="forecast",
    resolution="hourly",
    models=None,
    days=2,
    run=None,
    previous_days=1,
    opener=None,
):
    """Return selected UTC weather columns and safe provenance, never raw metadata.

    Missing provider values remain NaN. A run's initialization is not its release
    time; these records alone do not establish historical feature availability.
    """
    url, columns = build_request(
        latitude=latitude,
        longitude=longitude,
        mode=mode,
        resolution=resolution,
        models=models,
        days=days,
        run=run,
        previous_days=previous_days,
    )
    try:
        with (opener or urlopen)(url, timeout=30) as response:
            payload = json.load(response)
    except Exception:
        raise WeatherError(
            "Open-Meteo request failed; check connectivity, limits and model availability."
        ) from None
    try:
        block = payload[resolution]
        units = payload[resolution + "_units"]
        timestamps = block["time"]
        if (
            not isinstance(timestamps, list)
            or not timestamps
            or any(
                not isinstance(t, (int, float)) or not math.isfinite(t)
                for t in timestamps
            )
        ):
            raise ValueError
        index = pd.to_datetime(timestamps, unit="s", utc=True)
        step = pd.Timedelta(minutes=15 if resolution == "minutely_15" else 60)
        if (
            index.has_duplicates
            or not index.is_monotonic_increasing
            or not all(index[1:] - index[:-1] == step)
        ):
            raise ValueError
        values = {}
        selected_units = {}
        for column in columns:
            # Single-model JSON can use unsuffixed keys; normalize to explicit
            # model names so downstream comparisons do not lose provenance.
            key = column
            if key not in block and models and "," not in models:
                key = column.removesuffix("_" + models)
            raw = block[key]
            if not isinstance(raw, list) or len(raw) != len(index):
                raise ValueError
            if any(
                v is not None
                and (not isinstance(v, (int, float)) or not math.isfinite(v))
                for v in raw
            ):
                raise ValueError
            values[column] = raw
            if not isinstance(units[key], str):
                raise ValueError
            selected_units[column] = units[key]
        frame = pd.DataFrame(values, index=index, dtype=float)
        frame.index.name = "valid_time_utc"
        metadata = {
            "provider": "Open-Meteo",
            "source": ENDPOINTS[mode],
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "resolution": resolution,
            "models": models or "best_match",
            "run_initialization_utc": run,
            "previous_day_offset": previous_days if mode == "previous-runs" else None,
            "units": selected_units,
            "attribution": "Weather data by Open-Meteo (CC BY 4.0).",
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        raise WeatherError(
            "Open-Meteo returned an unexpected weather schema."
        ) from None
    return frame, metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=ENDPOINTS, default="forecast")
    parser.add_argument(
        "--resolution", choices=("hourly", "minutely_15"), default="hourly"
    )
    parser.add_argument("--models")
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument("--run", help="Model initialization in UTC, YYYY-MM-DDTHH:MM")
    parser.add_argument("--previous-days", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        latitude = float(os.environ["OPEN_METEO_LATITUDE"])
        longitude = float(os.environ["OPEN_METEO_LONGITUDE"])
    except (KeyError, ValueError):
        parser.exit(
            2, "Set numeric OPEN_METEO_LATITUDE and OPEN_METEO_LONGITUDE locally.\n"
        )
    try:
        frame, metadata = fetch_weather(
            latitude=latitude,
            longitude=longitude,
            mode=args.mode,
            resolution=args.resolution,
            models=args.models,
            days=args.days,
            run=args.run,
            previous_days=args.previous_days,
        )
    except WeatherError as error:
        parser.exit(2, str(error) + "\n")
    destination = Path("output/open-meteo")
    destination.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination / "weather.csv")
    (destination / "provenance.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Saved {len(frame)} weather rows under ignored output/open-meteo/. Keep these files local."
    )


if __name__ == "__main__":
    main()
