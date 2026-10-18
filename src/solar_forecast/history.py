"""Historical weather verification with an excluded forecast comparator."""

import argparse
import importlib.metadata
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .ensemble import weather_summaries
from .open_meteo import VARIABLES, WeatherError, fetch_weather
from .study import metrics

INPUT_MODELS = ("icon_eu", "ecmwf_ifs025", "meteofrance_arpege_europe", "gem_global")
THREE_MODEL_INPUTS = INPUT_MODELS[:3]
COMPARATOR = "gfs_global"
TARGETS = ("shortwave_radiation", "temperature_2m")


def acquire_history(
    *,
    latitude,
    longitude,
    start_date,
    end_date,
    input_models=INPUT_MODELS,
    fetcher=fetch_weather,
):
    """Fetch equal-offset forecasts and explicit ERA5; strip metadata via adapter."""
    if (
        len(input_models) not in (3, 4)
        or len(set(input_models)) != len(input_models)
        or COMPARATOR in input_models
        or "era5" in input_models
    ):
        raise ValueError(
            "Choose three or four distinct input models excluding GFS and ERA5"
        )
    common = dict(
        latitude=latitude, longitude=longitude, start_date=start_date, end_date=end_date
    )
    weather, forecast_meta = fetcher(
        **common,
        mode="previous-runs",
        previous_days=1,
        models=",".join((*input_models, COMPARATOR)),
    )
    reference, reference_meta = fetcher(
        **common, mode="historical-weather", models="era5"
    )
    if not weather.index.equals(reference.index):
        raise WeatherError("Forecast and reanalysis grids do not match.")
    for variable in VARIABLES:
        ref_unit = reference_meta["units"][variable + "_era5"]
        for model in (*input_models, COMPARATOR):
            if forecast_meta["units"][f"{variable}_previous_day1_{model}"] != ref_unit:
                raise WeatherError("Forecast and reanalysis units do not match.")
    weather = weather.rename(
        columns={c: c.replace("_previous_day1_", "_") for c in weather}
    )
    frame = weather.join(reference)
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise WeatherError(
            "Historical benchmark requires complete finite data; missing members are not imputed."
        )
    return frame, {"forecast": forecast_meta, "verification": reference_meta}


def weather_features(frame, input_models=INPUT_MODELS, comparator=COMPARATOR):
    """Build predictors only from the declared input models, never reference fields."""
    if comparator in input_models or comparator == "era5" or "era5" in input_models:
        raise ValueError(
            "Input models, comparator and verification reference must be distinct"
        )
    if len(input_models) not in (3, 4) or len(set(input_models)) != len(input_models):
        raise ValueError(
            "Historical studies require three or four distinct input weather models"
        )
    if not isinstance(frame.index, pd.DatetimeIndex) or str(frame.index.tz) != "UTC":
        raise ValueError("Use a UTC weather index")
    if not np.all(frame.index[1:] - frame.index[:-1] == pd.Timedelta(hours=1)):
        raise ValueError("Use a complete hourly grid")
    summary = weather_summaries(frame, input_models, VARIABLES)
    clock = pd.DataFrame(
        {
            "hour_sin": np.sin(2 * np.pi * frame.index.hour / 24),
            "hour_cos": np.cos(2 * np.pi * frame.index.hour / 24),
        },
        index=frame.index,
    )
    means = summary[[v + "_mean" for v in VARIABLES]]
    return {
        "means_only": means.join(clock),
        "means_plus_variance": means.join(
            summary[[v + "_variance" for v in VARIABLES]]
        ).join(clock),
    }


def historical_partitions(index):
    if len(index) < 24 * 60:
        raise ValueError("Use at least 60 days for a historical benchmark")
    a, b = (int(len(index) * ratio) // 24 * 24 for ratio in (0.6, 0.8))
    return {
        "train": np.arange(a - 24),
        "validation": np.arange(a, b - 24),
        "test": np.arange(b, len(index)),
    }


def _physical(prediction, variable):
    return (
        np.maximum(0, prediction) if variable == "shortwave_radiation" else prediction
    )


def candidate_models():
    """Fixed estimator menu shared by within-year and year-to-year protocols."""
    models = {
        f"ridge_{alpha:g}": make_pipeline(StandardScaler(), Ridge(alpha=alpha))
        for alpha in (0.1, 10.0, 1000.0)
    }
    models["gradient_boosting"] = HistGradientBoostingRegressor(
        max_iter=100,
        max_leaf_nodes=15,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=42,
    )
    return models


def evaluate_history(frame, partitions=None, input_models=INPUT_MODELS):
    """Tune using earlier ERA5 targets; GFS appears only in final comparator scores.

    This measures weather error relative to reanalysis, not measured PV error.
    Previous-day offsets are provider-defined, not an exact publication-time ledger.
    """
    features = weather_features(frame, input_models)
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError("Historical benchmark requires finite weather values")
    parts = historical_partitions(frame.index) if partitions is None else partitions
    previous_end = -1
    for name in ("train", "validation", "test"):
        positions = np.asarray(parts[name])
        if (
            positions.ndim != 1
            or not len(positions)
            or not np.issubdtype(positions.dtype, np.integer)
        ):
            raise ValueError("Partitions require nonempty integer index vectors")
        if (
            positions[0] <= previous_end
            or positions[-1] >= len(frame)
            or not np.all(np.diff(positions) == 1)
        ):
            raise ValueError("Partitions must be ordered, contiguous and disjoint")
        previous_end = positions[-1]
    train, validation, test = (parts[k] for k in ("train", "validation", "test"))
    report = {
        "task": "historical weather verification, not PV-power validation",
        "verification_reference": "ERA5 reanalysis; not station observations",
        "input_models": list(input_models),
        "variance_definition": "Sample variance across all declared input models, ddof=1; squared physical units",
        "excluded_comparator": COMPARATOR,
        "forecast_offset_days": 1,
        "variables": {},
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "scikit-learn")
        },
        "partitions": {
            k: {
                "hours": len(v),
                "first_valid_time": frame.index[v[0]].isoformat(),
                "last_valid_time": frame.index[v[-1]].isoformat(),
            }
            for k, v in parts.items()
        },
    }
    forecasts = pd.DataFrame(index=frame.index[test])
    for variable in TARGETS:
        actual = frame[variable + "_era5"].to_numpy()
        scores = {}
        for model in (*input_models, COMPARATOR):
            scores[model] = metrics(
                actual[test], frame[variable + "_" + model].iloc[test].to_numpy()
            )
            forecasts[variable + "_" + model] = frame[variable + "_" + model].iloc[test]
        mean = frame[[variable + "_" + m for m in input_models]].mean(axis=1).to_numpy()
        scores["input_ensemble_mean"] = metrics(actual[test], mean[test])
        forecasts[variable + "_input_ensemble_mean"] = mean[test]
        forecasts[variable + "_era5"] = actual[test]
        forecasts[variable + "_" + COMPARATOR] = frame[
            variable + "_" + COMPARATOR
        ].iloc[test]
        selection = {}
        for variant, x in features.items():
            candidates = []
            for name, model in candidate_models().items():
                model.fit(x.iloc[train], actual[train])
                prediction = _physical(model.predict(x.iloc[validation]), variable)
                candidates.append(
                    (
                        metrics(actual[validation], prediction)["mae"],
                        name,
                        model,
                    )
                )
            _, chosen, fitted = min(
                candidates, key=lambda candidate: (candidate[0], candidate[1])
            )
            prediction = _physical(fitted.predict(x.iloc[test]), variable)
            scores[variant] = metrics(actual[test], prediction)
            forecasts[variable + "_" + variant] = prediction
            selection[variant] = {
                "model": chosen,
                "validation": [{"model": a, "mae": e} for e, a, _ in candidates],
            }
        report["variables"][variable] = {
            "unit": "W/m²" if variable == "shortwave_radiation" else "°C",
            "holdout": scores,
            "selection": selection,
            "variance_mae_reduction": scores["means_only"]["mae"]
            - scores["means_plus_variance"]["mae"],
        }
    report["interpretation"] = (
        "ERA5 is a model-based reanalysis. Lower error is agreement with ERA5, not demonstrated PV skill. The GFS comparator never enters inputs, fitting or model selection. Report all fixed comparisons without selecting a favorable reference."
    )
    return report, forecasts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    args = parser.parse_args()
    try:
        latitude = float(os.environ["OPEN_METEO_LATITUDE"])
        longitude = float(os.environ["OPEN_METEO_LONGITUDE"])
    except (KeyError, ValueError):
        parser.exit(2, "Set local numeric Open-Meteo location variables.\n")
    try:
        frame, provenance = acquire_history(
            latitude=latitude,
            longitude=longitude,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        report, predictions = evaluate_history(frame)
    except (WeatherError, ValueError) as error:
        parser.exit(2, str(error) + "\n")
    destination = Path("output/history")
    destination.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination / "weather.csv")
    predictions.to_csv(destination / "predictions.csv")
    (destination / "metrics.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (destination / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
