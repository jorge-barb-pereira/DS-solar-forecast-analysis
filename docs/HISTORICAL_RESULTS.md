# Historical weather results

Real archived forecast data compared with ERA5 reanalysis. These are weather-variable scores, not measured PV-power accuracy. Location values, raw hourly data and original project material are excluded.

**Four input models:** ICON-EU, ECMWF IFS 0.25°, ARPEGE Europe and GEM Global. The ML ablation adds explicit sample variance (`ddof=1`) across all four members. GFS is an excluded comparator, and ERA5 is the reference. The earlier two-model standard-deviation experiment is [archived separately](results/historical-two-model-legacy.json); its conclusions do not describe this revised study.

## Design

The local dataset has 8,760 hourly rows. Rolling evaluation covers 201 unique test days across 7 expanding windows. Each model uses earlier training and 30 validation days, with seven-day gaps before validation and testing. GFS never enters fitting or selection.

This is a retrospective exploratory extension: this dataset and its original holdout had already been inspected. It is not a fresh independent confirmation. Protocol settings were fixed before running the new rolling analysis, without searching for a favorable block length or reference.

## Pooled rolling scores

| Method | Radiation MAE (W/m²) | Temperature MAE (°C) |
| --- | ---: | ---: |
| icon_eu | 18.1285 | 1.3856 |
| ecmwf_ifs025 | 16.9903 | 1.2023 |
| meteofrance_arpege_europe | 21.9370 | 1.3831 |
| gem_global | 18.6391 | 1.8026 |
| gfs_global | 21.2879 | 1.1795 |
| input_ensemble_mean | 14.2979 | 1.0884 |
| means_only | 16.5768 | 0.6846 |
| means_plus_variance | 15.0618 | 0.6676 |

## Paired differences and uncertainty

Positive reduction means lower MAE for `means_plus_variance`. Intervals below use 2,000 paired circular-block replicates of daily mean errors, with seven-day blocks resampled separately within each fold. Comparisons use exactly the same test hours.

| Variable | Comparator | MAE reduction | Approximate 95% interval |
| --- | --- | ---: | --- |
| shortwave_radiation | means_only | 1.5150 | [1.1273, 1.8978] |
| shortwave_radiation | input_ensemble_mean | -0.7639 | [-1.2260, -0.2809] |
| shortwave_radiation | gfs_global | 6.2261 | [4.0848, 8.6112] |
| temperature_2m | means_only | 0.0170 | [-0.0020, 0.0339] |
| temperature_2m | input_ensemble_mean | 0.4208 | [0.3315, 0.5029] |
| temperature_2m | gfs_global | 0.5119 | [0.4098, 0.6200] |

## Three-model versus four-model sensitivity

The three-member subset (ICON-EU, ECMWF IFS and ARPEGE Europe) and four-member ensemble use the same complete dates, partitions, candidate models and reference. No model set is selected on test performance. The comparison adds GEM Global as a fourth forecast centre, but does not assume statistical independence between centres.

| Variable | Three members: means MAE | Three members: variance MAE | Four members: means MAE | Four members: variance MAE |
| --- | ---: | ---: | ---: | ---: |
| shortwave_radiation | 19.0341 | 16.4218 | 16.5768 | 15.0618 |
| temperature_2m | 0.6951 | 0.6825 | 0.6846 | 0.6676 |

## Findings

For **shortwave_radiation**, the primary paired interval indicates **lower error with variance**. The lowest pooled MAE among the fixed methods is from `input_ensemble_mean`; this descriptive ranking does not select or refit a winner using test labels.

For **temperature_2m**, the primary paired interval indicates **no clear incremental benefit from variance**. The lowest pooled MAE among the fixed methods is from `means_plus_variance`; this descriptive ranking does not select or refit a winner using test labels.


![Rolling weather scores and paired intervals](figures/historical-robustness.png)

## Interpretation and limits

An interval containing zero does not establish a consistent improvement under this approximation. An interval excluding zero is conditional evidence for this dataset/protocol, not proof of universal superiority. Intervals are marginal, without multiplicity adjustment, and do not include retraining uncertainty. Daily blocks account for some serial dependence, but dependence beyond the selected length and artificial circular joins remain limitations.

The aggregate JSON includes 1-, 3-, 7- and 14-day block sensitivity, every fold, revised fixed-holdout results, units, versions, RMSE, bias, and radiation scores restricted to positive ERA5 radiation. Nighttime zeros can reduce all-hour radiation MAE. Earlier test outcomes may enter training in later rolling windows once historical, while each window remains strictly chronological.

One location and one year limit generalization. ERA5 is a retrospective model-based reference, with shared meteorological inputs and assumptions; it is not independent station truth. Exact local reproduction requires the withheld local configuration and downloaded data. Raw weather must remain local. The synthetic power studies remain separate.

[Aggregate results and sensitivity](results/historical-robustness.json) · [Historical protocol](HISTORICAL_BENCHMARK.md). Weather data by [Open-Meteo](https://open-meteo.com/) (CC BY 4.0); [ERA5 citation guidance](https://open-meteo.com/en/docs/historical-weather-api). Bootstrap background: [arch time-series bootstrap documentation](https://arch.readthedocs.io/en/stable/bootstrap/timeseries-bootstraps.html). The NumPy implementation here adds no bootstrap dependency.
