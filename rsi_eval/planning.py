"""Trusted host adapter for the pinned Spanner typed-STRIPS task subset.

This is deliberately not a general PDDL parser or PDDLGym replacement. Only
typed objects, a type hierarchy, positive conjunctive preconditions/goals, and
positive/negative STRIPS effects are accepted. VAL remains the final authority.
Candidate Python is never imported or executed in this host module.
"""

import hashlib
import json
from pathlib import Path
import re
import tempfile

from scripts.check_planning_data import PDDL_PREFIX, VAL_DIRECTORY, VAL_HASHES, run_val, safe_file


ALLOWED_ROLES = frozenset({"prompt", "development_feedback"})
MAX_ACTIONS = 1000
_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
_VARIABLE = re.compile(r"^\?[a-z][a-z0-9_-]*$")


def _expression(text):
    """Read one bounded, case-insensitive S-expression, rejecting extra roots."""
    text = re.sub(r";[^\r\n]*", "", text).lower()
    tokens = re.findall(r"\(|\)|[^\s()]+", text)
    if not tokens or len(tokens) > 100000:
        raise ValueError("Missing or oversized PDDL expression")
    stack = []
    root = None
    for token in tokens:
        if token == "(":
            if len(stack) >= 100:
                raise ValueError("PDDL nesting limit exceeded")
            node = []
            if stack:
                stack[-1].append(node)
            elif root is not None:
                raise ValueError("Multiple PDDL roots")
            else:
                root = node
            stack.append(node)
        elif token == ")":
            if not stack:
                raise ValueError("Unbalanced PDDL parentheses")
            stack.pop()
        elif not stack:
            raise ValueError("PDDL atom outside root")
        else:
            stack[-1].append(token)
    if stack or not root:
        raise ValueError("Unbalanced or empty PDDL expression")
    return root


def _typed(tokens, variables=False):
    """Parse grouped PDDL type annotations into an insertion-ordered mapping."""
    result, pending = {}, []
    index = 0
    pattern = _VARIABLE if variables else _NAME
    while index < len(tokens):
        token = tokens[index]
        if not isinstance(token, str):
            raise ValueError("Unsupported nested type declaration")
        if token == "-":
            if not pending or index + 1 >= len(tokens):
                raise ValueError("Malformed type declaration")
            kind = tokens[index + 1]
            if not isinstance(kind, str) or not _NAME.fullmatch(kind):
                raise ValueError("Unsupported type name")
            result.update((name, kind) for name in pending)
            pending = []
            index += 2
            continue
        if not pattern.fullmatch(token) or token in result or token in pending:
            raise ValueError("Invalid or duplicate typed symbol")
        pending.append(token)
        index += 1
    result.update((name, "object") for name in pending)
    return result


def _subtype(actual, required, types):
    seen = set()
    while actual is not None and actual not in seen:
        if actual == required:
            return True
        seen.add(actual)
        actual = types.get(actual)
    return False


def _atom(value, predicates, symbols, types):
    if not isinstance(value, list) or not value or any(not isinstance(x, str) for x in value):
        raise ValueError("Unsupported non-atomic PDDL formula")
    predicate, *args = value
    if predicate not in predicates or len(args) != len(predicates[predicate]):
        raise ValueError("Unknown predicate or wrong arity")
    for arg, required in zip(args, predicates[predicate]):
        if arg not in symbols or not _subtype(symbols[arg], required, types):
            raise ValueError("Unknown symbol or wrong predicate argument type")
    return tuple(value)


def _conjunction(value, predicates, symbols, types, allow_negative=False):
    if not isinstance(value, list) or not value:
        raise ValueError("Missing PDDL formula")
    items = value[1:] if value[0] == "and" else [value]
    result = []
    for item in items:
        negative = isinstance(item, list) and bool(item) and item[0] == "not"
        if negative:
            if not allow_negative or len(item) != 2:
                raise ValueError("Unsupported negative PDDL formula")
            item = item[1]
        result.append((negative, _atom(item, predicates, symbols, types)))
    return result


def parse_domain(text):
    """Parse the supported Spanner domain and reject unsupported PDDL features."""
    form = _expression(text)
    if len(form) < 3 or form[0] != "define" or form[1] != ["domain", "spanner"]:
        raise ValueError("Only the Spanner domain is supported")
    sections, actions = {}, []
    for section in form[2:]:
        if not isinstance(section, list) or not section or not isinstance(section[0], str):
            raise ValueError("Malformed domain section")
        label = section[0]
        if label == ":action":
            actions.append(section)
        elif label not in {":requirements", ":types", ":predicates"} or label in sections:
            raise ValueError("Unsupported or duplicate domain section")
        else:
            sections[label] = section[1:]
    if set(sections) != {":requirements", ":types", ":predicates"}:
        raise ValueError("Missing typed STRIPS domain section")
    if set(sections[":requirements"]) != {":typing", ":strips"}:
        raise ValueError("Only :typing and :strips are supported")
    types = {"object": None, **_typed(sections[":types"])}
    if types["object"] is not None:
        raise ValueError("Cannot redefine object type")
    for name in types:
        seen, current = set(), name
        while current is not None:
            if current in seen or current not in types:
                raise ValueError("Unknown parent type or cyclic type hierarchy")
            seen.add(current)
            current = types[current]
    predicates = {}
    for declaration in sections[":predicates"]:
        if not isinstance(declaration, list) or not declaration or not isinstance(declaration[0], str):
            raise ValueError("Malformed predicate declaration")
        name = declaration[0]
        if not _NAME.fullmatch(name) or name in predicates or name in {"and", "or", "not", "forall", "exists", "when"}:
            raise ValueError("Invalid or duplicate predicate")
        signature = list(_typed(declaration[1:], variables=True).values())
        if any(kind not in types for kind in signature):
            raise ValueError("Unknown predicate argument type")
        predicates[name] = signature
    operators = {}
    for declaration in actions:
        if len(declaration) != 8 or not isinstance(declaration[1], str):
            raise ValueError("Unsupported action structure")
        name = declaration[1]
        if not _NAME.fullmatch(name) or name in operators:
            raise ValueError("Invalid or duplicate action")
        pairs = declaration[2:]
        if pairs[::2] != [":parameters", ":precondition", ":effect"] or not isinstance(pairs[1], list):
            raise ValueError("Unsupported action fields or order")
        parameters = _typed(pairs[1], variables=True)
        if any(kind not in types for kind in parameters.values()):
            raise ValueError("Unknown action parameter type")
        preconditions = _conjunction(pairs[3], predicates, parameters, types)
        effects = _conjunction(pairs[5], predicates, parameters, types, allow_negative=True)
        operators[name] = {"parameters": parameters, "preconditions": preconditions, "effects": effects}
    if not operators:
        raise ValueError("No supported actions")
    return {"name": "spanner", "types": types, "predicates": predicates, "operators": operators}


def parse_problem(text, domain):
    """Return typed objects and ground init/goal atoms for the supported subset."""
    form = _expression(text)
    if (len(form) != 6 or form[0] != "define" or not isinstance(form[1], list)
            or len(form[1]) != 2 or form[1][0] != "problem"
            or not isinstance(form[1][1], str) or not _NAME.fullmatch(form[1][1])):
        raise ValueError("Unsupported problem structure")
    sections = {}
    for section in form[2:]:
        if (not isinstance(section, list) or not section or not isinstance(section[0], str)
                or section[0] not in {":domain", ":objects", ":init", ":goal"}
                or section[0] in sections):
            raise ValueError("Unsupported or duplicate problem section")
        sections[section[0]] = section[1:]
    if set(sections) != {":domain", ":objects", ":init", ":goal"} or sections[":domain"] != [domain["name"]]:
        raise ValueError("Missing problem section or mismatched domain")
    objects = _typed(sections[":objects"])
    if any(kind not in domain["types"] for kind in objects.values()):
        raise ValueError("Unknown object type")
    init = {_atom(item, domain["predicates"], objects, domain["types"]) for item in sections[":init"]}
    if len(sections[":goal"]) != 1:
        raise ValueError("Expected one goal formula")
    goal = {atom for _, atom in _conjunction(sections[":goal"][0], domain["predicates"], objects, domain["types"])}
    return {"objects": objects, "init": init, "goal": goal}


def _load_task(task_id, root):
    root = Path(root).resolve()
    manifest = json.loads((root / "configs/tasks/planning-spanner-v0.1.json").read_text(encoding="utf-8"))
    matches = [task for task in manifest["tasks"] if task["id"] == task_id]
    if len(matches) != 1:
        raise ValueError("Unknown or ambiguous planning task")
    entry = matches[0]
    if entry.get("pilot_role") not in ALLOWED_ROLES:
        raise PermissionError("Task role is not available to the development evaluator")
    paths, texts = [], []
    for item in (manifest["domain"], entry):
        upstream = item["upstream_path"]
        if not upstream.startswith(PDDL_PREFIX):
            raise ValueError("Unexpected planning data prefix")
        path = safe_file(root / "data/planning/spanner", upstream[len(PDDL_PREFIX):])
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise ValueError("Planning source integrity mismatch")
        paths.append(path)
        texts.append(content.decode("utf-8"))
    domain = parse_domain(texts[0])
    return domain, parse_problem(texts[1], domain), paths


def prepare_task(task_id, root):
    """Load only a hash-verified prompt/development task, returning public inputs."""
    _, task, _ = _load_task(task_id, root)
    return {"family": "planning", "task_id": task_id,
            "objects": [list(pair) for pair in sorted(task["objects"].items())],
            "init": [list(atom) for atom in sorted(task["init"])],
            "goal": [list(atom) for atom in sorted(task["goal"])]}


def _result(status, error_kind, diagnostic, plan_length=None, **extra):
    return {"status": status, "error_kind": error_kind, "public_diagnostic": diagnostic,
            "plan_length": plan_length, **extra}


def validate_plan(task_id, plan, root):
    """Validate candidate output on the host; only trusted VAL can mark success."""
    try:
        domain, task, paths = _load_task(task_id, root)
    except (OSError, ValueError, KeyError, TypeError):
        return _result("infrastructure_error", "task_data", "Task authorization, integrity, or parsing failed.")
    if type(plan) is not list:
        return _result("invalid_output", "output_not_plan", "get_plan must return a list of action strings.")
    if len(plan) > MAX_ACTIONS:
        return _result("invalid_output", "plan_too_long", "Plan exceeds the 1000-action limit.", len(plan))
    normalized = []
    for index, action in enumerate(plan):
        def invalid(kind, message):
            return _result("invalid_output", kind, message, len(plan), first_invalid_action=index)
        if type(action) is not str or len(action) > 4096 or not re.fullmatch(r"\s*\([a-zA-Z][a-zA-Z0-9_-]*(?:\s+[a-zA-Z][a-zA-Z0-9_-]*)*\)\s*", action):
            return invalid("operator_syntax", "Action must be one parenthesized grounded operator.")
        tokens = action.strip()[1:-1].lower().split()
        operator, *args = tokens
        if operator not in domain["operators"]:
            return invalid("unknown_operator", "Action names an operator absent from the domain.")
        kinds = list(domain["operators"][operator]["parameters"].values())
        if len(args) != len(kinds):
            return invalid("operator_arity", "Action has the wrong number of arguments.")
        for arg, required in zip(args, kinds):
            if arg not in task["objects"]:
                return invalid("unknown_object", "Action references an object absent from this task.")
            if not _subtype(task["objects"][arg], required, domain["types"]):
                return invalid("object_type", "Action argument has an incompatible object type.")
        normalized.append("(" + " ".join(tokens) + ")")
    val_dir = Path(root).resolve() / "vendor/llm-genplan" / VAL_DIRECTORY
    try:
        if any(hashlib.sha256((val_dir / name).read_bytes()).hexdigest() != expected for name, expected in VAL_HASHES.items()):
            raise ValueError("Validator integrity mismatch")
    except (OSError, ValueError):
        return _result("infrastructure_error", "validator_integrity", "Trusted validator files are missing or fail integrity verification.", len(plan))
    try:
        scratch_parent = Path(root).resolve() / "tmp"
        scratch_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="planning-eval-", dir=scratch_parent) as directory:
            observed = run_val(val_dir / "Validate", paths[0], paths[1], normalized, Path(directory), "candidate", 10.0)
    except OSError:
        return _result("infrastructure_error", "validator_io", "Validator temporary files could not be prepared.", len(plan))
    if observed["status"] == "valid":
        status, kind, diagnostic = "success", None, "VAL verified that every action is valid and the goal is reached."
    elif observed["status"] == "invalid":
        status, kind, diagnostic = "task_failure", "plan_semantics", "VAL rejected the plan: an action precondition or final goal is unsatisfied."
    else:
        status, kind, diagnostic = "infrastructure_error", observed["reason"], "The trusted validator did not produce a usable semantic verdict."
    return _result(status, kind, diagnostic, len(plan), validator=observed)
