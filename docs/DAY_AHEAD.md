# Daily forecasting with weather-model disagreement

This independently implemented experiment demonstrates daily multi-output forecasting, clear-sky-style normalization and disagreement between numerical weather models. All data, model identifiers, figures and results in this experiment are fictional. It requires no location, credentials, files from another project or live service.

```bash
python -m solar_forecast.day_ahead --days 180 --seed 42
```

The command writes `forecast.csv`, `metrics.json` and `day-ahead.png` under ignored `output/day-ahead/`. The existing short-horizon experiment and optional Open-Meteo acquisition remain separate commands.

## Inputs and forecast origin

Each example is one complete UTC calendar day with 96 fifteen-minute targets. At midnight D, the toy system assumes the power profiles from D-1 and D-7 and all weather forecasts for D are available. The target begins at that midnight: this is a start-of-day full-day forecast, not a claim of a fixed 24-hour lead for every target. Observations are assumed delivered immediately; operational delays are not simulated.

Days are assembled from a strict UTC grid, never arbitrary blocks after dropping missing rows. Duplicate timestamps, gaps, partial days and invalid values are rejected. The model predicts 96 normalized power-index values jointly using multi-output Ridge regression. A deterministic, fixed daily envelope provides the normalization and inverse transform. The index is zero where the envelope is zero; predictions are clipped to [0, 1] before multiplication by the envelope.

**The envelope is a toy stand-in for clear-sky power, not a solar-position, irradiance or equipment model.** It assumes known per-unit support and a fixed fictional daylight window. The demonstration does not validate physical PV conversion or reproduce a real clear-sky installation.

## Ensemble features and ablation

`weather_summaries` in `ensemble.py` computes means, sample variances and standard deviations (`ddof=1`) and ranges for each variable across aligned model columns. For two members it also computes their absolute difference. Missing members/values are rejected rather than silently changing ensemble composition.

For two members, sample standard deviation is the absolute difference divided by the square root of two. These are related measures of disagreement, not independent uncertainty estimates. Model agreement can coexist with large shared bias.

The daily experiment has two predeclared variants:

| Variant | Predictors |
| --- | --- |
| `means_only` | D-1 and D-7 power-index profiles plus target-day mean radiation and temperature forecasts |
| `means_plus_variance` | The same predictors plus inter-model sample variance for both weather variables |

The four fictional weather members are generated from a shared latent weather scenario, with common errors and member-specific daily errors. Power observations add separate noise. This is a controlled statistical experiment, not a realistic weather simulator. The added variance features may improve or worsen performance; the report preserves either outcome. The comparison tests information beyond ensemble means, not beyond a model already containing all individual members.

In the committed four-member 180-day, seed-42 experiment, holdout MAE is **0.02929 p.u.** with weather means and **0.02991 p.u.** with means plus variance. Variance slightly worsens this toy example. Observed full-day band coverage is 80.0% and 74.3%, respectively, below the nominal 90%; this demonstrates that the empirical band is not a coverage guarantee. Exact scores, partitions and library versions are in [the generated report](results/day-ahead.json).

## Selection, calibration and holdout

The chronological daily examples are divided 60%/20%/20% into training, calibration and test, with one unused day before each boundary. Each variant independently selects Ridge alpha from {0.1, 10, 1000} using three expanding training-only folds with a one-day gap. Each scaler is fitted inside its fold's pipeline. Selection minimizes average fold power MAE after inverse transformation; the selected pipeline is then fitted on training only and frozen.

Both variants and previous-day/previous-week persistence baselines are evaluated on the same final holdout. There is no test-driven winner selection. Reports include all-hour and toy daylight errors, the signed MAE reduction from adding variance, tuning scores and period boundaries. Positive reduction favors variance only on this synthetic experiment.

For each frozen variant, each calibration day contributes its maximum absolute error across all 96 targets. The finite-sample 90% residual rank determines a symmetric band, clipped to the known toy envelope. Reports distinguish full-day simultaneous coverage from pointwise coverage. This is an empirical daily-error band; temporal dependence prevents an unconditional coverage guarantee. It is not the quantile-regression method and is not a calibrated interpretation of weather spread.

## Public weather reuse

The same summary function accepts [Open-Meteo adapter](OPEN_METEO.md) columns, for example:

```python
from solar_forecast.ensemble import weather_summaries

# weather is the adapter's DataFrame, with all requested members present.
features = weather_summaries(
    weather,
    models=("icon_global", "ecmwf_ifs025"),
    variables=("shortwave_radiation", "temperature_2m"),
)
```

This computes features; it does not train the synthetic model on live weather. Before any real forecasting study, align units, interval meanings, model availability and initialization/release times, and obtain an explicitly publishable power dataset. A valid-time join alone does not establish historical forecast availability. Downloaded weather and any derived site-specific outputs remain local.

## Scope and further work

Implemented here: ensemble summaries, daily multi-output forecasting, D-1/D-7 profiles, toy clear-sky-style normalization, training-only tuning, a variance ablation, daily empirical bands and persistence benchmarks. The simpler estimator keeps the public example reproducible without heavyweight optional runtimes.

Not implemented or claimed: the original operational models/results, physical clear-sky modeling, XGBoost/LSTM training, SHAP selection, quantile regression, or a dependence-aware significance test. This is a reproducible subset of general methods, not a reproduction of private results or a deployment-ready system.

Technical references: [scikit-learn chronological folds](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) and [preprocessing leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html). Source and generated public artifacts were written for this demonstration in October 2026.
