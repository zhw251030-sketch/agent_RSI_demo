import numpy as np


def equation(*args):
    return np.full_like(args[0], args[-1][0], dtype=float)
