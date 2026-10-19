"""Candidate-side planning worker; invoke only inside the controller sandbox."""


def prepare_runtime():
    """Planning requires no third-party imports before sandbox restrictions."""


def run(source, request):
    """Execute candidate source in the sandbox and return its untrusted plan.

    This function does not establish isolation itself. The host must never call
    it with untrusted source outside the sandbox bootstrap. It returns no score.
    """
    scope = {"__name__": "candidate"}
    try:
        exec(compile(source, "candidate.py", "exec"), scope)
        function = scope.get("get_plan")
        if not callable(function):
            return {"status": "candidate_error", "error_kind": "missing_get_plan"}
        plan = function(
            {tuple(pair) for pair in request["objects"]},
            {tuple(atom) for atom in request["init"]},
            {tuple(atom) for atom in request["goal"]},
        )
        # Preserve bounded, JSON-safe malformed output for trusted host checks.
        # Never serialize custom objects: their repr/properties may execute code.
        if type(plan) is not list:
            return {"status": "ok", "plan": None}
        if len(plan) > 1000:
            return {"status": "candidate_error", "error_kind": "plan_too_long"}
        if any(type(action) is not str or len(action) > 4096 for action in plan):
            return {"status": "candidate_error", "error_kind": "invalid_plan_items"}
        return {"status": "ok", "plan": plan}
    except MemoryError:
        # The outer bootstrap owns resource-limit classification.
        raise
    except Exception as exc:
        candidate_line = None
        traceback = exc.__traceback__
        while traceback is not None:
            if traceback.tb_frame.f_code.co_filename == "candidate.py":
                candidate_line = traceback.tb_lineno
            traceback = traceback.tb_next
        return {"status": "candidate_error", "error_kind": "python_exception",
                "exception_type": type(exc).__name__, "candidate_line": candidate_line}
