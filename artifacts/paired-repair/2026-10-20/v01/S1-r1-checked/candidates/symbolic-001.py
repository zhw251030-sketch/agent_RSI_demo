import numpy as np


def equation(x, v, params):
    # Linear restoring term plus amplitude-dependent damping on velocity.
    return -params[0] * x - params[1] * v - params[2] * np.abs(v)