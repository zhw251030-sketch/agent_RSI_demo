import numpy as np


def equation(x, v, params):
    # Odd-symmetric restoring force + linear/quadratic damping:
    #   a = c1*x + c3*x^3 + c5*x^5 + c2*v + c4*v^2
    # Incumbent (linear + cubic) reaches train NMSE 0.0951, bias^2/MSE
    # only 0.0084 -> residual error is variance, not offset. Adding a
    # quintic stiffness term and a mild quadratic-in-v term to capture the
    # higher-|v| and higher-|x| growth seen in the binned RMSE.
    c1 = params[0]
    c2 = params[1]
    c3 = params[2]
    c4 = params[3]
    c5 = params[4]
    return c1 * x + c2 * v + c3 * x ** 3 + c4 * v ** 2 + c5 * x ** 5