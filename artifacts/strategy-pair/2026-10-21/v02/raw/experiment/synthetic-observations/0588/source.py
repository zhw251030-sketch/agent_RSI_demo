import numpy as np


def equation(u0, u1, u2, u3, params):
    """Initial hypothesis: smooth quadratic response in the four inputs.

    Compact general form: a linear blend of the inputs plus a small
    quadratic cross-term, all with bounded scalar coefficients.
    """
    p = np.asarray(params, dtype=float).ravel()

    a0 = p[0]
    a1 = p[1]
    a2 = p[2]
    a3 = p[3]
    c01 = p[4]
    c23 = p[5]
    c012 = p[6]

    u0 = np.asarray(u0, dtype=float).ravel()
    u1 = np.asarray(u1, dtype=float).ravel()
    u2 = np.asarray(u2, dtype=float).ravel()
    u3 = np.asarray(u3, dtype=float).ravel()

    lin = a0 + a1 * u0 + a2 * u1 + a3 * u2
    quad = c01 * u0 * u1 + c23 * u2 * u3 + c012 * u0 * u1 * u2

    out = lin + quad

    # keep the response finite even for extreme inputs
    scale = 1.0 + np.abs(out)
    out = np.clip(out / scale, -1.0, 1.0) * scale
    return np.nan_to_num(out, nan=0.0, posinf=1.0e6, neginf=-1.0e6)