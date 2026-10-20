"""Bounded host-side descriptive summaries of training residuals.

The caller must supply authorized training observations; this function performs
no data loading or candidate execution. Residuals are prediction minus target.
Standardized bias divides their mean by the population target standard
deviation (ddof=0), not a standard error or a significance statistic.

For each input, sort its values and calculate quantiles at 0, .25, .5, .75, 1.
The linear quantile uses h=(n-1)*q, j=floor(h), w=h-j and
(1-w)*sorted[j] + w*sorted[j+1] (the last endpoint is the maximum).
Bins are [lower, upper), except the final bin which includes its upper bound.
Equal values therefore stay together; repeated boundaries can produce empty
bins, and a constant input places every observation in the final bin. Bounds
depend only on X, never targets or candidate predictions.

Inputs are finite real-valued list/tuple tables, with 1..3 columns and at most
100000 rows. Input names are unique ASCII identifiers of at most 64 characters.
No rows, target/prediction arrays, or individual residuals are returned. These
marginal summaries do not establish causation or statistical significance.
"""
import math
from numbers import Real


MAX_ROWS = 100000
MAX_INPUTS = 3
MAX_NAME_LENGTH = 64


class _InvalidInput(ValueError):
    pass


def _number(value):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise _InvalidInput("invalid_dtype")
    number = float(value)
    if not math.isfinite(number):
        raise _InvalidInput("nonfinite_input")
    return number


def _finite(value):
    if not math.isfinite(value):
        raise OverflowError
    return value


def _mean_and_rmse(values):
    count = len(values)
    if not count:
        return None, None
    mean = _finite(math.fsum(value / count for value in values))
    mean_square = _finite(math.fsum(value ** 2 / count for value in values))
    return mean, _finite(math.sqrt(mean_square))


def _quantile(sorted_values, quantile):
    position = (len(sorted_values) - 1) * quantile
    index = math.floor(position)
    weight = position - index
    if weight == 0:
        return sorted_values[index]
    # This convex form avoids overflow from upper - lower for extreme inputs.
    return _finite((1 - weight) * sorted_values[index] + weight * sorted_values[index + 1])


def summarize_residuals(X, y, predictions, input_names) -> dict:
    """Return finite bounded aggregate observations or a sanitized error dict.

    Arithmetic overflow fails the complete summary rather than dropping rows
    or exposing partial statistics. Empty bins have null means/RMSE. Constant
    targets retain valid bias/RMSE, but standardized bias is null with a reason.
    """
    base = {"scope": "train", "residual_definition": "prediction - target"}

    def invalid(reason):
        return {"status": "error", **base, "error": reason}

    if not isinstance(X, (list, tuple)) or not X:
        return invalid("invalid_input_shape")
    count = len(X)
    if count > MAX_ROWS:
        return invalid("row_limit_exceeded")
    if not isinstance(input_names, (list, tuple)) or not 1 <= len(input_names) <= MAX_INPUTS:
        return invalid("invalid_input_names")
    if any(not isinstance(name, str) or not 1 <= len(name) <= MAX_NAME_LENGTH
           or not name.isascii() or not name.isidentifier() for name in input_names):
        return invalid("invalid_input_names")
    if len(set(input_names)) != len(input_names):
        return invalid("invalid_input_names")
    width = len(input_names)
    if any(not isinstance(row, (list, tuple)) or len(row) != width for row in X):
        return invalid("invalid_input_shape")
    if not isinstance(y, (list, tuple)) or len(y) != count:
        return invalid("invalid_target_shape")
    if not isinstance(predictions, (list, tuple)) or len(predictions) != count:
        return invalid("invalid_prediction_shape")

    try:
        inputs = [[_number(value) for value in row] for row in X]
        actual = [_number(value) for value in y]
        predicted = [_number(value) for value in predictions]
    except _InvalidInput as exc:
        return invalid(str(exc))
    except (OverflowError, ValueError):
        return invalid("numeric_overflow")

    try:
        residuals = [_finite(prediction - target) for prediction, target in zip(predicted, actual)]
        bias, rmse = _mean_and_rmse(residuals)
        constant_target = all(value == actual[0] for value in actual)
        if constant_target:
            target_variance = 0.0
        else:
            target_mean = _finite(math.fsum(value / count for value in actual))
            target_variance = _finite(math.fsum((value - target_mean) ** 2 / count for value in actual))
        if target_variance == 0:
            standardized_bias = None
            standardized_bias_reason = ("zero_target_variance" if constant_target
                                        else "target_variance_underflow")
        else:
            standardized_bias = _finite(bias / math.sqrt(target_variance))
            standardized_bias_reason = None

        per_input = []
        for column, name in enumerate(input_names):
            column_values = [row[column] for row in inputs]
            ordered = sorted(column_values)
            bounds = [_quantile(ordered, q) for q in (0, 0.25, 0.5, 0.75, 1)]
            grouped = [[], [], [], []]
            for value, residual in zip(column_values, residuals):
                # Comparisons to the same bounds keep equal values together.
                index = sum(value >= boundary for boundary in bounds[1:4])
                grouped[index].append(residual)
            bins = []
            for index, values in enumerate(grouped):
                bin_mean, bin_rmse = _mean_and_rmse(values)
                bins.append({"lower": bounds[index], "upper": bounds[index + 1],
                             "upper_inclusive": index == 3, "count": len(values),
                             "mean_residual": bin_mean, "rmse": bin_rmse})
            per_input.append({"name": name, "boundaries": bounds, "bins": bins})
    except (OverflowError, ValueError, ZeroDivisionError):
        return invalid("numeric_overflow")

    return {"status": "ok", **base, "n": count, "bias": bias, "rmse": rmse,
            "standardized_bias": standardized_bias,
            "standardized_bias_reason": standardized_bias_reason,
            "standardized_bias_definition": "bias / population_std(target)",
            "binning_method": "linear_quantile",
            "inputs": per_input}
