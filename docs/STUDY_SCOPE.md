# Study scope and endpoint selection

## Research question

Do differences between three or four numerical weather predictions contain useful information beyond their ensemble means when predicting historical weather conditions?

The within-2025 study uses **four forecast centres**: DWD ICON-EU, ECMWF IFS 0.25°, Météo-France ARPEGE Europe and ECCC GEM Global. A prespecified three-member subset excludes GEM Global. NOAA GFS Global is a fifth source used only as a comparator in that study. The cross-year study described below instead includes GFS and omits GEM, consistently in both years. ERA5 is always the retrospective verification reference, never an input forecast member.

For each valid timestamp and each weather variable, the mean is the arithmetic average over all declared members. The variance feature is

`sample_variance = sum((member_prediction - ensemble_mean)**2) / (member_count - 1)`.

The historical `means_plus_variance` model receives these variance values in squared physical units, together with weather means and known clock features. `means_only` receives identical features except variance. Both use the same training/validation partitions and candidate menu: three scaled Ridge regularization values and a fixed histogram gradient-boosting configuration. The latter allows nonlinear effects of disagreement. Candidates are selected on validation only. No test-driven architecture or member-set selection is performed.

The three-/four-model cases use identical complete timestamps, references, estimator candidates and scoring rules. Missing members, unsupported fields, nonfinite values or mismatched units are rejected; there is no fallback from four members to two. A generic summary helper also computes standard deviation and range, but those are diagnostics rather than extra, redundant variance-model inputs.

Three or four members offer a richer description of disagreement than a pair, but member count alone does not establish robust uncertainty: different forecast centres can share observations, boundary conditions and biases. Neither ensemble variance nor sample standard deviation is a calibrated prediction interval.

## Which Open-Meteo endpoint is appropriate?

| Endpoint | Appropriate purpose | Use in this study |
| --- | --- | --- |
| `previous-runs-api.open-meteo.com/v1/forecast` | Archived forecasts at provider-defined fixed lead offsets | All four inputs and GFS use hourly `_previous_day1` forecasts for 2025 |
| `archive-api.open-meteo.com/v1/archive` | Retrospective weather/reanalysis | Explicit `models=era5`, matched UTC valid times and units |
| `historical-forecast-api.open-meteo.com/v1/forecast` | Stitched historical operational output | Available in the adapter, but not substituted for a fixed-lead input |
| `single-runs-api.open-meteo.com/v1/forecast` | Full horizon from one specified initialization | Needed for a genuinely common-origin full-day experiment; requires release-time handling |
| `api.open-meteo.com/v1/forecast` | Current/future operational acquisition | Not used to reconstruct 2025 forecasts |

The Historical Weather endpoint defaults to a blend unless a model is selected; this study explicitly selects ERA5. `best_match` and seamless blends do not count as extra independent weather members.

Previous Runs is appropriate for this hourly fixed-lead post-processing study. It does not imply that every hour in a day was predicted from the same issue time. Single Runs preserves that run structure, but its initialization time precedes public release. The provider currently documents archives from April 2026 for most Single Runs models, with longer ECMWF history; a full 2025 four-model common-origin experiment cannot simply assume those runs exist.

Open-Meteo 15-minute output may be interpolated depending on model/region. This historical comparison therefore uses hourly output without claiming native quarter-hour resolution. Radiation values refer to the preceding interval, and the comparison retains that convention for forecasts and reanalysis.

## Scope boundaries and version history

### Cross-year study

The [2025-to-2026 evaluation](YEARLY_RESULTS.md) uses ICON-EU, ECMWF IFS, ARPEGE Europe and **GFS Global** consistently in both years. GEM has internal gaps in its 2026 archive, and JMA GSM lacks the needed radiation, so the replacement was chosen from field availability before evaluating 2026 errors. GFS is therefore an input and raw-model baseline in that study, not an excluded comparator. ERA5 remains the reference. The earlier within-2025 GEM-based results below remain a separate experiment.

All of 2025 is used for final fitting after chronological 2025-only selection. Models stay frozen across 2026; the calendar holdout is January onward through the latest complete common day. ERA5 delay means full late-December labels would not all have been available for a real January 1 deployment, so a January 8-onward subset is also reported. This is calendar-year generalization, not an exact historical deployment ledger.

The historical workflow verifies radiation and temperature, using radiation, temperature and cloud-cover forecast predictors. It does not reproduce a private measured-PV system, its results, its trained models or its source data. The separate synthetic daily power example also uses four fictional members and explicit variance, but remains a toy physical model.

The earlier two-member standard-deviation report is retained as [legacy evidence](results/historical-two-model-legacy.json). It is superseded for the stated research question. The revised study changes both ensemble composition and the candidate estimator menu, so comparisons against that legacy report do not isolate a causal benefit from member count. The controlled three-versus-four sensitivity uses the same revised menu and dates.

A complete private static review covered 18 development notebooks and 52 supporting Python files. It found single-, two- and optional three-member branches alongside an early four-member experiment, inconsistent terminology, silent member fallback, scaling before chronological folds in some versions, and differences in sequence/quantile definitions. The originals remain untouched and are not redistributed. No private saved model was loaded and no operational scores are presented as independently reproduced.

Sources: [Previous Runs](https://open-meteo.com/en/docs/previous-runs-api), [Historical Weather](https://open-meteo.com/en/docs/historical-weather-api), [Historical Forecast](https://open-meteo.com/en/docs/historical-forecast-api), [Single Runs](https://open-meteo.com/en/docs/single-runs-api). Endpoint semantics were checked against provider documentation and live availability for the selected model/date combination. The public report retains only aggregate results.
