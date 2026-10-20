import numpy as np


def equation(x, v, params):
    # Classical damped oscillator form: a ≈ -k*x - c*v
    p0, p1 = params[0], params[1]
    return -p0 * x - p1 * v
