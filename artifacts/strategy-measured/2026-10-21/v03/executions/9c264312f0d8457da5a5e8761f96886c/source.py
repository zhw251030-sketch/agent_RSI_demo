import numpy as np


def equation(u0, u1, params):
    """Linear + quadratic + cross-term model with bounded output scaling."""
    u0 = np.asarray(u0, dtype=float).ravel()
    u1 = np.asarray(u1, dtype=float).ravel()

    p = np.asarray(params, dtype=float).ravel()

    a0 = p[0]   # linear in u0
    a1 = p[1]   # linear in u1
    q0 = p[2]   # curvature in u0
    q1 = p[3]   # curvature in u1
    c01 = p[4]  # cross term
    g = p[5]    # overall gain
    b = p[6]    # offset
    s = p[7]    # residual symmetric scale (kept multiplicative on deviation)

    a = 0.5 * (u0 + u1)
    d = 0.5 * (u0 - u1)

    inner = (g * (a0 * u0 + a1 * u1 + q0 * u0 * u0 + q1 * u1 * u1
                  + c01 * u0 * u1) + b)
    y = inner + s * (a * a - d * d)

    return np.nan_to_num(y, nan=0.0, posinf=1e6, neginf=-1e6)