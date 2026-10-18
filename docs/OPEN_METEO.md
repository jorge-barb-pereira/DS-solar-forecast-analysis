# Optional Open-Meteo acquisition

The provider adapter retrieves public numerical weather forecasts independently of the synthetic power experiment. No site defaults, measured power targets or saved models are included. Tests use in-memory responses and make no network calls.

## Local configuration and execution

Set `OPEN_METEO_LATITUDE` and `OPEN_METEO_LONGITUDE` in your local process environment using your chosen location. No location values are included in this documentation. The command reads environment variables directly; it does not load `.env` files. Running it sends the chosen location to Open-Meteo. Request URLs and raw responses should remain private.

After installation, choose a workflow:

```bash
# Current forecast, hourly weather
python -m solar_forecast.open_meteo

# Compare explicitly selected weather models at 15-minute resolution
python -m solar_forecast.open_meteo --resolution minutely_15 --models icon_global,ecmwf_ifs025

# Forecast values at a fixed previous-day offset (hourly only)
python -m solar_forecast.open_meteo --mode previous-runs --previous-days 1

# One archived model initialization in UTC; choose a supported cycle/date
python -m solar_forecast.open_meteo --mode single-run --models icon_eu --run 2026-10-01T00:00
```

`--days` selects 1–16 forecast days (default 2), subject to the chosen model's horizon and archive availability. The default variables are air temperature, cloud cover and shortwave radiation. Model/variable combinations depend on provider support; unsupported requests fail with a redacted message. There are no automatic retries or background downloads. No subscription credentials are required by this free-endpoint adapter; it does not implement customer endpoints.

Regional models require a location within their domain. If a multi-model response omits a requested model or loses its model labels, acquisition fails rather than silently attributing weather to the wrong model.

Downloads overwrite `output/open-meteo/weather.csv` and `provenance.json`, both ignored by Git. Save distinct local copies when collecting successive runs. Only requested numeric weather fields and UTC valid times are exported. Echoed location, elevation and other response metadata are discarded. Provenance retains units, provider, retrieval time, mode, model selection and requested run initialization/day offset. Downloaded weather can still reveal location indirectly: keep it local and review any derived plots before publication. CI publishes only the separate synthetic experiment outputs.

## Scientific interpretation

- Current forecasts combine recent model runs; retrieval time does not identify each underlying model initialization.
- Previous Runs supplies fixed day-offset forecasts, rather than a complete individual model run.
- Single Runs identifies a UTC **initialization**, which precedes public availability. Account for model computation and publication delays before treating any forecast as available at a historical prediction origin. Retrieval time alone cannot reconstruct that history.
- Requested 15-minute output may be interpolated from hourly data, depending on region/model. It must not automatically be described as native 15-minute numerical weather prediction.
- Shortwave radiation is an average over the preceding output interval; temperature and cloud-cover timestamps have different physical interpretations. Align intervals explicitly before any future power-model integration.
- Missing values remain missing. The adapter does not interpolate, train a power model, join internal measurements or calculate real-world accuracy. Existing published metrics and figures remain entirely synthetic.

Weather data attribution: [Open-Meteo](https://open-meteo.com/) (CC BY 4.0). Consult the current [terms and usage limits](https://open-meteo.com/en/terms) before use; the free endpoints are for non-commercial use. Technical references: [Forecast API](https://open-meteo.com/en/docs), [Previous Runs](https://open-meteo.com/en/docs/previous-runs-api), [Single Runs](https://open-meteo.com/en/docs/single-runs-api). Provider access terms and data licensing are separate from this repository's source publication scope.
