"""Generate a fictional normalized signal, without a physical site model."""

import numpy as np
import pandas as pd


def synthetic_series(days=120, seed=42):
    if isinstance(days, bool) or not isinstance(days, int) or days < 30:
        raise ValueError("Use an integer of at least 30 days")
    rng = np.random.default_rng(seed)
    index = pd.date_range("2050-01-01", periods=days * 96, freq="15min", tz="UTC")
    step = np.arange(len(index))
    hour = (step % 96) / 4
    envelope = np.where(
        (hour > 6) & (hour < 18), np.sin(np.pi * (hour - 6) / 12), 0.0
    )
    weather = np.empty(len(index))
    weather[0] = 0.75
    for i in range(1, len(index)):
        weather[i] = np.clip(
            0.98 * weather[i - 1] + 0.02 * 0.75 + rng.normal(0, 0.025), 0.25, 1.0
        )
    noise = rng.normal(0, 0.012, len(index))
    power = np.where(envelope > 0, np.clip(envelope * weather + noise, 0, 1), 0)
    return pd.Series(power, index=index, name="power_pu")


def validate_series(series):
    if not isinstance(series, pd.Series) or not isinstance(
        series.index, pd.DatetimeIndex
    ):
        raise ValueError("Expected a series indexed by timestamps")
    if len(series) < 200 or series.index.tz is None:
        raise ValueError("Need at least 200 timezone-aware samples")
    if (
        series.index.hasnans
        or series.index.has_duplicates
        or not series.index.is_monotonic_increasing
    ):
        raise ValueError("Timestamps must be unique and increasing")
    if not np.all(np.diff(series.index.asi8) == pd.Timedelta(minutes=15).value):
        raise ValueError("Expected a complete regular 15-minute grid")
    values = np.asarray(series, dtype=float)
    if not np.all(np.isfinite(values)) or np.any((values < 0) | (values > 1)):
        raise ValueError("Normalized power must be finite and in [0,1]")
