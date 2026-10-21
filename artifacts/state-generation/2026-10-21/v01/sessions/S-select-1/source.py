import numpy as np

def equation(u0, u1, u2, params):
    # Initial hypothesis: a compact, general nonlinear combination of the
    # three inputs with a few adjustable scalar constants. Not a claimed
    # relationship; parameters are placeholders for later fitting.
    a = params[0]
    b = params[1]
    c = params[2]
    d = params[3]
    e = params[4]
    f = params[5]

    x = u0
    y = u1
    z = u2

    expr = (
        a * x
        + b * y
        + c * z
        + d * np.sin(x)
        + e * np.cos(y)
        + f * (x * y + y * z + z * x)
    )
    return np.asarray(expr, dtype=float)
