import numpy as np


def equation(u0, u1, u2, u3, params):
    """Response model for four inputs.

    Hypothesis under test: the dominant structure is a bounded smooth
    function of the inputs, so a compact polynomial basis (constant, linear
    terms in all four inputs, and a few quadratic cross terms) plus a mild
    saturating compression should track the within-task training data better
    than the previous clipped blend.

    The previous version clipped its own output with a rescaling that is
    algebraically the identity but numerically lossy for large magnitudes, and
    it omitted u3 entirely from the linear part even though u3 is supplied as
    an input. Both are corrected here.
    """
    p = np.asarray(params, dtype=float).ravel()

    u0 = np.asarray(u0, dtype=float).ravel()
    u1 = np.asarray(u1, dtype=float).ravel()
    u2 = np.asarray(u2, dtype=float).ravel()
    u3 = np.asarray(u3, dtype=float).ravel()

    n = u0.shape[0]

    # Pad or truncate the parameter vector so every read index is valid.
    k = int(p.size)
    idx = np.arange(12) % k if k > 0 else np.zeros(12, dtype=int)

    a0 = p[idx[0]]
    a1 = p[idx[1]]
    a2 = p[idx[2]]
    a3 = p[idx[3]]
    b3 = p[idx[4]]
    c01 = p[idx[5]]
    c23 = p[idx[6]]
    c012 = p[idx[7]]
    d1 = p[idx[8]]
    d2 = p[idx[9]]
    e0 = p[idx[10]]
    e1 = p[idx[11]]

    lin = a0 + a1 * u0 + a2 * u1 + a3 * u2 + b3 * u3
    quad = c01 * u0 * u1 + c23 * u2 * u3 + c012 * u0 * u1 * u2
    sq = d1 * u0 * u0 + d2 * u2 * u2
    cross = e0 * u1 * u3 + e1 * u0 * u3

    out = lin + quad + sq + cross

    # Soft, monotone, invertible-in-range compression: only compress values
    # well outside the plausible response range, leaving small values
    # essentially linear so least-squares coefficients stay well conditioned.
    out = np.tanh(out / 8.0) * 8.0

    out = np.nan_to_num(out, nan=0.0, posinf=1.0e6, neginf=-1.0e6)
    if out.shape[0] != n:  # defensive shape guard
        out = np.resize(out, n)
    return out