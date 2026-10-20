# Checked feedback implementation plan

Goal: repair whole-input growth and run a focused feedback-visibility comparison with executable, narrowly scoped predicates. Specification: [frozen protocol](../protocols/2026-10-20-checked-feedback.md).

Existing authorization covers implementation, bounded experiments and continuous private GitHub/server synchronization. The clean project checkout is already isolated from the literature workspace. Preserve all old runs.

1. Pure stdlib checker (`rsi_eval/evidence_checks.py`, dedicated tests): full identity binding, fact/scalar claims, preregistered before/after predictions, four statuses, tolerance and malformed/missing-data tests. Independent agent owns these two files.
2. Deterministic packet (`rsi_eval/state_packet.py`, dedicated tests): one incumbent source, compact failed/latest records, host diagnostics, check visibility, replace all non-system history; test escaped byte sizes and no hidden outcomes. Separate agent owns these two files.
3. Trusted evidence adapter/controller (`rsi_eval/checked_controller.py`, tests): public PDDL atoms and training aggregates; persist claims/predictions before execution, check actual child even when rejected, preserve original scoring and task bounds. Primary agent owns integration.
4. SDK adapter (`rsi_eval/checked_agent.py`) and minimal optional factory seam in old SDK adapter; new frozen runner/config/prompt. Exact denial metadata before transport; no key in reports. New tests cover real SDK mocked transport and all four state transitions.
5. Offline server verification: full appropriate task/SDK suites, old saved-response SDK replay and bounded source stress. No model call during validation. Freeze implementation commit, push and fast-forward server via bundle; verify hashes.
6. New 16-request maximum run, no retries/recovery. Collect all sessions and failures, inspect claim coverage and prediction outcomes, preserve safe artifacts, write Chinese file-based explanation.
7. Independent review, update project/root status only where evidence changed, push and verify local/GitHub/server agreement.

Tests precede relevant implementation and exercise meaningful boundaries. No new dependencies. Runtime versions, data permissions and prior immutable run limits stay as recorded. A stop is an outcome to report, not a reason to extend the frozen trial.
