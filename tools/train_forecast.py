"""Train and evaluate a monthly UPI Ridge regression forecast.

Uses NumPy only. The 12-month test window stays out of feature scaling,
coefficient fitting and alpha selection. Multi-month forecasts are recursive.
Run: python tools/train_forecast.py
"""
from __future__ import annotations

import csv
from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "upi_monthly_totals.csv"
OUT = ROOT / "output" / "ml_forecast"
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
FEATURES = ["lag_1_bn", "lag_2_bn", "lag_3_bn", "lag_12_bn",
            "month_index", "month_sin", "month_cos"]
TEST_MONTHS = 12
ALPHAS = [0.01, 0.1, 1.0, 10.0, 100.0]


def next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def load_data(source: Path = SOURCE):
    with source.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    parsed = []
    for row in rows:
        month, year = row["month"].split("-")
        parsed.append((date(int(year), MONTHS.index(month) + 1, 1),
                       float(row["volume_mn"]) / 1000))
    parsed.sort()
    if len(parsed) < 60:
        raise ValueError("At least 60 monthly observations are required")
    for (d0, _), (d1, _) in zip(parsed, parsed[1:]):
        if next_month(d0) != d1:
            raise ValueError("The source has a duplicate or missing month")
    dates, values = zip(*parsed)
    y = np.asarray(values, dtype=float)
    if not np.isfinite(y).all() or (y < 0).any():
        raise ValueError("Volumes must be finite and non-negative")
    return list(dates), y


def feature(history, index: int, target_date: date):
    if len(history) < 12:
        raise ValueError("Lag features need 12 months of history")
    angle = 2 * np.pi * (target_date.month - 1) / 12
    return np.array([history[-1], history[-2], history[-3], history[-12],
                     index, np.sin(angle), np.cos(angle)], dtype=float)


def fit_model(dates, values, end: int, alpha: float):
    # end is exclusive. Feature construction uses earlier values only.
    x = np.stack([feature(values[:i], i, dates[i]) for i in range(12, end)])
    y = np.asarray(values[12:end], dtype=float)
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.where(scale > 0, scale, 1.0)
    z = (x - mean) / scale
    intercept = float(y.mean())
    coefficients = np.linalg.solve(z.T @ z + alpha * np.eye(z.shape[1]),
                                   z.T @ (y - intercept))
    # Verify the fitted coefficients satisfy the Ridge normal equation.
    gradient = z.T @ (z @ coefficients - (y - intercept)) + alpha * coefficients
    if not np.allclose(gradient, 0, atol=1e-7):
        raise AssertionError("Ridge solution failed its normal-equation check")
    return {"alpha": float(alpha), "mean": mean.tolist(), "scale": scale.tolist(),
            "coefficients": coefficients.tolist(), "intercept_bn": intercept,
            "train_end_exclusive": end}


def forecast(model, history, first_date: date, horizon: int):
    # Copy the prefix. Future observations are never supplied to predict.
    history = list(history)
    results = []
    d = first_date
    for _ in range(horizon):
        x = feature(history, len(history), d)
        z = (x - np.array(model["mean"])) / np.array(model["scale"])
        value = max(0.0, float(model["intercept_bn"] + z @ model["coefficients"]))
        if not np.isfinite(value):
            raise ValueError("Forecast produced a non-finite value")
        results.append({"date": d.isoformat(), "forecast_bn": value})
        history.append(value)
        d = next_month(d)
    return results


def scores(actual, predicted):
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    error = predicted - actual
    nonzero = actual != 0
    return {"mae_bn": float(np.abs(error).mean()),
            "rmse_bn": float(np.sqrt(np.mean(error ** 2))),
            "mape_pct": float(np.mean(np.abs(error[nonzero] / actual[nonzero])) * 100)}


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    dates, y = load_data()
    split = len(y) - TEST_MONTHS
    tuning = []
    # Two earlier 12-month validation windows, both entirely before the test.
    for alpha in ALPHAS:
        fold_scores = []
        for end in (split - 24, split - 12):
            model = fit_model(dates, y, end, alpha)
            predicted = forecast(model, y[:end], dates[end], TEST_MONTHS)
            fold_scores.append(scores(y[end:end + TEST_MONTHS],
                                      [r["forecast_bn"] for r in predicted])["rmse_bn"])
        tuning.append({"alpha": alpha, "mean_validation_rmse_bn": float(np.mean(fold_scores))})
    best = min(tuning, key=lambda r: r["mean_validation_rmse_bn"])
    alpha = best["alpha"]
    test_model = fit_model(dates, y, split, alpha)
    predictions = forecast(test_model, y[:split], dates[split], TEST_MONTHS)
    predicted = [r["forecast_bn"] for r in predictions]
    baseline = y[split - 12:split]  # Same month in the previous year.
    metrics = scores(y[split:], predicted)
    baseline_metrics = scores(y[split:], baseline)
    test_rows = [{"date": dates[split + i].isoformat(), "actual_bn": float(y[split + i]),
                  "predicted_bn": predicted[i], "seasonal_naive_bn": float(baseline[i])}
                 for i in range(TEST_MONTHS)]
    final_model = fit_model(dates, y, len(y), alpha)
    future = forecast(final_model, y, next_month(dates[-1]), 12)
    # Round-trip the persisted model and verify reproducible predictions.
    restored = json.loads(json.dumps(final_model))
    assert forecast(restored, y, next_month(dates[-1]), 12) == future
    payload = {"algorithm": "Ridge regression", "implementation": "NumPy normal equations",
               "target": "Monthly UPI transaction volume in billions", "features": FEATURES,
               "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
               "source_rows": len(y), "supervised_rows": len(y) - 12,
               "alpha": alpha, "alpha_selection": tuning,
               "test_training_first_target": dates[12].isoformat(),
               "test_training_last_target": dates[split - 1].isoformat(),
               "test_training_rows": split - 12,
               "test_period": [dates[split].isoformat(), dates[-1].isoformat()],
               "test_rows": TEST_MONTHS, "test_method": "12-step recursive, held-out future months",
               "metrics": metrics, "seasonal_naive_metrics": baseline_metrics,
               "test_results": test_rows, "future_forecast": future,
               "final_model": final_model,
               "limitations": ["One 12-month test window", "No prediction intervals",
                               "Recursive forecasts accumulate error", "Sensitive to future structural changes"],
               "reference": "https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "model_results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_csv(OUT / "backtest.csv", test_rows, ["date", "actual_bn", "predicted_bn", "seasonal_naive_bn"])
    write_csv(OUT / "forecast.csv", future, ["date", "forecast_bn"])
    print(json.dumps({"algorithm": payload["algorithm"], "alpha": alpha,
                      "test_period": payload["test_period"], "metrics": metrics,
                      "baseline": baseline_metrics, "aug_2027_bn": future[-1]["forecast_bn"],
                      "output": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
