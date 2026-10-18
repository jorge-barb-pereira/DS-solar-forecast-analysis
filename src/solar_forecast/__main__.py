"""Run a reproducible, offline synthetic forecasting experiment."""

import argparse
import importlib.metadata
import json
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from .data import synthetic_series
from .study import run_study


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--horizon", type=int, default=4, help="15-minute steps, from 1 to 96"
    )
    parser.add_argument("--output", type=Path, default=Path("output"))
    args = parser.parse_args()
    series = synthetic_series(args.days, args.seed)
    report, forecast = run_study(series, args.horizon, args.seed)
    report["dataset"] = {
        "kind": "synthetic",
        "days": args.days,
        "seed": args.seed,
        "rows": len(series),
        "unit": "normalized power (per unit)",
    }
    report["versions"] = {
        name: importlib.metadata.version(name)
        for name in ["numpy", "pandas", "scikit-learn", "matplotlib"]
    }
    args.output.mkdir(parents=True, exist_ok=True)
    series.to_csv(args.output / "synthetic-series.csv", index_label="timestamp")
    forecast.to_csv(args.output / "forecast.csv", index_label="issued_at")
    (args.output / "metrics.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    preview = forecast.iloc[:192]
    fig, axes = plt.subplots(
        2,
        1,
        figsize=(11, 7),
        layout="constrained",
        gridspec_kw={"height_ratios": [2, 1]},
    )
    time = preview.target_time
    axes[0].fill_between(
        time,
        preview.lower,
        preview.upper,
        color="#bfd6eb",
        alpha=0.65,
        label="Empirical 90% residual band",
    )
    axes[0].plot(
        time,
        preview.target,
        color="#172e40",
        label="Synthetic observed power",
        linewidth=1.4,
    )
    axes[0].plot(
        time,
        preview.prediction,
        color="#d27d2d",
        label="Selected forecast",
        linewidth=1.2,
    )
    axes[0].set(
        ylabel="Normalized power (p.u.)",
        ylim=(-0.03, 1.03),
        title=f"Synthetic solar forecasting · {args.horizon * 15}-minute horizon",
    )
    axes[0].legend(fontsize=9, ncol=2)
    rows = {
        "Selected model": report["holdout"],
        "Persistence": report["baselines"]["persistence"],
        "Daily persistence": report["baselines"]["daily_persistence"],
    }
    axes[1].barh(
        list(rows),
        [v["mae"] for v in rows.values()],
        color=["#d27d2d", "#436a86", "#83a7b5"],
    )
    axes[1].invert_yaxis()
    axes[1].set(
        xlabel="Holdout MAE (p.u.)",
        title="Frozen selection compared with fixed baselines",
    )
    fig.savefig(args.output / "forecast-analysis.png", dpi=160)
    plt.close(fig)
    print(
        json.dumps(
            {
                k: report[k]
                for k in ["selected_model", "holdout", "baselines", "interval"]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
