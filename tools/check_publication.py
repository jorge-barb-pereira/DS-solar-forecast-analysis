"""Allow only the reviewed source tree and known generated public artifacts."""

from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
allowed_files = {
    ".gitignore",
    ".gitattributes",
    "pyproject.toml",
    "README.md",
    "CONTRIBUTING.md",
    "docs/METHODS.md",
    "docs/PUBLICATION_SCOPE.md",
    "docs/VALIDATION.md",
    "docs/figures/forecast-analysis.png",
    "docs/results/metrics.json",
    ".github/workflows/forecast.yml",
    "tools/check_publication.py",
    "tests/test_forecasting.py",
    "tests/test_open_meteo.py",
    "docs/OPEN_METEO.md",
    "docs/DAY_AHEAD.md",
    "tests/test_day_ahead.py",
    "docs/results/day-ahead.json",
    "docs/figures/day-ahead.png",
    "tests/test_history.py",
    "docs/HISTORICAL_BENCHMARK.md",
}
allowed_package = {
    "__init__.py",
    "__main__.py",
    "data.py",
    "features.py",
    "study.py",
    "open_meteo.py",
    "ensemble.py",
    "day_ahead.py",
    "history.py",
}
checked = 0
for p in root.rglob("*"):
    if not p.is_file():
        continue
    rel = p.relative_to(root)
    if any(
        part in {".git", ".venv", "venv", "__pycache__", "output"}
        or part.endswith(".egg-info")
        for part in rel.parts
    ):
        continue
    path = rel.as_posix()
    allowed = path in allowed_files or (
        rel.parent.as_posix() == "src/solar_forecast" and p.name in allowed_package
    )
    if not allowed:
        raise SystemExit("Unexpected publication file: " + path)
    checked += 1
print(f"PASS: {checked} files in reviewed publication allowlist")

if (root / ".git").exists():
    tracked = (
        subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
        .decode("utf-8")
        .split("\0")
    )
    for path in filter(None, tracked):
        rel = Path(path)
        if not (
            path in allowed_files
            or (
                rel.parent.as_posix() == "src/solar_forecast"
                and rel.name in allowed_package
            )
        ):
            raise SystemExit("Unapproved tracked file: " + path)
    print("PASS: tracked files contain no ignored outputs or unapproved artifacts")
