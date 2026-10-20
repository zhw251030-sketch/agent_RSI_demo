import numpy as np


def equation(x, v, params):
    k = params[0]
    c = params[1]
    d = params[2]
    c2 = params[3]
    d2 = params[4]
    return -k * x - c * v - d * x ** 3 - c2 * v * np.abs(v) - d2 * x ** 5