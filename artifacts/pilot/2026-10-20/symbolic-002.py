import numpy as np


def equation(x, v, params):
    k = params[0]
    c = params[1]
    d = params[2]
    return -k * x - c * v - d * x ** 3
