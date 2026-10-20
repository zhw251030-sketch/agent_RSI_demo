import numpy as np


def equation(x, v, params):
    # Linear spring-damper: a = c1 * x + c2 * v
    # Fitted constants; physically motivated harmonic oscillator structure.
    c1 = params[0]
    c2 = params[1]
    return c1 * x + c2 * v