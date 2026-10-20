import numpy as np

def equation(x, v, params):
    return params[0] * x + params[1] * v + params[2] * x ** 3 + params[3] * v ** 2 + params[4] * x ** 5
