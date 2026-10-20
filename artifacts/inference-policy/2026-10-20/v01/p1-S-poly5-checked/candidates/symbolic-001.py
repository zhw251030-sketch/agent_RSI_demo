import numpy as np


def equation(x, v, params):
    # Odd-symmetric restoring force (linear + cubic + quintic stiffness) plus
    # an odd-in-velocity cubic damping term:
    #   a = c1*x + c3*x^3 + c5*x^5 + c2*v + c4*v*|v|*|v|
    #
    # Observed train diagnostics for the incumbent (which used c4*v^2):
    # overall bias ~ 7.6e-05 and bias^2/MSE ~ 1.4e-05, so the error is
    # dominated by residual variance, not by a missing constant offset.
    # Per-bin mean residuals over the v bins alternate in sign
    # (-0.00246, +0.00421, -0.00149, +0.00005) rather than following a
    # monotone trend, which is a marginal association only; the physically
    # motivated response to a pattern like this is to keep the velocity
    # dependence odd (so no spurious constant force term is introduced) while
    # allowing its magnitude to grow faster than linear at large |v|.
    # The highest-|v| bin also carries the largest RMSE (0.0298), consistent
    # with a restoring/damping law that stiffens at higher speed.
    #
    # This is a training-fit hypothesis only; it does not establish held-out
    # accuracy or the true underlying equation.
    c1 = params[0]  # linear stiffness
    c2 = params[1]  # linear damping
    c3 = params[2]  # cubic stiffness
    c4 = params[3]  # cubic (odd) velocity damping
    c5 = params[4]  # quintic stiffness
    return c1 * x + c2 * v + c3 * x ** 3 + c5 * x ** 5 + c4 * v * np.abs(v) * np.abs(v)