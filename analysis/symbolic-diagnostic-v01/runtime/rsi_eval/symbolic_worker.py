"""Diagnostic-only successor; call only within the copied Linux sandbox worker.

Fit receives training targets; fresh-process predict receives only X and fitted
parameters. Reports from this process are untrusted until checked by the host.
The original fit algorithm is retained; diagnostics do not evaluate a candidate
or invoke the optimizer. No diagnostics are scores or acceptance decisions.
"""

np = None
least_squares = None


def prepare_runtime():
    """Load and warm numerical code before the sandbox restricts syscalls."""
    global np, least_squares
    import numpy as numpy_module
    from scipy.optimize import least_squares as scipy_least_squares
    np = numpy_module
    least_squares = scipy_least_squares
    # Exercise finite-difference Jacobian and linear algebra lazy imports before
    # seccomp. This is a synthetic fixture, not fitting any benchmark data.
    least_squares(lambda p: np.array([p[0] - 2, p[1] + 3, p[2] - 4, p.sum() - 3]),
                  np.ones(3), max_nfev=2)


class _CandidateError(Exception):
    def __init__(self, reason, details=None):
        super().__init__(reason)
        self.details = details or {}


def _exception_location(exc):
    """Diagnostic type/line only; exception messages can contain private values."""
    details = {"exception_type": type(exc).__name__[:80]}
    if isinstance(exc, SyntaxError) and exc.filename == "candidate.py":
        details["candidate_line"] = exc.lineno
    trace = exc.__traceback__
    while trace is not None:
        if trace.tb_frame.f_code.co_filename == "candidate.py":
            details["candidate_line"] = trace.tb_lineno
        trace = trace.tb_next
    return details


def _array(value, dimensions, reason):
    try:
        result = np.asarray(value)
    except (ValueError, TypeError):
        raise ValueError(reason) from None
    if result.ndim != dimensions or result.dtype.kind not in "iuf":
        raise ValueError(reason)
    result = result.astype(float, copy=False)
    if not np.all(np.isfinite(result)):
        raise ValueError("nonfinite_request")
    return result


def _finite_or_none(value):
    """Represent nonfinite optimizer metadata explicitly in finite JSON."""
    if value is None:
        return None
    result = float(value)
    return result if np.isfinite(result) else None


def run(source: str, request: dict) -> dict:
    """Fit or predict one candidate, returning no model-supplied fitness value."""
    if np is None or least_squares is None:
        raise RuntimeError("symbolic_runtime_not_preloaded")
    try:
        if not isinstance(source, str) or not isinstance(request, dict):
            raise ValueError("invalid_payload")
        phase = request.get("phase")
        if phase not in {"fit", "predict"}:
            raise ValueError("invalid_phase")
        X = _array(request.get("X"), 2, "invalid_input_shape_or_dtype")
        if X.shape[0] == 0 or X.shape[1] == 0:
            raise ValueError("empty_inputs")
        if phase == "fit":
            y = _array(request.get("y"), 1, "invalid_target_shape_or_dtype")
            if len(y) != len(X):
                raise ValueError("target_length_mismatch")
            n_params = request.get("n_params")
            if type(n_params) is not int or not 0 <= n_params <= 16:
                raise ValueError("invalid_parameter_count")
            params = np.ones(n_params)
        else:
            if "y" in request:
                raise ValueError("prediction_targets_refused")
            params = _array(request.get("params"), 1, "invalid_parameters")
            if len(params) > 16:
                raise ValueError("invalid_parameter_count")
    except (ValueError, TypeError, OverflowError) as exc:
        # Only our request diagnostics enter the response, never arbitrary input.
        reason = str(exc) if isinstance(exc, ValueError) else "invalid_payload"
        return {"status": "invalid_request", "error": reason}

    candidate_calls = 0
    diagnostics = {
        "version": "symbolic-fit-diagnostics-v0.1",
        "initial_params": params.tolist(),
        "optimizer_invocations": 0,
        "optimizer_returned": False,
        "optimizer_status": None,
        "optimizer_message": None,
        "optimizer_success": None,
        "nfev": None,
        "njev": None,
        "candidate_calls": 0,
        "optimizer_candidate_calls": 0,
        "postfit_confirmation_calls": 0,
        "final_params": None,
        "final_params_finite": None,
        "optimizer_cost": None,
        "optimality": None,
        "exception_type": None,
    }

    def finish(value):
        if phase == "fit":
            diagnostics["candidate_calls"] = candidate_calls
            if diagnostics["optimizer_invocations"]:
                diagnostics["optimizer_candidate_calls"] = (
                    candidate_calls - diagnostics["postfit_confirmation_calls"])
            value["diagnostics"] = dict(diagnostics)
        return value

    namespace = {"np": np, "__name__": "candidate"}
    try:
        exec(compile(source, "candidate.py", "exec"), namespace, namespace)
        equation = namespace.get("equation")
        if not callable(equation):
            raise _CandidateError("missing_equation")
    except _CandidateError as exc:
        return finish({"status": "candidate_error", "error": str(exc), **exc.details})
    except MemoryError:
        raise
    except Exception as exc:
        diagnostics["exception_type"] = type(exc).__name__[:80]
        return finish({"status": "candidate_error", "error": "execution_error", **_exception_location(exc)})

    columns = [X[:, index] for index in range(X.shape[1])]
    # Read-only prevents accidental in-place changes; OS sandboxing, not these
    # flags, establishes the execution boundary.
    for column in columns:
        column.setflags(write=False)

    def predict(parameters):
        nonlocal candidate_calls
        try:
            candidate_calls += 1
            with np.errstate(all="ignore"):
                values = np.asarray(equation(*columns, parameters))
        except MemoryError:
            raise
        except Exception as exc:
            raise _CandidateError("execution_error", _exception_location(exc)) from None
        if values.shape != (len(X),):
            raise _CandidateError("invalid_shape")
        if values.dtype.kind not in "iuf":
            raise _CandidateError("invalid_dtype")
        values = values.astype(float, copy=False)
        if not np.all(np.isfinite(values)):
            raise _CandidateError("nonfinite_output")
        return values

    try:
        if phase == "predict":
            return {"status": "success", "predictions": predict(params).tolist()}

        def residual(parameters):
            with np.errstate(all="ignore"):
                result = predict(parameters) - y
            if not np.all(np.isfinite(result)):
                raise _CandidateError("nonfinite_output")
            return result

        if len(params) == 0:
            residual(params)
            diagnostics.update(final_params=[], final_params_finite=True)
            return finish({"status": "success", "params": [], "converged": True, "nfev": 1,
                           "candidate_calls": candidate_calls})
        diagnostics["optimizer_invocations"] = 1
        result = least_squares(residual, params, max_nfev=100)
        diagnostics.update(
            optimizer_returned=True,
            optimizer_status=int(result.status),
            optimizer_message=str(result.message),
            optimizer_success=bool(result.success),
            nfev=int(result.nfev),
            njev=int(result.njev) if result.njev is not None else None,
            final_params=[_finite_or_none(value) for value in result.x],
            final_params_finite=bool(np.all(np.isfinite(result.x))),
            optimizer_cost=_finite_or_none(result.cost),
            optimality=_finite_or_none(result.optimality),
        )
        if not result.success or not np.all(np.isfinite(result.x)):
            raise _CandidateError("optimization_failed")
        # Confirm the fitted point still satisfies the complete prediction contract.
        diagnostics["postfit_confirmation_calls"] = 1
        predict(result.x)
        return finish({"status": "success", "params": result.x.tolist(),
                       "converged": bool(result.success), "nfev": int(result.nfev),
                       "candidate_calls": candidate_calls})
    except _CandidateError as exc:
        diagnostics["exception_type"] = exc.details.get("exception_type")
        return finish({"status": "candidate_error", "error": str(exc), **exc.details})
    except MemoryError:
        raise
    except Exception as exc:
        diagnostics["exception_type"] = type(exc).__name__[:80]
        return finish({"status": "candidate_error", "error": "optimization_failed"})
