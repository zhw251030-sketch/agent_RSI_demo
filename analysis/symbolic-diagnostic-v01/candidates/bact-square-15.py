import numpy as np


def equation(u0, u1, u2, u3, params):
    """Fixed 15-coefficient basis; common input conversion and finite-output guard."""
    p = np.asarray(params, dtype=float).ravel()

    u0 = np.asarray(u0, dtype=float).ravel()
    u1 = np.asarray(u1, dtype=float).ravel()
    u2 = np.asarray(u2, dtype=float).ravel()
    u3 = np.asarray(u3, dtype=float).ravel()

    k = min(15, p.size)
    out = np.zeros_like(u0 + u1 + u2 + u3)

    def coeff(i):
        if i < k:
            return p[i]
        return 0.0

    out = out + coeff(0)
    out = out + coeff(1) * u0
    out = out + coeff(2) * u1
    out = out + coeff(3) * u2
    out = out + coeff(4) * u3
    out = out + coeff(5) * u0 * u1
    out = out + coeff(6) * u0 * u2
    out = out + coeff(7) * u0 * u3
    out = out + coeff(8) * u1 * u2
    out = out + coeff(9) * u1 * u3
    out = out + coeff(10) * u2 * u3
    out = out + coeff(11) * u0 ** 2
    out = out + coeff(12) * u1 ** 2
    out = out + coeff(13) * u2 ** 2
    out = out + coeff(14) * u3 ** 2

    out = np.nan_to_num(out, nan=0.0, posinf=1.0e6, neginf=-1.0e6)
    return out
