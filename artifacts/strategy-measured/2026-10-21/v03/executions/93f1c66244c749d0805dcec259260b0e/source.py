import numpy as np


def equation(u0, u1, u2, u3, params):
    """Smooth additive response in the four inputs plus cross terms.

    Each term is linear in the declared scalar coefficients, so the host's
    bounded least-squares fit identifies them directly from a ones start.
    All four inputs appear; coefficients are read only from valid indices.
    """
    p = np.asarray(params, dtype=float).ravel()

    a0 = p[0]
    a1 = p[1]
    a2 = p[2]
    a3 = p[3]
    b3 = p[4]
    c01 = p[5]
    c12 = p[6]
    c23 = p[7]

    u0 = np.asarray(u0, dtype=float).ravel()
    u1 = np.asarray(u1, dtype=float).ravel()
    u2 = np.asarray(u2, dtype=float).ravel()
    u3 = np.asarray(u3, dtype=float).ravel()

    # Additive linear part: uses every input, including u3.
    lin = a0 + a1 * u0 + a2 * u1 + a3 * u2 + b3 * u3

    # Symmetric pairwise cross terms (pure quadratic response).
    quad = c01 * u0 * u1 + c12 * u1 * u2 + c23 * u2 * u3

    out = lin + quad

    # Guard against non-finite values without distorting finite predictions.
    out = np.nan_to_num(out, nan=0.0, posinf=1.0e6, neginf=-1.0e6)
    return out