"""At issue time t, only observations at or before t are available."""

import numpy as np
import pandas as pd
from .data import validate_series


def make_samples(series, horizon=4):
    validate_series(series)
    if (
        isinstance(horizon, bool)
        or not isinstance(horizon, int)
        or not 1 <= horizon <= 96
    ):
        raise ValueError("Horizon must be an integer from 1 to 96 steps")
    target_index = series.index + pd.Timedelta(minutes=15 * horizon)
    hour = target_index.hour + target_index.minute / 60
    frame = pd.DataFrame(
        {
            "observed_now": series,
            "lag_1": series.shift(1),
            "lag_4": series.shift(4),
            "lag_96": series.shift(96),
            "recent_mean": series.rolling(4, min_periods=4).mean(),
            "daily_reference": series.shift(96 - horizon),
            "hour_sin": np.sin(2 * np.pi * hour / 24),
            "hour_cos": np.cos(2 * np.pi * hour / 24),
            "target": series.shift(-horizon),
            "target_time": target_index,
        },
        index=series.index,
    ).dropna()
    return frame


def chronological_partitions(samples):
    """60/15/10/15 nominal blocks; purge labels crossing the next issue boundary."""
    n = len(samples)
    if n < 400:
        raise ValueError("Need at least 400 valid forecast samples")
    cuts = [0, int(n * 0.60), int(n * 0.75), int(n * 0.85), n]
    names = ["train", "validation", "calibration", "test"]
    result = {}
    for i, name in enumerate(names):
        block = samples.iloc[cuts[i] : cuts[i + 1]]
        if i < 3:
            boundary = samples.index[cuts[i + 1]]
            block = block.loc[block.target_time < boundary]
        if len(block) < 50:
            raise ValueError("Each partition needs at least 50 samples after purging")
        result[name] = block
    return result
