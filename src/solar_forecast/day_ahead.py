"""Offline daily multi-output forecasting and weather-variance ablation."""

import argparse
import importlib.metadata
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .ensemble import weather_summaries
from .study import metrics, residual_radius

MODELS = ("model_a", "model_b", "model_c", "model_d")
WEATHER = ("shortwave_radiation", "temperature_2m")


def synthetic_weather(days=180, seed=42):
    """Invent power and imperfect forecast members; never call a weather API.

    The envelope is an educational stand-in, not a physical clear-sky model.
    Forecasts share a latent weather scenario with noisy subsequent observations.
    Every member is assumed available at the start of its target UTC day.
    """
    if not isinstance(days, int) or days < 80:
        raise ValueError("At least 80 complete synthetic days are required")
    rng = np.random.default_rng(seed)
    index = pd.date_range("2050-01-01", periods=days * 96, freq="15min", tz="UTC")
    hour = index.hour.to_numpy() + index.minute.to_numpy() / 60
    envelope = np.maximum(0, np.sin(np.pi * (hour - 6) / 12))
    envelope[(hour <= 6) | (hour >= 18)] = 0
    cloud = rng.uniform(0.25, 0.95, days).repeat(96)
    variation = np.convolve(
        rng.normal(0, 0.06, len(index) + 8), np.ones(9) / 9, mode="valid"
    )
    transmission = np.clip(cloud + variation, 0.1, 1)
    difficulty = rng.uniform(0.03, 0.22, days).repeat(96)
    shared_error = rng.normal(0, 0.05, days).repeat(96)
    temperature = (
        15 + 6 * np.sin(2 * np.pi * (hour - 8) / 24) + rng.normal(0, 1, days).repeat(96)
    )
    frame = pd.DataFrame(
        {
            "envelope": envelope,
            "power": envelope
            * np.clip(transmission + rng.normal(0, 0.025, len(index)), 0, 1),
        },
        index=index,
    )
    for model in MODELS:
        member_error = rng.normal(0, 1, days).repeat(96) * difficulty
        frame[f"shortwave_radiation_{model}"] = (
            1000 * envelope * np.clip(transmission + shared_error + member_error, 0, 1)
        )
        frame[f"temperature_2m_{model}"] = temperature + rng.normal(
            0, 1.5, days
        ).repeat(96)
    frame.index.name = "valid_time_utc"
    return frame


def daily_samples(frame):
    """Build calendar-day examples; observations from the target day are labels only."""
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("Use a timezone-aware UTC timestamp index")
    if (
        str(frame.index.tz) != "UTC"
        or frame.index.has_duplicates
        or not frame.index.is_monotonic_increasing
    ):
        raise ValueError("Use unique ordered UTC timestamps")
    if frame.empty or frame.index[0] != frame.index[0].normalize() or len(frame) % 96:
        raise ValueError("Use complete UTC calendar days")
    if not np.all(frame.index[1:] - frame.index[:-1] == pd.Timedelta(minutes=15)):
        raise ValueError("Use a complete 15-minute grid")
    values = frame[["power", "envelope"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
        raise ValueError("Power and toy envelope must be finite per-unit values")
    if np.any(frame.power > frame.envelope + 1e-12):
        raise ValueError("Toy power cannot exceed the toy clear-sky envelope")
    envelope = frame.envelope.to_numpy().reshape(-1, 96)
    power = frame.power.to_numpy().reshape(-1, 96)
    index_power = np.divide(
        power, envelope, out=np.zeros_like(power), where=envelope > 0
    )
    summaries = weather_summaries(frame, MODELS, WEATHER)
    means = summaries[[v + "_mean" for v in WEATHER]].to_numpy().reshape(-1, 192)
    spread = summaries[[v + "_variance" for v in WEATHER]].to_numpy().reshape(-1, 192)
    # At midnight D, D-1 and D-7 are observed; all D weather members are assumed issued.
    base = np.concatenate([index_power[6:-1], index_power[:-7], means[7:]], axis=1)
    return {
        "issued_at": frame.index[::96][7:],
        "means_only": base,
        "means_plus_variance": np.concatenate([base, spread[7:]], axis=1),
        "target_index": index_power[7:],
        "envelope": envelope[7:],
        "actual": power[7:],
        "persistence": np.clip(index_power[6:-1], 0, 1) * envelope[7:],
        "weekly_persistence": np.clip(index_power[:-7], 0, 1) * envelope[7:],
    }


def daily_partitions(count):
    """60/20/20 train/calibration/test with one unused day at each boundary."""
    if count < 70:
        raise ValueError("Not enough daily samples")
    a, b = int(count * 0.6), int(count * 0.8)
    return {
        "train": np.arange(a - 1),
        "calibration": np.arange(a, b - 1),
        "test": np.arange(b, count),
    }


def tune_daily(x, target_index, envelope):
    """Select regularization using training-only forward folds and power MAE."""
    scores = []
    folds = list(TimeSeriesSplit(n_splits=3, gap=1).split(x))
    for alpha in (0.1, 10.0, 1000.0):
        errors = []
        for train, validation in folds:
            pipeline = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
            pipeline.fit(x[train], target_index[train])
            predicted = (
                np.clip(pipeline.predict(x[validation]), 0, 1) * envelope[validation]
            )
            errors.append(
                metrics(
                    (target_index[validation] * envelope[validation]).ravel(),
                    predicted.ravel(),
                )["mae"]
            )
        scores.append({"alpha": alpha, "mean_fold_mae": float(np.mean(errors))})
    chosen = min(scores, key=lambda row: (row["mean_fold_mae"], row["alpha"]))["alpha"]
    fitted = make_pipeline(StandardScaler(), Ridge(alpha=chosen))
    fitted.fit(x, target_index)
    return fitted, chosen, scores


def evaluate_daily(samples):
    parts = daily_partitions(len(samples["issued_at"]))
    train, calibration, test = (parts[k] for k in ("train", "calibration", "test"))
    report = {
        "dataset": "synthetic",
        "forecast_steps": 96,
        "step_minutes": 15,
        "issue_time": "UTC midnight, with toy observations available immediately",
        "partitions": {
            k: {
                "days": len(v),
                "first_issue": samples["issued_at"][v[0]].isoformat(),
                "last_issue": samples["issued_at"][v[-1]].isoformat(),
            }
            for k, v in parts.items()
        },
        "variants": {},
    }
    forecasts = {}
    actual = samples["actual"][test]
    envelope = samples["envelope"]
    for name in ("means_only", "means_plus_variance"):
        model, alpha, scores = tune_daily(
            samples[name][train], samples["target_index"][train], envelope[train]
        )
        calibration_prediction = (
            np.clip(model.predict(samples[name][calibration]), 0, 1)
            * envelope[calibration]
        )
        prediction = np.clip(model.predict(samples[name][test]), 0, 1) * envelope[test]
        # One maximum-error score per day; evaluates simultaneous full-day bands.
        daily_errors = np.max(
            np.abs(samples["actual"][calibration] - calibration_prediction), axis=1
        )
        radius = residual_radius(
            daily_errors, np.zeros_like(daily_errors), coverage=0.90
        )
        lower = np.maximum(0, prediction - radius)
        upper = np.minimum(envelope[test], prediction + radius)
        covered = (actual >= lower) & (actual <= upper)
        active = envelope[test] > 0
        report["variants"][name] = {
            "alpha": alpha,
            "training_cv": scores,
            "holdout": metrics(actual.ravel(), prediction.ravel()),
            "holdout_active": metrics(actual[active], prediction[active]),
            "interval": {
                "nominal_daily_coverage": 0.90,
                "radius": radius,
                "observed_daily_coverage": float(covered.all(axis=1).mean()),
                "observed_pointwise_coverage": float(covered.mean()),
                "mean_width": float(np.mean(upper - lower)),
                "interpretation": "Empirical daily maximum-error band; temporal dependence prevents a coverage guarantee.",
            },
        }
        forecasts[name] = (prediction, lower, upper)
    report["baselines"] = {
        name: metrics(actual.ravel(), samples[name][test].ravel())
        for name in ("persistence", "weekly_persistence")
    }
    reference = report["variants"]["means_only"]["holdout"]["mae"]
    report["variance_ablation_mae_reduction"] = (
        reference - report["variants"]["means_plus_variance"]["holdout"]["mae"]
    )
    report["variance_ablation_interpretation"] = (
        "Positive reduction favors variance on this fixed synthetic holdout; no real-world benefit is asserted."
    )
    records = []
    for day, sample in enumerate(test):
        for step in range(96):
            row = {
                "issued_at_utc": samples["issued_at"][sample],
                "valid_time_utc": samples["issued_at"][sample]
                + pd.Timedelta(minutes=15 * step),
                "actual": actual[day, step],
            }
            for name, (pred, low, high) in forecasts.items():
                row.update(
                    {
                        name: pred[day, step],
                        name + "_lower": low[day, step],
                        name + "_upper": high[day, step],
                    }
                )
            records.append(row)
    return report, pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    frame = synthetic_weather(args.days, args.seed)
    report, forecasts = evaluate_daily(daily_samples(frame))
    report.update(
        {
            "seed": args.seed,
            "synthetic_days": args.days,
            "versions": {
                name: importlib.metadata.version(name)
                for name in ("numpy", "pandas", "scikit-learn")
            },
        }
    )
    destination = Path("output/day-ahead")
    destination.mkdir(parents=True, exist_ok=True)
    forecasts.to_csv(destination / "forecast.csv", index=False)
    (destination / "metrics.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    preview = forecasts.iloc[:192]
    fig, ax = plt.subplots(figsize=(11, 4), layout="constrained")
    ax.fill_between(
        preview.valid_time_utc,
        preview.means_plus_variance_lower,
        preview.means_plus_variance_upper,
        alpha=0.3,
        label="Empirical daily band",
    )
    ax.plot(
        preview.valid_time_utc, preview.actual, color="black", label="Synthetic power"
    )
    ax.plot(preview.valid_time_utc, preview.means_only, label="Weather means")
    ax.plot(
        preview.valid_time_utc,
        preview.means_plus_variance,
        label="Weather means + variance",
    )
    ax.set(
        title="Synthetic 96-step daily forecasting: weather variance ablation",
        ylabel="Power (p.u.)",
        xlabel="UTC valid time",
    )
    ax.legend(ncol=2)
    fig.savefig(destination / "day-ahead.png", dpi=160)
    plt.close(fig)
    print(
        json.dumps(
            {
                "variants": report["variants"],
                "baselines": report["baselines"],
                "variance_ablation_mae_reduction": report[
                    "variance_ablation_mae_reduction"
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
