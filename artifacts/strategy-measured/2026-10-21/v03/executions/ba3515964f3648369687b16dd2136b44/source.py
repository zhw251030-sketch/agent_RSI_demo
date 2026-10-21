import numpy as np


def equation(u0, u1, u2, params):
    """Expanded polynomial-in-scaled-input response; strictly linear in params."""
    u0 = np.asarray(u0, dtype=float)
    u1 = np.asarray(u1, dtype=float)
    u2 = np.asarray(u2, dtype=float)

    c = np.asarray(params, dtype=float).ravel()
    n = c.size

    c0 = c[0] if n > 0 else 0.0
    c1 = c[1] if n > 1 else 0.0
    c2 = c[2] if n > 2 else 0.0
    c3 = c[3] if n > 3 else 0.0
    c4 = c[4] if n > 4 else 0.0
    c5 = c[5] if n > 5 else 0.0
    c6 = c[6] if n > 6 else 0.0
    c7 = c[7] if n > 7 else 0.0
    c8 = c[8] if n > 8 else 0.0
    c9 = c[9] if n > 9 else 0.0
    c10 = c[10] if n > 10 else 0.0
    c11 = c[11] if n > 11 else 0.0
    c12 = c[12] if n > 12 else 0.0
    c13 = c[13] if n > 13 else 0.0

    s0 = 1.0 + c1 * u0
    s1 = 1.0 + c2 * u1
    s2 = 1.0 + c3 * u2

    core = (c0
            + c4 * u0
            + c5 * u1
            + c6 * u2
            + c7 * u0 * u1
            + c8 * u0 * u2
            + c9 * u1 * u2
            + c10 * u0 * u0
            + c11 * u1 * u1
            + c12 * u2 * u2
            + c13 * u0 * u1 * u2)

    out = core * s0 * s1 * s2

    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)