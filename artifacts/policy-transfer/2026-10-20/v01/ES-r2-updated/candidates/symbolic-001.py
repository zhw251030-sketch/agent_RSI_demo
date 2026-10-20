import numpy as np


def equation(x, v, params):
    # Damped oscillator with linear + quadratic (sign-preserving) velocity drag and constant offset
    p0, p1, p2, p3 = params[0], params[1], params[2], params[3]
    return -p0 * x - p1 * v - p3 * v * np.abs(v) + p2