import numpy as np


def equation(u0, u1, u2, params):
    """Cubic-interaction scalar response fit by bounded least squares.

    Builds a polynomial basis in (u0, u1, u2) up to total degree 3 plus a
    saturating tanh correction, so the returned vector is finite for any
    finite inputs.

    Returns
    -------
    numpy.ndarray, shape (len(u0),)
        Finite scalar response for each row.
    """
    u0 = np.asarray(u0, dtype=float).ravel()
    u1 = np.asarray(u1, dtype=float).ravel()
    u2 = np.asarray(u2, dtype=float).ravel()

    p = np.asarray(params, dtype=float).ravel()
    if p.size < 16:
        p = np.concatenate([p, np.zeros(16 - p.size)])

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
        + p[15] * u0 * u0 * u0
    )

    return np.nan_to_num(y, nan=0.0, posinf=1e6, neginf=-1e6)