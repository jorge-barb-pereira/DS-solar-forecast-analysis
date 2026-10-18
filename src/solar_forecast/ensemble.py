"""Model disagreement summaries for aligned forecasts of the same variable."""

import numpy as np
import pandas as pd


def weather_summaries(frame, models, variables):
    """Summarize model columns without mixing physical quantities.

    Input names follow ``variable_model``. Require all members rather than
    silently comparing different ensembles when values are missing. The caller
    must align valid times, units and issue-time availability before using this.
    """
    models, variables = tuple(models), tuple(variables)
    if len(models) < 2 or len(set(models)) != len(models):
        raise ValueError("At least two distinct weather models are required")
    if not variables or len(set(variables)) != len(variables):
        raise ValueError("Select distinct weather variables")
    if (
        frame.empty
        or frame.index.has_duplicates
        or not frame.index.is_monotonic_increasing
    ):
        raise ValueError("Forecast rows must be nonempty, unique and ordered")
    result = pd.DataFrame(index=frame.index)
    for variable in variables:
        columns = [f"{variable}_{model}" for model in models]
        if not all(c in frame for c in columns):
            raise ValueError("A requested weather member is missing")
        values = frame[columns].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("Weather members must contain finite aligned values")
        result[f"{variable}_mean"] = values.mean(axis=1)
        result[f"{variable}_std"] = values.std(axis=1, ddof=1)
        result[f"{variable}_variance"] = values.var(axis=1, ddof=1)
        result[f"{variable}_range"] = np.ptp(values, axis=1)
        if len(models) == 2:
            result[f"{variable}_abs_difference"] = np.abs(values[:, 0] - values[:, 1])
    return result
