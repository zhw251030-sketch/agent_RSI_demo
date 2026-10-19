import numpy as np


def equation(*args):
    """Fixed plumbing fixture: one slope per input plus an intercept."""
    columns, params = args[:-1], args[-1]
    result = np.full_like(columns[0], params[-1], dtype=float)
    for index, column in enumerate(columns):
        result = result + params[index] * column
    return result
