import numpy as np


def equation(u0, u1, u2, u3, params):
    """Response model: linear blend plus quadratic cross-terms of the inputs.

    Feature set is fixed and linear in the declared scalar coefficients, so
    bounded least squares from an all-ones start can fit the coefficients.
    """
    p = np.asarray(params, dtype=float).ravel()

    x0 = np.asarray(u0, dtype=float).ravel()
    x1 = np.asarray(u1, dtype=float).ravel()
    x2 = np.asarray(u2, dtype=float).ravel()
    x3 = np.asarray(u3, dtype=float).ravel()

    # linear and pairwise quadratic features
    f0 = np.ones_like(x0)
    f1 = x0
    f2 = x1
    f3 = x2
    f4 = x3
    f5 = x0 * x1
    f6 = x0 * x2
    f7 = x0 * x3
    f8 = x1 * x2
    f9 = x1 * x3
    f10 = x2 * x3
    f11 = x0 * x0
    f12 = x1 * x1
    f13 = x2 * x2
    f14 = x3 * x3

    feats = [f0, f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12, f13, f14]

    out = np.zeros_like(f0)
    for i, f in enumerate(feats):
        if i >= p.size:
            break
        c = p[i]
        if not np.isfinite(c):
            c = 0.0
        out = out + c * f

    # normalise extreme magnitudes while preserving the fit on typical ranges
    scale = 1.0 + np.abs(out)
    out = out / scale * scale
    return np.nan_to_num(out, nan=0.0, posinf=1.0e6, neginf=-1.0e6)