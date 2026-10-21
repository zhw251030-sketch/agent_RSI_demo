import numpy as np


def equation(u0, u1, u2, params):
    """Bilinear baseline: linear-in-params core times per-input affine gains."""
    u0 = np.asarray(u0, dtype=float)
    u1 = np.asarray(u1, dtype=float)
    u2 = np.asarray(u2, dtype=float)

    c0, c1, c2, c3, c4, c5, c6, c7 = [float(p) for p in params[:8]]

    s0 = 1.0 + c1 * u0
    s1 = 1.0 + c2 * u1
    s2 = 1.0 + c3 * u2

    out = (c0 + c4 * u0 + c5 * u1 + c6 * u2 + c7 * u0 * u1) * s0 * s1 * s2

    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)