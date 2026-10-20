import numpy as np


def equation(x, v, params):
    # Odd-symmetric restoring force (x, x^3, x^5) plus velocity-dependent
    # damping (v, v^2, v^3):
    #   a = c1*x + c2*v + c3*x^3 + c4*v^2 + c5*x^5 + c6*v^3
    # The parent (5-term) version reaches train NMSE 0.0938 with
    # bias^2/MSE ~ 1.4e-5, so the residual is almost pure variance.
    # Binned RMSE is worst at high |v| (0.0298) and at the extreme |x| bins
    # (~0.023), suggesting unmodeled amplitude-dependent behavior in both
    # channels. Rather than adding more stiffness terms (which grow as
    # x^7 for large amplitude and can be unstable), the cheapest remaining
    # independent shape is a cubic-in-velocity term, which lets the damping
    # change sign with velocity and can capture the non-monotonic
    # v-residual pattern without touching the restoring part.
    c1 = params[0]
    c2 = params[1]
    c3 = params[2]
    c4 = params[3]
    c5 = params[4]
    c6 = params[5]
    return c1 * x + c2 * v + c3 * x ** 3 + c4 * v ** 2 + c5 * x ** 5 + c6 * v ** 3