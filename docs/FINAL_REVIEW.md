# Final code and scientific review

Reviewed on October 18, 2026. This is a maintainer audit of the public implementation and saved local inputs, not an external peer review. The repository is suitable as a professional exploratory forecasting portfolio. Its scientific value is **7/10 for weather post-processing research**; the evidence does not yet establish operational solar-power accuracy.

## Scope and verification

The audit covered every public Python module and test, the CI workflow, packaging, Markdown documentation and published aggregate JSON. It checked chronological separation, feature construction, estimator selection, timestamp/label alignment, endpoint choice, report consistency and public-file boundaries. All 50 offline tests pass. A total of 2,935 published numerical fields were reproduced within a 1e-10 comparison tolerance from the saved inputs, including both synthetic studies, the frozen cross-year study, within-2025 rolling evaluation and three-member sensitivity. Markdown local links and the publication allowlist were checked. No original private model was executed and no private source or downloaded hourly data is included in this release.

## Confirmed defects corrected

| Defect | Consequence | Correction |
| --- | --- | --- |
| Availability trimming checked matching indices and row count without validating a UTC calendar grid | Shifted, duplicated or reversed hours could be treated as whole days | Require nonempty UTC data starting at midnight with exact hourly spacing before trimming |
| Positive-reference radiation scoring assumed at least one positive value | A valid zero-radiation reference period raised an exception | Emit a zero count and empty stratified scores; retain all-hour scores |
| The cross-year writer hardcoded 2,000 replicates | Reports from custom runs could misstate the uncertainty calculation | Record inference settings in JSON and render the actual replicate count |
| The writer called a supplied cache the latest common provider data | An older cache could be presented as current | Describe the evaluated data endpoint and explicitly state that caches are not freshness-checked |
| Test status always said incomplete year | A future complete test year would be mislabeled | Determine status from the calendar endpoint |
| Daily-results JSON retained older terminology | The artifact wording differed from the current code | Synchronize the variance interpretation |

The audit also added a guard against mismatched declared training/test member identities and clarified GFS roles across the two historical experiments. These changes do not alter the published fitted models, predictions, selected estimators or score differences. No new hyperparameter or member selection used 2026 errors.

## What the results support

The cross-year experiment trains on all 8,760 hours of 2025 after selection within four earlier chronological folds. The frozen test covers January 1–October 12, 2026: 285 days and 6,840 hours. It uses four named forecast models and sample variance computed independently for each variable at each valid timestamp. See the [full report](YEARLY_RESULTS.md) and [aggregate JSON](results/yearly-2025-2026.json).

| Cross-year comparison | Result | Interpretation |
| --- | --- | --- |
| Radiation, means-only ML → means plus variance | MAE 18.2953 → 17.5962 W/m²; paired reduction 0.6991, approximate 95% interval [0.2995, 1.1740] | Conditional evidence that disagreement helps beyond mean-compressed predictors |
| Radiation, raw ensemble average → variance ML | MAE 17.8851 → 17.5962 W/m²; paired reduction 0.2889, interval [-0.6097, 1.1729] | No clear improvement over the simple average |
| Temperature, means-only ML → variance ML | MAE 0.6280 → 0.6306 °C; paired reduction -0.0026, interval [-0.0060, 0.0006] | No clear incremental value from variance |

These are the primary seven-day circular-block intervals, conditional on the fitted models. Other block lengths, monthly scores, positive-reference radiation scores and January 8-onward availability-buffered scores are retained. The within-2025 experiment is separate: it uses GEM instead of GFS among its inputs, includes an excluded GFS comparator, and is explicitly retrospective. Scores across those experiments do not isolate a causal effect of changing one member.

## Remaining scientific limitations

1. **Verification reference:** ERA5 is reanalysis, with possible shared inputs and assumptions across weather systems. Agreement with it does not establish accuracy against independent station measurements or measured PV power.
2. **Generalization:** one withheld location, one training year and an incomplete test year provide limited spatial and interannual evidence. Exact real-data reproduction requires the private location configuration and saved downloads; the offline synthetic experiments are publicly reproducible.
3. **Baseline coverage:** the raw ensemble average is a strong baseline, but a train-only weighted ensemble and ML receiving all individual member forecasts are still missing. Mean and variance are deterministic summaries of those members; an advantage over mean-only features is not evidence of new information beyond the full forecasts.
4. **Forecast timing:** Previous Runs supplies fixed lead offsets. The actual-weather study is hourly post-processing, not a common-origin 96-step forecast of an entire next day. Such a deployment study needs archived individual runs and a release-time ledger. Late-December ERA5 labels would not all be available on January 1; the buffered subset mitigates this without proving exact operational availability.
5. **Uncertainty:** variance is a point-forecast input, not a calibrated probability forecast. Bootstrap intervals are approximate, marginal and conditional, omit refitting/selection uncertainty, and have seasonal-stationarity and block-length limitations. The separate synthetic daily bands under-cover their nominal 90% level.
6. **Research status:** development is retrospective and was not prospectively registered. Four members capture more disagreement than two, but correlation between centres means member count alone does not guarantee robust uncertainty.

## Assessment

The strongest contributions are transparent negative results, per-timestamp four-model variance, time-respecting fitting, frozen cross-year testing, simple baselines and explicit limits on the claims. No critical implementation or test-label leakage defect was identified in the evaluated path after the corrections above. This is a bounded audit, not a guarantee that all possible defects are absent.

The next scientific experiment should freeze its protocol before evaluating new periods/sites, add full-member and train-only weighted-ensemble baselines, and verify against independent public observations. A measured PV target is necessary before claiming solar-power forecasting performance. Adding those experiments should not overwrite or retune the current 2026 holdout results.

Technical references: [Open-Meteo Previous Runs](https://open-meteo.com/en/docs/previous-runs-api), [Historical Weather / ERA5](https://open-meteo.com/en/docs/historical-weather-api), [Single Runs](https://open-meteo.com/en/docs/single-runs-api), [time-series block bootstrap](https://arch.readthedocs.io/en/stable/bootstrap/timeseries-bootstraps.html). Weather data by Open-Meteo (CC BY 4.0).
