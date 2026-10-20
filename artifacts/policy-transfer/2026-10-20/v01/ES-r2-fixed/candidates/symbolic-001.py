import numpy as np


def equation(x, v, params):
    # Damped oscillator with quadratic velocity correction
    p0, p1, p2 = params[0], params[1], params[2]
    return -p0 * x - p1 * v - p2 * v * v