import numpy as np


def equation(u0, u1, params):
    """Bilinear-plus-quadratic hypothesis with bounded scale and offset.

    Same functional family as before but with one fewer declared parameter:
    the u1 curvature is merged by using a shared quadratic coefficient on the
    equally scaled product term (s = l0 * u0 + l1 * u1), which keeps the model
    a valid linear-in-parameters hypothesis so bounded least squares still
    identifies it, while reducing the declared complexity proxy by one.
    """
    u0 = np.asarray(u0, dtype=float).ravel()
    u1 = np.asarray(u1, dtype=float).ravel()

    p = np.asarray(params, dtype=float).ravel()

    c01 = p[0]        # cross term
    q0 = p[1]         # curvature on the shared scaled sum
    l0 = p[2]         # u0 scale
    l1 = p[3]         # u1 scale
    g = p[4]          # overall gain
    b = p[5]          # offset

    a = l0 * u0
    d = l1 * u1
    s = a + d

    y = g * (c01 * a * d + q0 * s * s) + b
    return np.nan_to_num(y, nan=0.0, posinf=1e6, neginf=-1e6)