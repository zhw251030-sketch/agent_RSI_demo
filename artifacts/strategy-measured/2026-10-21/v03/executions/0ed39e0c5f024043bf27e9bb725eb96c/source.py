import numpy as np


def equation(u0, u1, u2, params):
    """Scalar response model for a three-input nonlinear system.

    Hypothesis (unverified beyond the provided training fit): the response is a
    smooth function of the three inputs, so a low-order polynomial plus a few
    saturating corrections is used as a general-purpose basis:

        linear + quadratic + a single cubic interaction
        + an optional tanh correction in u1
        + an optional tanh*u2 cross damping term.

    All coefficients are free parameters and are fitted by the host, so this
    is a flexible hypothesis rather than an assertion about which terms matter.

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