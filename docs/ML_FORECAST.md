# Monthly UPI forecasting with Ridge regression

The forecasting model predicts monthly UPI transaction volume in billions. It
learns coefficients from the project's national monthly totals. Run it with:

```powershell
python -m pip install -r requirements-ml.txt
python tools/train_forecast.py
python tools/test_forecast.py
```

## Method

- Input: `data/upi_monthly_totals.csv`, April 2016 to August 2026, 125 months.
- Features: volumes 1, 2, 3 and 12 months earlier, elapsed month index, and sine
  and cosine of the calendar month. The 12-month lag leaves 113 supervised rows.
- Model: Ridge regression with an unpenalised intercept. NumPy solves
  `(Z.T @ Z + alpha * I) @ coefficients = Z.T @ (y - mean(y))`.
- Scaling: feature means and standard deviations come from each training window.
- Alpha selection: 0.01, 0.1, 1, 10 and 100, evaluated on two earlier 12-month
  recursive validation windows. The selected value is 10.
- Test: train on targets April 2017 to August 2025, then predict all 12 months
  September 2025 to August 2026 recursively. Test observations do not enter
  training, scaling, alpha selection or subsequent lag features.
- Final forecast: refit using all 113 supervised observations through August 2026
  and predict September 2026 to August 2027 recursively.

## Measured results

| Metric | Ridge | Seasonal naive (same month last year) |
|---|---:|---:|
| MAE, billion transactions | 0.33645 | 4.49352 |
| RMSE, billion transactions | 0.46231 | 4.50092 |
| MAPE | 1.55957% | 20.55876% |

The refitted model forecasts **28.63271 billion** transactions for August 2027.
MAPE is an error measure and should not be presented as classification accuracy.
The estimate reflects one historical test window and has no prediction interval.
Future changes to payment behaviour or policy can change forecast performance.

## Files

- `output/ml_forecast/model_results.json`: coefficients, scaler, selected alpha,
  source hash, evaluation details, test results and future predictions.
- `output/ml_forecast/backtest.csv`: actual, predicted and baseline volumes.
- `output/ml_forecast/forecast.csv`: 12 future monthly estimates.

Python runs the ML model independently of the existing Power BI report. The
report screenshot retains its original DAX growth projection. Ridge results and
the DAX scenario are separate estimates based on different methods.

Method reference: [Ridge regression objective](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html).
