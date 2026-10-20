import numpy as np


def equation(x, v, params):
    # Nonlinear spring-damper (Duffing-like): a = c1*x + c2*v + c3*x^3
    # Linear fit left 99% of MSE as variance (bias^2/MSE=0.0098), with the
    # largest residual RMSE in the high-|v| bin, suggesting a missing
    # higher-order restoring force. A cubic stiffness term is the standard
    # next-order physical correction.
    c1 = params[0]
    c2 = params[1]
    c3 = params[2]
    return c1 * x + c2 * v + c3 * x ** 3