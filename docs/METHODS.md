# Methods and limitations

## Synthetic data and quality policy

The generator combines a fixed sine-shaped daily envelope, correlated stochastic attenuation and small observation noise. It has no physical site or equipment parameter. The active interval is deliberately fixed at synthetic clock hours 06:00–18:00; UTC is an indexing convention, not a claim about solar time. The date range is fictional. Values are clipped to [0,1].

Input validation rejects missing, duplicate, disordered or irregular timestamps and nonfinite/out-of-range values. No backward fill, centered smoothing or interpolation from future observations is used. The command generates its own data; a real-data ingestion adapter is outside this example.

## Causality and forecast issuance

For an issue index t and a horizon h in 15-minute steps, the target is power[t+h]. Features include power[t], observations at t-1, t-4 and t-96, a trailing four-observation mean ending at t, a daily-reference observation at t+h-96 and the known target clock-hour encoding. Restricting h to 1–96 ensures the daily reference is available at issuance. The synthetic timestamps define observation availability directly; collection/delivery delays are not modeled.

## Selection and evaluation

Nominal chronological proportions are 60% training, 15% validation, 10% residual calibration and 15% final testing. Before each boundary, samples whose target timestamp reaches or crosses the next block's first issue timestamp are removed. Thus every earlier label precedes later issuance, including multi-step horizons.

The fixed candidates are persistence, daily persistence, Ridge with three alpha values and histogram gradient boosting. Ridge preprocessing is fitted on training only. Boosting disables internal early stopping so it does not introduce an implicit shuffled validation split. Minimum validation MAE chooses the candidate; ties use model name. Baselines are eligible to win. The fitted model is then frozen: no refitting or selection uses calibration/test labels.

Absolute calibration errors produce a finite-sample upper order-statistic radius at nominal 90%. Predictions and interval endpoints are clipped to the known synthetic support. Actual test coverage and mean width are reported without a coverage guarantee. Temporal dependence, nonstationarity and overlapping forecast horizons prevent an exchangeability claim.

MAE, RMSE and signed bias use per-unit power. MAPE is omitted because zero-power observations make percentage errors unsuitable. Metrics are reported over the entire holdout and separately over the generator's fixed active clock interval. Skill relative to the better fixed baseline on the test period is descriptive; that comparison does not change the selected model. A zero baseline MAE yields undefined skill (JSON null), not a division error.

## Practical limits

This is one synthetic process and seed, with a modest fixed candidate set. It is not a comparison of operational weather providers, a deep-learning benchmark, proof of forecast calibration or an estimate of commercial savings. Nighttime zeros can make aggregate errors look smaller, which is why active-period errors are also included. Forecast-error autocorrelation and real-world sensor/provider availability would need explicit treatment for operational evaluation.

References: [scikit-learn lagged time-series forecasting example](https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html) and [chronological cross-validation guidance](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html). These document general methods; no tutorial or external implementation is copied into this project.
