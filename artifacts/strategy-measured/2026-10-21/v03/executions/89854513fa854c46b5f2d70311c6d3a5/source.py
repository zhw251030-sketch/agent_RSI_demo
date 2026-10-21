import numpy as np


def equation(u0, u1, u2, params):
    """Compact hypothesis: bilinear + quadratic response in (u0, u1, u2)."""
    u0 = np.asarray(u0, dtype=float)
    u1 = np.asarray(u1, dtype=float)
    u2 = np.asarray(u2, dtype=float)

    c0 = params[0]
    c1 = params[1]
    c2 = params[2]
    c3 = params[3]
    c4 = params[4]
    c5 = params[5]
    c6 = params[6]
    c7 = params[7]

    s0 = 1.0 + c1 * u0
    s1 = 1.0 + c2 * u1
    s2 = 1.0 + c3 * u2

    out = (c0 + c4 * u0 + c5 * u1 + c6 * u2 + c7 * u0 * u1) * s0 * s1 * s2

    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)