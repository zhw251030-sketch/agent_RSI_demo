import numpy as np


def equation(x, v, params):
    # Damped oscillator with quadratic-velocity nonlinearity (cubic-like restoring)
    # Adds p3 * v * |v| term to address elevated RMSE and alternating residuals in v-bins.
    p0, p1, p2, p3 = params[0], params[1], params[2], params[3]
    return -p0 * x - p1 * v + p2 + p3 * v * np.abs(v)