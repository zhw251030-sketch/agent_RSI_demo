import numpy as np


def equation(u0, u1, params):
    """Same finite-real function family as stress-original-7, four direct coefficients."""
    u0 = np.asarray(u0, dtype=float).ravel()
    u1 = np.asarray(u1, dtype=float).ravel()

    p = np.asarray(params, dtype=float).ravel()
    # Parameter order: offset, cross term, square of u0, square of u1.
    y = p[0] + p[1] * u0 * u1 + p[2] * u0 ** 2 + p[3] * u1 ** 2
    return np.nan_to_num(y, nan=0.0, posinf=1e6, neginf=-1e6)
