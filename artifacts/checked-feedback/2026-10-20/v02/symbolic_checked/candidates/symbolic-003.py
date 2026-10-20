import numpy as np


def equation(x, v, params):
    # Harmonic-oscillator structure with a cubic position correction:
    # a = p0*x + p1*v + p2*x^3
    return params[0] * x + params[1] * v + params[2] * x * x * x

n_params = 3