# Validation

Tests check deterministic generation, normalized bounds, rejected timestamp/value defects, known lag/target alignment, feature invariance when future observations are changed, label purging at horizons 1, 4 and 96, hand-calculated error metrics, zero-power handling, residual-quantile rank and a complete synthetic experiment.

A separate holdout-perturbation test changes all observations from the first test issue onward and verifies that model selection, validation metrics and the calibration radius remain unchanged. Timestamp-spacing checks are tested at both nanosecond and microsecond resolution for pandas 2/3 compatibility. The suite contains 15 tests.

The default 120-day, seed-42 experiment selected gradient boosting on validation. On the synthetic holdout its MAE was approximately 0.01602 p.u., compared with 0.06111 for persistence and 0.04592 for daily persistence. Active-period MAE was approximately 0.03157 p.u.; observed empirical-band coverage was approximately 0.9194. These values describe the invented process only. The full run metadata is saved in `docs/results/metrics.json` and the figure in `docs/figures/`.

GitHub Actions runs tests, the publication allowlist and a complete CLI experiment on Python 3.11 and 3.12 and stores the generated synthetic outputs as workflow artifacts. The root badge links to actual run status. Generated figures are visually reviewed before inclusion.

Successful tests demonstrate software behavior on synthetic data. No historical operational model is executed, no model pickle is loaded and no real-world forecast claim is validated. Dependency versions, generator parameters and chronological boundaries are saved in each metrics JSON.
