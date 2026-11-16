"""Focused checks for temporal separation and forecast reproducibility."""
import unittest

import numpy as np

from train_forecast import fit_model, forecast, load_data, next_month


class ForecastTests(unittest.TestCase):
    def test_test_values_do_not_affect_fit_or_predictions(self):
        dates, y = load_data()
        end = len(y) - 12
        modified = y.copy()
        modified[end:] = 1_000_000
        first = fit_model(dates, y, end, 10)
        second = fit_model(dates, modified, end, 10)
        self.assertEqual(first, second)
        self.assertEqual(forecast(first, y[:end], dates[end], 12),
                         forecast(second, modified[:end], dates[end], 12))

    def test_recursive_forecast_matches_stepwise_prediction(self):
        dates, y = load_data()
        model = fit_model(dates, y, len(y), 10)
        d = next_month(dates[-1])
        together = forecast(model, y, d, 12)
        history = list(y)
        for expected in together:
            one = forecast(model, history, d, 1)[0]
            self.assertEqual(one, expected)
            history.append(one["forecast_bn"])
            d = next_month(d)

    def test_source_is_contiguous_and_model_is_finite(self):
        dates, y = load_data()
        for first, second in zip(dates, dates[1:]):
            self.assertEqual(next_month(first), second)
        model = fit_model(dates, y, len(y), 10)
        self.assertTrue(np.isfinite(model["coefficients"]).all())
        self.assertTrue((np.asarray(model["scale"]) > 0).all())


if __name__ == "__main__":
    unittest.main()
