# Historical weather benchmark

This optional workflow downloads real archived numerical weather forecasts and ERA5 reanalysis. It evaluates **weather variables**, independently of the synthetic power experiments. No measured power dataset, source installation, coordinates or local historical results are committed.

## Run locally

Set `OPEN_METEO_LATITUDE` and `OPEN_METEO_LONGITUDE` in your local environment, as described in [Open-Meteo setup](OPEN_METEO.md), then run:

```bash
python -m solar_forecast.history --start-date 2025-01-01 --end-date 2025-12-31
```

Use 60–366 complete days, subject to provider/model archive availability. The command makes two requests, verifies matching UTC hourly grids and units, and rejects missing values rather than imputing them. A regional model must cover the selected location. Downloaded fields, predictions, scores and provider provenance are written only under ignored `output/history/`. The location must remain in private local configuration. No live requests run in CI.

## Fixed roles

| Source | Role | Used in fitting or model selection? |
| --- | --- | --- |
| ICON-EU and ECMWF IFS 0.25° | Forecast input variables | Yes, as predictors |
| ERA5 | Historical verification reference | Earlier periods supply training/validation labels; test labels supply final scores only |
| GFS Global | Excluded forecast comparator | No; only scored on the final test period |

GFS is distinct from the input models and never enters ensemble summaries, features, fitting or hyperparameter selection. All forecast sources use the provider's `_previous_day1` offset. ERA5 is explicitly selected, rather than the archive's blended default.

This comparison is **verification relative to reanalysis**, not measured ground truth. Forecast and reanalysis systems can share observations, forcing and modeling assumptions; a different model name does not establish statistical independence. Agreement with another forecast also does not establish PV skill. ERA5 is never used as an issue-time feature.

## Protocol

The requested period is divided chronologically into 60% training, 20% validation and 20% final testing, with 24 unused hours before each boundary. The complete expected hourly date range is checked before analysis.

For each of radiation and air temperature, two Ridge pipelines use weather means, or means plus inter-model standard deviations, across the input models. All three input weather variables (radiation, temperature and cloud cover) and known clock-hour sine/cosine are available as predictors. Scaling is fitted only on the training block. Alpha is selected from {0.1, 10, 1000} using earlier validation MAE, after which the fitted model is frozen. Negative predicted radiation is clipped to zero.

The same holdout scores both variants, both raw input models, their unweighted mean and the excluded GFS comparator. Reports retain every score, including cases where a simple baseline wins. Parameters, reference, model roles and metrics are fixed before examining the holdout. No favorable reference is selected afterwards.

Metrics are MAE, RMSE and signed bias in W/m² for shortwave radiation and °C for temperature. A lower radiation MAE can reflect nighttime zeros; inspect the hourly prediction export and daylight behavior before drawing operational conclusions. A single chronological holdout does not establish multi-season robustness, statistical significance or repeatability across sites. The benchmark does not calculate a confidence interval for score differences.

## Forecast availability and limitations

The Previous Runs API supplies provider-defined fixed lead-time offsets, not an exact ledger of individual forecast publication times. Shortwave radiation is an interval average, so comparisons use matched UTC valid times and the same hourly convention. For experiments requiring exact initialization and release-time availability, collect individual runs and apply provider publication delays explicitly.

ERA5 reanalysis incorporates observations retrospectively and is not an operationally available predictor at forecast time. The workflow learns a historical weather post-processing relation; its scores must not be presented as validation of the separate power forecaster or as commercial performance.

The source implements reproducible methods, while location-specific data and outputs remain local. Record your private location configuration together with the saved provenance to reproduce a local run. Provider datasets can be revised after retrieval; the local downloaded files preserve the actual inputs used for that run.

Weather attribution: [Open-Meteo](https://open-meteo.com/) (CC BY 4.0). Technical sources: [Previous Runs](https://open-meteo.com/en/docs/previous-runs-api), [Historical Weather / ERA5](https://open-meteo.com/en/docs/historical-weather-api), [Historical Forecast](https://open-meteo.com/en/docs/historical-forecast-api), [Single Runs](https://open-meteo.com/en/docs/single-runs-api). Respect current [provider usage terms](https://open-meteo.com/en/terms).
