import numpy as np


def equation(*args):
    return np.full_like(args[0], np.nan, dtype=float)
