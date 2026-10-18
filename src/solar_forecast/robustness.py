"""Retrospective rolling-origin evaluation and aggregate-only public reporting."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .history import (
    INPUT_MODELS,
    THREE_MODEL_INPUTS,
    TARGETS,
    evaluate_history,
    weather_features,
)
from .study import metrics

COMPARISONS = ("means_only", "input_ensemble_mean", "gfs_global")


def rolling_partitions(
    index, initial_days=120, validation_days=30, test_days=30, gap_days=7
):
    """Expanding training; earlier validation; disjoint full-day test windows."""
    if min(initial_days, validation_days, test_days, gap_days) < 1:
        raise ValueError("All rolling window settings must be positive")
    if len(index) % 24 or index[0] != index[0].normalize():
        raise ValueError("Rolling evaluation requires complete UTC days")
    count = len(index) // 24
    first = initial_days + validation_days + 2 * gap_days
    windows = []
    for start in range(first, count, test_days):
        end = min(start + test_days, count)
        # Keep partial final windows only if enough days for 14-day sensitivity.
        if end - start < 14:
            break
        validation_end = start - gap_days
        validation_start = validation_end - validation_days
        train_end = validation_start - gap_days
        windows.append(
            {
                "train": np.arange(train_end * 24),
                "validation": np.arange(validation_start * 24, validation_end * 24),
                "test": np.arange(start * 24, end * 24),
            }
        )
    if len(windows) < 2:
        raise ValueError("At least two rolling test windows are required")
    return windows


def paired_interval(fold_daily_differences, block_days=7, repetitions=2000, seed=42):
    """Percentile interval from circular day blocks, resampled within each fold.

    Each input is daily mean(abs(error_baseline)-abs(error_variance)); positive
    values favor variance. Keeping paired differences preserves forecast pairing.
    Fold-specific fitted pipelines remain fixed throughout resampling.
    """
    folds = [np.asarray(v, dtype=float) for v in fold_daily_differences]
    if (
        not folds
        or not isinstance(block_days, int)
        or block_days < 1
        or repetitions < 100
    ):
        raise ValueError("Use positive integer blocks and at least 100 replicates")
    if any(
        v.ndim != 1 or len(v) < block_days or not np.isfinite(v).all() for v in folds
    ):
        raise ValueError("Each finite daily-error vector must cover a whole block")
    rng = np.random.default_rng(seed)
    totals = np.zeros(repetitions)
    for values in folds:
        blocks = int(np.ceil(len(values) / block_days))
        starts = rng.integers(0, len(values), size=(repetitions, blocks))
        positions = (starts[:, :, None] + np.arange(block_days)) % len(values)
        positions = positions.reshape(repetitions, -1)[:, : len(values)]
        totals += values[positions].sum(axis=1)
    samples = totals / sum(map(len, folds))
    low, high = np.quantile(samples, [0.025, 0.975])
    return {
        "mean_mae_reduction": float(np.concatenate(folds).mean()),
        "lower_95": float(low),
        "upper_95": float(high),
        "block_days": block_days,
        "replicates": repetitions,
        "seed": seed,
        "test_days": sum(map(len, folds)),
    }


def aggregate_report(frame, repetitions=2000, input_models=INPUT_MODELS):
    """Construct only known aggregate fields, without copying downloaded metadata."""
    weather_features(frame, input_models)
    fixed, _ = evaluate_history(frame, input_models=input_models)
    windows = rolling_partitions(frame.index)
    reports, predictions = [], []
    for positions in windows:
        report, forecast = evaluate_history(frame, positions, input_models=input_models)
        reports.append(report)
        predictions.append(forecast)
    result = {
        "scope": "Historical numerical weather forecasts verified against ERA5 reanalysis; not measured PV validation",
        "data": {
            "year": int(frame.index[0].year),
            "hourly_rows": len(frame),
            "location": "User-configured location withheld from public artifacts",
            "raw_data": "Local only; no per-timestamp data or location values exported",
        },
        "protocol": {
            "status": "Retrospective exploratory analysis of an already inspected dataset; not new independent confirmation",
            "initial_training_days": 120,
            "validation_days": 30,
            "test_window_days": 30,
            "gap_days": 7,
            "primary_block_days": 7,
            "bootstrap_replicates": repetitions,
            "sensitivity_block_days": [1, 3, 7, 14],
            "bootstrap": "Paired circular day-block percentile intervals within each fold; fitted forecasts held fixed",
            "uncertainty_limits": "Approximate, marginal intervals; no multiple-comparison adjustment or refitting uncertainty; short within-fold dependence assumptions and artificial circular joins remain",
            "availability": "Seven-day gaps are a conservative allowance for reanalysis delivery; fixed forecast offsets do not establish exact operational release times",
        },
        "fixed_holdout": fixed,
        "rolling": {
            "folds": [
                {
                    "fold": i + 1,
                    "partitions": report["partitions"],
                    "variables": report["variables"],
                }
                for i, report in enumerate(reports)
            ],
            "variables": {},
        },
    }
    methods = tuple(
        (
            *input_models,
            "gfs_global",
            "input_ensemble_mean",
            "means_only",
            "means_plus_variance",
        )
    )
    result["methods"] = list(methods)
    combined = pd.concat(predictions)
    if combined.index.has_duplicates:
        raise ValueError("Rolling test windows must not overlap")
    for variable in TARGETS:
        actual = combined[variable + "_era5"].to_numpy()
        scores = {
            name: metrics(actual, combined[variable + "_" + name].to_numpy())
            for name in methods
        }
        active = (
            actual > 0
            if variable == "shortwave_radiation"
            else np.ones(len(actual), dtype=bool)
        )
        active_scores = (
            {
                name: metrics(
                    actual[active], combined[variable + "_" + name].to_numpy()[active]
                )
                for name in methods
            }
            if active.any()
            else {}
        )
        intervals = {}
        for baseline in COMPARISONS:
            fold_errors = []
            for forecast in predictions:
                target = forecast[variable + "_era5"].to_numpy()
                baseline_error = np.abs(
                    forecast[variable + "_" + baseline].to_numpy() - target
                )
                spread_error = np.abs(
                    forecast[variable + "_means_plus_variance"].to_numpy() - target
                )
                fold_errors.append(
                    (baseline_error - spread_error).reshape(-1, 24).mean(axis=1)
                )
            intervals[baseline] = {
                str(block): paired_interval(fold_errors, block, repetitions)
                for block in (1, 3, 7, 14)
            }
        result["rolling"]["variables"][variable] = {
            "unit": fixed["variables"][variable]["unit"],
            "pooled_test": scores,
            "positive_reference_hours_count": int(active.sum()),
            (
                "positive_reference_radiation_hours"
                if variable == "shortwave_radiation"
                else "all_hours"
            ): active_scores,
            "paired_mae_reduction_vs": intervals,
        }
    result["rolling"]["test_hours"] = len(combined)
    result["rolling"]["test_days"] = len(combined) // 24
    return result


def write_public_report(report, destination):
    """Export aggregate JSON, an English results page and a score/interval plot."""
    methods = report["methods"]
    destination = Path(destination)
    (destination / "results").mkdir(parents=True, exist_ok=True)
    (destination / "figures").mkdir(parents=True, exist_ok=True)
    (destination / "results/historical-robustness.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    text = [
        "# Historical weather results",
        "",
        "Real archived forecast data compared with ERA5 reanalysis. These are weather-variable scores, not measured PV-power accuracy. Location values, raw hourly data and original project material are excluded.",
        "",
        "**Four input models:** ICON-EU, ECMWF IFS 0.25°, ARPEGE Europe and GEM Global. The ML ablation adds explicit sample variance (`ddof=1`) across all four members. GFS is an excluded comparator, and ERA5 is the reference. The earlier two-model standard-deviation experiment is [archived separately](results/historical-two-model-legacy.json); its conclusions do not describe this revised study.",
        "",
        "## Design",
        "",
        f"The local dataset has {report['data']['hourly_rows']:,} hourly rows. Rolling evaluation covers {report['rolling']['test_days']} unique test days across {len(report['rolling']['folds'])} expanding windows. Each model uses earlier training and 30 validation days, with seven-day gaps before validation and testing. GFS never enters fitting or selection.",
        "",
        "This is a retrospective exploratory extension: this dataset and its original holdout had already been inspected. It is not a fresh independent confirmation. Protocol settings were fixed before running the new rolling analysis, without searching for a favorable block length or reference.",
        "",
        "## Pooled rolling scores",
        "",
        "| Method | Radiation MAE (W/m²) | Temperature MAE (°C) |",
        "| --- | ---: | ---: |",
    ]
    for method in methods:
        a, b = (
            report["rolling"]["variables"][v]["pooled_test"][method]["mae"]
            for v in TARGETS
        )
        text.append(f"| {method} | {a:.4f} | {b:.4f} |")
    text += [
        "",
        "## Paired differences and uncertainty",
        "",
        f"Positive reduction means lower MAE for `means_plus_variance`. Intervals below use {report['protocol']['bootstrap_replicates']:,} paired circular-block replicates of daily mean errors, with seven-day blocks resampled separately within each fold. Comparisons use exactly the same test hours.",
        "",
        "| Variable | Comparator | MAE reduction | Approximate 95% interval |",
        "| --- | --- | ---: | --- |",
    ]
    for variable in TARGETS:
        for baseline in COMPARISONS:
            row = report["rolling"]["variables"][variable]["paired_mae_reduction_vs"][
                baseline
            ]["7"]
            text.append(
                f"| {variable} | {baseline} | {row['mean_mae_reduction']:.4f} | [{row['lower_95']:.4f}, {row['upper_95']:.4f}] |"
            )
    if "three_model_sensitivity" in report:
        text += [
            "",
            "## Three-model versus four-model sensitivity",
            "",
            "The three-member subset (ICON-EU, ECMWF IFS and ARPEGE Europe) and four-member ensemble use the same complete dates, partitions, candidate models and reference. No model set is selected on test performance. The comparison adds GEM Global as a fourth forecast centre, but does not assume statistical independence between centres.",
            "",
            "| Variable | Three members: means MAE | Three members: variance MAE | Four members: means MAE | Four members: variance MAE |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for variable in TARGETS:
            three = report["three_model_sensitivity"]["variables"][variable][
                "pooled_test"
            ]
            four = report["rolling"]["variables"][variable]["pooled_test"]
            text.append(
                f"| {variable} | {three['means_only']['mae']:.4f} | {three['means_plus_variance']['mae']:.4f} | {four['means_only']['mae']:.4f} | {four['means_plus_variance']['mae']:.4f} |"
            )
    text += ["", "## Findings", ""]
    for variable in TARGETS:
        values = report["rolling"]["variables"][variable]
        row = values["paired_mae_reduction_vs"]["means_only"]["7"]
        conclusion = (
            "lower error with variance"
            if row["lower_95"] > 0
            else (
                "higher error with variance"
                if row["upper_95"] < 0
                else "no clear incremental benefit from variance"
            )
        )
        best = min(methods, key=lambda name: values["pooled_test"][name]["mae"])
        text += [
            f"For **{variable}**, the primary paired interval indicates **{conclusion}**. The lowest pooled MAE among the fixed methods is from `{best}`; this descriptive ranking does not select or refit a winner using test labels.",
            "",
        ]
    text += [
        "",
        "![Rolling weather scores and paired intervals](figures/historical-robustness.png)",
        "",
        "## Interpretation and limits",
        "",
        "An interval containing zero does not establish a consistent improvement under this approximation. An interval excluding zero is conditional evidence for this dataset/protocol, not proof of universal superiority. Intervals are marginal, without multiplicity adjustment, and do not include retraining uncertainty. Daily blocks account for some serial dependence, but dependence beyond the selected length and artificial circular joins remain limitations.",
        "",
        "The aggregate JSON includes 1-, 3-, 7- and 14-day block sensitivity, every fold, revised fixed-holdout results, units, versions, RMSE, bias, and radiation scores restricted to positive ERA5 radiation. Nighttime zeros can reduce all-hour radiation MAE. Earlier test outcomes may enter training in later rolling windows once historical, while each window remains strictly chronological.",
        "",
        "One location and one year limit generalization. ERA5 is a retrospective model-based reference, with shared meteorological inputs and assumptions; it is not independent station truth. Exact local reproduction requires the withheld local configuration and downloaded data. Raw weather must remain local. The synthetic power studies remain separate.",
        "",
        "[Aggregate results and sensitivity](results/historical-robustness.json) · [Historical protocol](HISTORICAL_BENCHMARK.md). Weather data by [Open-Meteo](https://open-meteo.com/) (CC BY 4.0); [ERA5 citation guidance](https://open-meteo.com/en/docs/historical-weather-api). Bootstrap background: [arch time-series bootstrap documentation](https://arch.readthedocs.io/en/stable/bootstrap/timeseries-bootstraps.html). The NumPy implementation here adds no bootstrap dependency.",
        "",
    ]
    (destination / "HISTORICAL_RESULTS.md").write_text(
        "\n".join(text), encoding="utf-8"
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    for col, variable in enumerate(TARGETS):
        data = report["rolling"]["variables"][variable]
        scores = [data["pooled_test"][name]["mae"] for name in methods]
        axes[0, col].barh(
            methods, scores, color=["#7393a7"] * (len(methods) - 1) + ["#cc853b"]
        )
        axes[0, col].invert_yaxis()
        axes[0, col].set(
            title=variable.replace("_", " "), xlabel="Pooled MAE (" + data["unit"] + ")"
        )
        for y, baseline in enumerate(COMPARISONS):
            row = data["paired_mae_reduction_vs"][baseline]["7"]
            axes[1, col].hlines(
                y, row["lower_95"], row["upper_95"], color="#406f8e", linewidth=3
            )
            axes[1, col].plot(row["mean_mae_reduction"], y, "o", color="#cc853b")
        axes[1, col].axvline(0, color="black", linewidth=0.8)
        axes[1, col].set(
            yticks=range(3),
            yticklabels=COMPARISONS,
            xlabel="MAE reduction from variance (" + data["unit"] + ")",
            title="Paired 95% intervals; seven-day blocks",
        )
    fig.suptitle(
        "Historical weather verification against ERA5 · retrospective rolling evaluation"
    )
    fig.savefig(destination / "figures/historical-robustness.png", dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=Path("output/history/weather.csv")
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Write aggregate report into docs/ after local data review",
    )
    parser.add_argument(
        "--compare-three",
        action="store_true",
        help="Also evaluate the fixed three-member subset on identical dates",
    )
    args = parser.parse_args()
    frame = pd.read_csv(args.input, index_col=0, parse_dates=True)
    report = aggregate_report(frame)
    if args.compare_three:
        three = aggregate_report(frame, input_models=THREE_MODEL_INPUTS)
        report["three_model_sensitivity"] = {
            "input_models": list(THREE_MODEL_INPUTS),
            "test_days": three["rolling"]["test_days"],
            "variables": three["rolling"]["variables"],
            "folds": three["rolling"]["folds"],
        }
    destination = Path("docs") if args.publish else Path("output/history-robustness")
    write_public_report(report, destination)
    print(
        f"Aggregate report saved to {destination}; no hourly data or location fields exported."
    )


if __name__ == "__main__":
    main()
