import numpy as np


def equation(x, v, params):
    return (params[0] * x
            + params[1] * v
            + params[2] * x * x
            + params[3] * x * x * x
            + params[4] * v * v * v)