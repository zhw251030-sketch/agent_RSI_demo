import numpy as np


def equation(x, v, params):
    # Nonlinear spring-damper: a = c1*x + c2*v + c3*x^3 + c4*x^5
    # The cubic term was confirmed necessary (removal raised train NMSE by
    # ~1.9e-3). Binned residuals show the largest RMSE in the high-|v| bin
    # and a mild x-dependent trend, consistent with a further odd restoring
    # term. A quintic stiffness term is the standard next-order correction
    # (Duffing-with-quintic softening), kept in the same odd-harmonic family.
    c1 = params[0]
    c2 = params[1]
    c3 = params[2]
    c4 = params[3]
    return c1 * x + c2 * v + c3 * x ** 3 + c4 * x ** 5