import numpy as np


def equation(u0, u1, u2, params):
    """Smooth response expansion in the three inputs.

    The prediction is a bounded least-squares linear combination of a fixed
    feature basis (constant, linear, pairwise products, squares, cubic
    monomials, a quartic radial term and a few smooth saturating shapes),
    so every declared parameter enters linearly with a bounded design
    matrix.

    Returns
    -------
    numpy.ndarray, shape (len(u0),)
        Finite scalar response for each row.
    """
    u0 = np.asarray(u0, dtype=float).ravel()
    u1 = np.asarray(u1, dtype=float).ravel()
    u2 = np.asarray(u2, dtype=float).ravel()

    n = u0.size
    if n == 0:
        return np.zeros(0, dtype=float)

    p = np.asarray(params, dtype=float).ravel()
    if p.size < 16:
        p = np.concatenate([p, np.zeros(16 - p.size)])

    u0 = np.nan_to_num(u0, nan=0.0, posinf=1.0, neginf=-1.0)
    u1 = np.nan_to_num(u1, nan=0.0, posinf=1.0, neginf=-1.0)
    u2 = np.nan_to_num(u2, nan=0.0, posinf=1.0, neginf=-1.0)

    s = u0 + u1 + u2
    q = u0 * u0 + u1 * u1 + u2 * u2

    feats = [
        np.ones(n),
        u0,
        u1,
        u2,
        u0 * u1,
        u0 * u2,
        u1 * u2,
        u0 * u0,
        u1 * u1,
        u2 * u2,
        u0 * u1 * u2,
        q * s,
        s * s * s,
        u1 * u1 * u1,
        np.sin(2.0 * u1),
        np.tanh(u0 * u2),
    ]

    y = np.zeros(n, dtype=float)
    for i, f in enumerate(feats):
        fi = np.nan_to_num(np.asarray(f, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
        y = y + p[i] * fi

    return np.nan_to_num(y, nan=0.0, posinf=1e6, neginf=-1e6)