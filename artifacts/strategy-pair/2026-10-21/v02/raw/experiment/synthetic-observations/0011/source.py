import numpy as np


def equation(u0, u1, u2, params):
    """Initial hypothesis: smooth quadratic-plus-interaction scalar response.

    y = p0
        + p1*u0 + p2*u1 + p3*u2
        + p4*u0*u1 + p5*u0*u2 + p6*u1*u2
        + p7*u0**2 + p8*u1**2 + p9*u2**2
        + p10*u1*u2*u0
    with an optional saturating correction  p11 * tanh(p12 * u1)
    and a mild radial damping  p13 * tanh(p14 * u0) * u2.

    Returns
    -------
    numpy.ndarray, shape (len(u0),)
        Finite scalar response for each row.
    """
    u0 = np.asarray(u0, dtype=float).ravel()
    u1 = np.asarray(u1, dtype=float).ravel()
    u2 = np.asarray(u2, dtype=float).ravel()

    p = np.asarray(params, dtype=float).ravel()
    # Pad short parameter vectors so the expression stays well defined.
    if p.size < 15:
        p = np.concatenate([p, np.zeros(15 - p.size)])

    y = (
        p[0]
        + p[1] * u0
        + p[2] * u1
        + p[3] * u2
        + p[4] * u0 * u1
        + p[5] * u0 * u2
        + p[6] * u1 * u2
        + p[7] * u0 * u0
        + p[8] * u1 * u1
        + p[9] * u2 * u2
        + p[10] * u0 * u1 * u2
        + p[11] * np.tanh(p[12] * u1)
        + p[13] * np.tanh(p[14] * u0) * u2
    )

    return np.nan_to_num(y, nan=0.0, posinf=1e6, neginf=-1e6)
