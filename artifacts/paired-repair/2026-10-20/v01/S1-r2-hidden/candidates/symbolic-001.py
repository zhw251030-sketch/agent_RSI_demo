import numpy as np


def equation(x, v, params):
    a = params[0] * x + params[1] * v + params[2] * v * v
    # numerical safety: clip any extremely large output to keep the run finite
    np.clip(a, -1e6, 1e6, out=a)
    return a
