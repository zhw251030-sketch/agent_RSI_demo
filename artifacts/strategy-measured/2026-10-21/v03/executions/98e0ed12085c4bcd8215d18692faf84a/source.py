import numpy as np


def equation(u0, u1, params):
    """Bilinear-plus-quadratic hypothesis with bounded scale and offset."""
    u0 = np.asarray(u0, dtype=float).ravel()
    u1 = np.asarray(u1, dtype=float).ravel()

    p = np.asarray(params, dtype=float).ravel()

    c01 = p[0]        # cross term
    q0 = p[1]         # curvature in u0
    q1 = p[2]         # curvature in u1
    l0 = p[3]         # u0 scale
    l1 = p[4]         # u1 scale
    g = p[5]          # overall gain
    b = p[6]          # offset

    x0 = l0 * u0
    x1 = l1 * u1

    y = g * (c01 * x0 * x1 + q0 * x0 ** 2 + q1 * x1 ** 2) + b
    return np.nan_to_num(y, nan=0.0, posinf=1e6, neginf=-1e6)