"""Select on a complete training year, refit on that year, freeze and test next year."""

import argparse
from datetime import date, timedelta
import importlib.metadata
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone

from .history import (
    TARGETS,
    _physical,
    candidate_models,
    weather_features,
)
from .open_meteo import VARIABLES, WeatherError, fetch_weather
from .robustness import paired_interval
from .study import metrics

INPUT_MODELS = ("icon_eu", "ecmwf_ifs025", "meteofrance_arpege_europe", "gfs_global")


def selection_folds(index):
    """Four expanding folds within the training year; seven-day label gaps."""
    count = len(index) // 24
    folds = []
    for train_days in (120, 180, 240, 300):
        start = train_days + 7
        end = min(start + 60, count)
        if end - start < 30:
            raise ValueError("A complete training year is required")
        folds.append((np.arange(train_days * 24), np.arange(start * 24, end * 24)))
    return folds


def validate_year(frame, year, complete=False):
    weather_features(frame, input_models=INPUT_MODELS, comparator=None)
    required = [
        f"{variable}_{model}"
        for variable in VARIABLES
        for model in (*INPUT_MODELS, "era5")
    ]
    if frame.empty or not np.isfinite(frame[required].to_numpy(dtype=float)).all():
        raise ValueError(
            "Yearly studies require complete finite weather and reference values"
        )
    first = pd.Timestamp(f"{year}-01-01", tz="UTC")
    last = (
        pd.Timestamp(f"{year+1}-01-01", tz="UTC")
        if complete
        else frame.index[-1].normalize() + pd.Timedelta(days=1)
    )
    expected = pd.date_range(first, last, freq="h", inclusive="left")
    if (
        len(frame) != len(expected)
        or not all(frame.index == expected)
        or not np.all(frame.index.year == year)
    ):
        raise ValueError(
            "Use the complete requested calendar year or an unbroken January-onward YTD period"
        )


def fit_training_year(frame, year=2025):
    """All choices depend on the complete training year only, never test inputs/labels."""
    validate_year(frame, year, complete=True)
    features = weather_features(frame, input_models=INPUT_MODELS, comparator=None)
    folds = selection_folds(frame.index)
    frozen, selection = {}, {}
    for variable in TARGETS:
        target = frame[variable + "_era5"].to_numpy()
        frozen[variable], selection[variable] = {}, {}
        for variant, x in features.items():
            scores = []
            for name, template in candidate_models().items():
                fold_scores, total_error, count = [], 0.0, 0
                for train, validation in folds:
                    model = clone(template)
                    model.fit(x.iloc[train], target[train])
                    predicted = _physical(model.predict(x.iloc[validation]), variable)
                    mae = metrics(target[validation], predicted)["mae"]
                    fold_scores.append(mae)
                    total_error += mae * len(validation)
                    count += len(validation)
                scores.append(
                    {
                        "model": name,
                        "weighted_validation_mae": total_error / count,
                        "fold_mae": fold_scores,
                    }
                )
            chosen = min(
                scores, key=lambda row: (row["weighted_validation_mae"], row["model"])
            )["model"]
            final = candidate_models()[chosen]
            final.fit(x, target)
            frozen[variable][variant] = final
            selection[variable][variant] = {
                "selected_model": chosen,
                "candidates": scores,
            }
    protocol = {
        "input_models": list(INPUT_MODELS),
        "training_year": year,
        "training_hours": len(frame),
        "first_training_time": frame.index[0].isoformat(),
        "last_training_time": frame.index[-1].isoformat(),
        "final_fit": "All training-year rows after training-year-only chronological selection",
        "selection": selection,
        "selection_folds": [
            {
                "train_hours": len(a),
                "last_train_time": frame.index[a[-1]].isoformat(),
                "first_validation_time": frame.index[b[0]].isoformat(),
                "last_validation_time": frame.index[b[-1]].isoformat(),
            }
            for a, b in folds
        ],
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "scikit-learn")
        },
    }
    return frozen, protocol


def available_prefix(forecasts, reference):
    """Remove only trailing incomplete whole days, never gaps within the study."""
    index = reference.index
    if (
        not isinstance(index, pd.DatetimeIndex)
        or str(index.tz) != "UTC"
        or reference.empty
        or not forecasts.index.equals(index)
        or len(index) % 24
        or index[0] != index[0].normalize()
        or not np.all(index[1:] - index[:-1] == pd.Timedelta(hours=1))
    ):
        raise ValueError("Expected aligned complete hourly calendar-day grids")
    joined = forecasts.join(reference)
    valid = (
        np.isfinite(joined.to_numpy(dtype=float))
        .all(axis=1)
        .reshape(-1, 24)
        .all(axis=1)
    )
    missing = np.flatnonzero(~valid)
    days = int(missing[0]) if len(missing) else len(valid)
    if not days or valid[days:].any():
        raise ValueError(
            "Incomplete leading or internal days cannot be silently removed"
        )
    return joined.iloc[: days * 24].copy(), len(valid) - days


def acquire_test_year(*, latitude, longitude, as_of, fetcher=fetch_weather):
    """Request yesterday at most, then determine the latest complete common day."""
    today = date.fromisoformat(as_of)
    start, requested_end = date(today.year, 1, 1), today - timedelta(days=1)
    if requested_end < start:
        raise ValueError("No completed test-year day is available yet")
    common = dict(
        latitude=latitude,
        longitude=longitude,
        start_date=start.isoformat(),
        end_date=requested_end.isoformat(),
    )
    forecast, fmeta = fetcher(
        **common,
        mode="previous-runs",
        previous_days=1,
        models=",".join(INPUT_MODELS),
    )
    reference, rmeta = fetcher(**common, mode="historical-weather", models="era5")
    for variable in VARIABLES:
        for model in INPUT_MODELS:
            if (
                fmeta["units"][f"{variable}_previous_day1_{model}"]
                != rmeta["units"][variable + "_era5"]
            ):
                raise WeatherError("Forecast/reference units do not match")
    forecast = forecast[
        [
            f"{variable}_previous_day1_{model}"
            for variable in VARIABLES
            for model in INPUT_MODELS
        ]
    ]
    reference = reference[[variable + "_era5" for variable in VARIABLES]]
    forecast = forecast.rename(
        columns={c: c.replace("_previous_day1_", "_") for c in forecast}
    )
    frame, excluded = available_prefix(forecast, reference)
    return frame, {
        "forecast": fmeta,
        "verification": rmeta,
        "as_of": as_of,
        "requested_end": requested_end.isoformat(),
        "latest_complete_day": frame.index[-1].date().isoformat(),
        "trailing_incomplete_days_excluded": excluded,
        "used_input_models": list(INPUT_MODELS),
    }


def evaluate_test_year(frozen, training_protocol, frame, repetitions=2000):
    if tuple(training_protocol["input_models"]) != INPUT_MODELS:
        raise ValueError("Frozen training and test input model identities must match")
    year = training_protocol["training_year"] + 1
    validate_year(frame, year)
    features = weather_features(frame, input_models=INPUT_MODELS, comparator=None)
    forecasts = pd.DataFrame(index=frame.index)
    methods = (
        *INPUT_MODELS,
        "input_ensemble_mean",
        "means_only",
        "means_plus_variance",
    )
    report = {
        "scope": "Frozen cross-year weather verification against ERA5, not observed PV validation",
        "training": training_protocol,
        "input_models": list(INPUT_MODELS),
        "excluded_comparator": None,
        "input_model_change": "The earlier within-2025 study uses GEM Global and excludes GFS. This cross-year study replaces GEM with GFS because GEM has internal 2026 archive gaps; JMA GSM also lacks required radiation. The choice used field completeness before test errors were examined. All 2025 fitting uses the same four members as 2026 prediction; earlier scores are not a controlled before/after comparison.",
        "test_year": year,
        "first_test_time": frame.index[0].isoformat(),
        "last_test_time": frame.index[-1].isoformat(),
        "test_hours": len(frame),
        "test_days": len(frame) // 24,
        "test_status": (
            "Complete calendar test year"
            if frame.index[-1]
            == pd.Timestamp(f"{year+1}-01-01", tz="UTC") - pd.Timedelta(hours=1)
            else "Year-to-date; not a complete test year"
        ),
        "inference": {
            "bootstrap_replicates": repetitions,
            "seed": 42,
            "primary_block_days": 7,
            "sensitivity_block_days": [1, 3, 7, 14],
            "minimum_test_days": 14,
        },
        "model_updates_during_test": False,
        "variables": {},
        "availability_note": "Calendar holdout starts January 1. Full previous-year ERA5 labels arrive with delay, so the separate January 8-onward subset is the availability-buffered evaluation. Neither reconstructs an exact operational release-time ledger.",
        "inference_note": "Paired circular daily-block intervals condition on frozen models, are marginal without multiplicity adjustment, and do not include selection/refitting uncertainty or guarantee validity under seasonal nonstationarity.",
    }
    buffered = frame.index >= pd.Timestamp(f"{year}-01-08", tz="UTC")
    for variable in TARGETS:
        actual = frame[variable + "_era5"].to_numpy()
        predictions = {m: frame[variable + "_" + m].to_numpy() for m in INPUT_MODELS}
        predictions["input_ensemble_mean"] = (
            frame[[variable + "_" + m for m in INPUT_MODELS]].mean(axis=1).to_numpy()
        )
        for variant, x in features.items():
            predictions[variant] = _physical(
                frozen[variable][variant].predict(x), variable
            )
        scores = {m: metrics(actual, predictions[m]) for m in methods}
        active = (
            actual > 0
            if variable == "shortwave_radiation"
            else np.ones(len(actual), dtype=bool)
        )
        intervals = {}
        if len(frame) // 24 >= 14:
            for baseline in ("means_only", "input_ensemble_mean", "gfs_global"):
                delta = (
                    (
                        np.abs(predictions[baseline] - actual)
                        - np.abs(predictions["means_plus_variance"] - actual)
                    )
                    .reshape(-1, 24)
                    .mean(axis=1)
                )
                intervals[baseline] = {
                    str(block): paired_interval([delta], block, repetitions)
                    for block in (1, 3, 7, 14)
                }
        monthly = {}
        for month in sorted(set(frame.index.strftime("%Y-%m"))):
            mask = frame.index.strftime("%Y-%m") == month
            monthly[month] = {
                "hours": int(mask.sum()),
                "scores": {
                    m: metrics(actual[mask], predictions[m][mask]) for m in methods
                },
            }
        report["variables"][variable] = {
            "unit": "W/m²" if variable == "shortwave_radiation" else "°C",
            "all_hours": scores,
            "positive_reference_hours_count": int(active.sum()),
            "positive_reference_hours": (
                {m: metrics(actual[active], predictions[m][active]) for m in methods}
                if active.any()
                else {}
            ),
            "availability_buffered": (
                {
                    m: metrics(actual[buffered], predictions[m][buffered])
                    for m in methods
                }
                if buffered.any()
                else {}
            ),
            "monthly": monthly,
            "paired_mae_reduction_vs": intervals,
        }
        forecasts[variable + "_era5"] = actual
        for m, predicted in predictions.items():
            forecasts[variable + "_" + m] = predicted
    return report, forecasts


def write_report(report, destination):
    """Export known aggregate scores and plots, no location or hourly values."""
    destination = Path(destination)
    (destination / "results").mkdir(parents=True, exist_ok=True)
    (destination / "figures").mkdir(parents=True, exist_ok=True)
    (destination / "results/yearly-2025-2026.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    methods = list(report["variables"][TARGETS[0]]["all_hours"])
    text = [
        f"# Train on {report['training']['training_year']}, test on {report['test_year']}",
        "",
        "Four-model mean/variance post-processing of archived weather forecasts, verified against ERA5 reanalysis. This is not measured PV-power validation. Location values and raw hourly inputs/predictions remain local.",
        "",
        f"Training uses all **{report['training']['training_hours']:,} hourly records from {report['training']['training_year']}**. Four expanding folds entirely within that year select each estimator, which is refitted on all training-year rows and frozen. No test-year labels enter selection, scaling or fitting.",
        "",
        f"The calendar holdout spans **{report['first_test_time'][:10]} to {report['last_test_time'][:10]}**, with **{report['test_days']} days / {report['test_hours']:,} hours**. Status: {report['test_status']}. The end date is the last complete day in the evaluated dataset; a supplied cache is not checked for newer provider data.",
        "",
        "Inputs are ICON-EU, ECMWF IFS 0.25°, ARPEGE Europe and GFS Global. Variance is computed independently at each valid hour across the four members (sample variance, ddof=1). GFS is an input member and is also scored as a raw-model baseline; ERA5 is the verification reference. The estimator menu is unchanged: three scaled Ridge alpha values and fixed histogram gradient boosting.",
        "",
        report["input_model_change"],
        "",
        f"## Frozen {report['test_year']} scores",
        "",
        "| Method | Radiation MAE (W/m²) | Temperature MAE (°C) |",
        "| --- | ---: | ---: |",
    ]
    for m in methods:
        a, b = (report["variables"][v]["all_hours"][m]["mae"] for v in TARGETS)
        text.append(f"| {m} | {a:.4f} | {b:.4f} |")
    text += [
        "",
        "## Paired differences",
        "",
        f"Positive MAE reduction favors the variance model. When at least 14 test days are available, approximate 95% intervals use {report['inference']['bootstrap_replicates']:,} paired circular daily-block replicates, seven-day blocks and seed {report['inference']['seed']}. The JSON also includes 1-, 3- and 14-day sensitivity. Shorter studies omit intervals. These are conditional, marginal intervals; seasonal nonstationarity and the artificial circular end-to-start join limit interpretation.",
        "",
        "| Variable | Comparator | MAE reduction | Approximate 95% interval |",
        "| --- | --- | ---: | --- |",
    ]
    for variable in TARGETS:
        for baseline, values in report["variables"][variable][
            "paired_mae_reduction_vs"
        ].items():
            row = values["7"]
            text.append(
                f"| {variable} | {baseline} | {row['mean_mae_reduction']:.4f} | [{row['lower_95']:.4f}, {row['upper_95']:.4f}] |"
            )
    text += [
        "",
        "![Frozen 2026 scores and monthly errors](figures/yearly-2025-2026.png)",
        "",
        "## Availability and interpretation",
        "",
        report["availability_note"],
        "",
        "The January 8-onward scores, monthly scores (with partial-month counts), positive-reference radiation scores, model choices, fold boundaries and package versions are in the aggregate JSON. ERA5 is retrospective and can be revised. Weather providers can change model versions between years; this is part of the cross-year generalization challenge, not evidence of a fixed model climate.",
        "",
        "The design uses only 2025 for development and does not adapt to 2026 outcomes. It remains a retrospective evaluation, not a prospectively registered deployment. One location, one training year and an incomplete test year limit generalization. Variance is a point-forecast predictor, not a calibrated uncertainty estimate.",
        "",
        "[Aggregate results](results/yearly-2025-2026.json) · [Study scope and endpoints](STUDY_SCOPE.md) · [Earlier within-2025 study](HISTORICAL_RESULTS.md). Weather data by [Open-Meteo](https://open-meteo.com/) (CC BY 4.0); [historical reference and attribution](https://open-meteo.com/en/docs/historical-weather-api).",
        "",
    ]
    (destination / "YEARLY_RESULTS.md").write_text("\n".join(text), encoding="utf-8")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    shown = ("input_ensemble_mean", "means_only", "means_plus_variance", "gfs_global")
    for col, variable in enumerate(TARGETS):
        values = report["variables"][variable]
        axes[0, col].barh(
            shown,
            [values["all_hours"][m]["mae"] for m in shown],
            color=["#7393a7", "#7393a7", "#cc853b", "#7393a7"],
        )
        axes[0, col].invert_yaxis()
        axes[0, col].set(
            title=variable.replace("_", " "), xlabel="YTD MAE (" + values["unit"] + ")"
        )
        months = list(values["monthly"])
        for method in shown[:3]:
            axes[1, col].plot(
                months,
                [values["monthly"][month]["scores"][method]["mae"] for month in months],
                marker="o",
                label=method,
            )
        axes[1, col].tick_params(axis="x", rotation=45)
        axes[1, col].set(
            ylabel="Monthly MAE (" + values["unit"] + ")",
            xlabel=f"{report['test_year']} month; latest month may be partial",
        )
        axes[1, col].legend(fontsize=8)
    fig.suptitle(
        f"Train: full {report['training']['training_year']} · Frozen test: {report['test_year']} · ERA5 reference"
    )
    fig.savefig(destination / "figures/yearly-2025-2026.png", dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--train-data", type=Path, default=Path("output/history/weather.csv")
    )
    parser.add_argument("--test-data", type=Path)
    parser.add_argument(
        "--as-of",
        required=True,
        help="YYYY-MM-DD snapshot date; requires the following test year",
    )
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    training = pd.read_csv(args.train_data, index_col=0, parse_dates=True)
    frozen, protocol = fit_training_year(training)
    if date.fromisoformat(args.as_of).year != 2026:
        parser.error("This protocol tests 2026")
    folder = Path("output/yearly")
    folder.mkdir(parents=True, exist_ok=True)
    if args.test_data:
        testing = pd.read_csv(args.test_data, index_col=0, parse_dates=True)
    else:
        try:
            testing, provenance = acquire_test_year(
                latitude=float(os.environ["OPEN_METEO_LATITUDE"]),
                longitude=float(os.environ["OPEN_METEO_LONGITUDE"]),
                as_of=args.as_of,
            )
        except (KeyError, ValueError, WeatherError) as error:
            parser.exit(
                2,
                "Historical acquisition failed; verify local settings and provider availability.\n",
            )
        testing.to_csv(folder / "weather-2026.csv")
        (folder / "provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )
    if testing.index[-1].date() >= date.fromisoformat(args.as_of):
        parser.error("Test data must end before the as-of snapshot date")
    report, predictions = evaluate_test_year(frozen, protocol, testing)
    report["as_of"] = args.as_of
    predictions.to_csv(folder / "predictions.csv")
    write_report(report, Path("docs") if args.publish else folder)
    print(
        f"Frozen 2025 models evaluated over {report['test_days']} complete 2026 days; aggregate report saved."
    )


if __name__ == "__main__":
    main()
