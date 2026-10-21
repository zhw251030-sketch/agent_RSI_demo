import numpy as np


def equation(u0, u1, u2, params):
    """Revised hypothesis: quadratic response plus mild saturating corrections.

    Compared with the previous version the rarely-active cubic cross term is
    replaced by an additive square of the summed pair-products, and the
    saturating corrections use a single shared slope plus a bounded
    quadratic-in-u0 radial damping term. The parameter order and count
    (15) are unchanged so the host bounded least-squares fit stays identical
    in form.

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

    cross = u0 * u1 + u1 * u2 + u0 * u2

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
        + p[10] * cross * cross
        + p[11] * np.tanh(p[12] * u1)
        + p[13] * u0 * u2 * np.tanh(p[14] * u2)
    )

    return np.nan_to_num(y, nan=0.0, posinf=1e6, neginf=-1e6)