"""Fixed candidate models, validation-only selection and an empirical error band."""

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .features import make_samples, chronological_partitions

FEATURES = [
    "observed_now",
    "lag_1",
    "lag_4",
    "lag_96",
    "recent_mean",
    "daily_reference",
    "hour_sin",
    "hour_cos",
]


def metrics(actual, predicted):
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(
        predicted, dtype=float
    )
    if actual.ndim != 1 or actual.size == 0 or actual.shape != predicted.shape:
        raise ValueError("Expected nonempty paired vectors")
    if not np.all(np.isfinite(actual)) or not np.all(np.isfinite(predicted)):
        raise ValueError("Metrics require finite values")
    error = predicted - actual
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "bias": float(np.mean(error)),
        "samples": len(actual),
    }


def residual_radius(actual, predicted, coverage=0.90):
    if not 0 < coverage < 1:
        raise ValueError("Coverage must be between zero and one")
    metrics(actual, predicted)
    residuals = np.sort(np.abs(np.asarray(actual) - np.asarray(predicted)))
    rank = int(np.ceil((len(residuals) + 1) * coverage))
    if rank > len(residuals):
        raise ValueError("Calibration sample is too small for the requested coverage")
    return float(residuals[rank - 1])


def _predict(name, model, frame):
    if name == "persistence":
        prediction = frame.observed_now.to_numpy()
    elif name == "daily_persistence":
        prediction = frame.daily_reference.to_numpy()
    else:
        prediction = model.predict(frame[FEATURES])
    return np.clip(prediction, 0, 1)


def run_study(series, horizon=4, seed=42):
    samples = make_samples(series, horizon)
    parts = chronological_partitions(samples)
    train, validation, calibration, test = [
        parts[name] for name in ["train", "validation", "calibration", "test"]
    ]
    candidates = {"persistence": None, "daily_persistence": None}
    for alpha in [0.1, 1.0, 10.0]:
        candidates[f"ridge_{alpha:g}"] = make_pipeline(
            StandardScaler(), Ridge(alpha=alpha)
        )
    candidates["gradient_boosting"] = HistGradientBoostingRegressor(
        max_iter=100,
        max_leaf_nodes=15,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=seed,
    )
    comparison = []
    for name, model in candidates.items():
        if model is not None:
            model.fit(train[FEATURES], train.target)
        scores = metrics(validation.target, _predict(name, model, validation))
        comparison.append({"model": name, **scores})
    comparison.sort(key=lambda row: (row["mae"], row["model"]))
    chosen = comparison[0]["model"]
    model = candidates[chosen]
    # Model and hyperparameters are frozen before calibration or holdout outcomes are used.
    radius = residual_radius(calibration.target, _predict(chosen, model, calibration))
    predictions = _predict(chosen, model, test)
    lower, upper = np.clip(predictions - radius, 0, 1), np.clip(
        predictions + radius, 0, 1
    )
    actual = test.target.to_numpy()
    selected_metrics = metrics(actual, predictions)
    baseline_metrics = {
        name: metrics(actual, _predict(name, None, test))
        for name in ["persistence", "daily_persistence"]
    }
    baseline_mae = min(row["mae"] for row in baseline_metrics.values())
    active = (test.target_time.dt.hour >= 6) & (test.target_time.dt.hour < 18)
    report = {
        "horizon_steps": horizon,
        "horizon_minutes": horizon * 15,
        "selected_model": chosen,
        "validation_comparison": comparison,
        "holdout": selected_metrics,
        "baselines": baseline_metrics,
        "holdout_skill_vs_best_baseline": (
            1 - selected_metrics["mae"] / baseline_mae if baseline_mae else None
        ),
        "holdout_synthetic_active_period": metrics(actual[active], predictions[active]),
        "interval": {
            "nominal_coverage": 0.90,
            "residual_radius": radius,
            "observed_coverage": float(np.mean((actual >= lower) & (actual <= upper))),
            "mean_width": float(np.mean(upper - lower)),
            "interpretation": "Empirical residual band; temporal dependence prevents a distribution-free coverage claim.",
        },
        "partitions": {
            name: {
                "rows": len(frame),
                "first_issue": frame.index[0].isoformat(),
                "last_issue": frame.index[-1].isoformat(),
                "last_target": frame.target_time.iloc[-1].isoformat(),
            }
            for name, frame in parts.items()
        },
    }
    forecast = test[["target_time", "target"]].copy()
    forecast["prediction"] = predictions
    forecast["lower"] = lower
    forecast["upper"] = upper
    forecast["persistence"] = test.observed_now
    return report, forecast
