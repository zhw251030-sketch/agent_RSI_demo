# Diagnostic comparison implementation plan

> For agentic workers: use the subagent-driven-development workflow for independent modules; the primary agent owns integration, actual runs and synchronization.

**Goal:** Build bounded diagnostic observations, verify previous failure explanations through explicit interventions, and execute one exploratory A/B/C comparison on each existing development task family.

**Architecture:** Preserve the existing sandbox and host scorers. Add planning replay and symbolic residual modules, bounded candidate tracing, and a separate comparison controller/runner that reuses the existing SDK and request ledger. Previous pilot artifacts remain immutable.

**Tech Stack:** Python 3.10 task runtime, Python 3.12/OpenHands 1.55.1, existing NumPy/SciPy and VAL; no new packages.

**Spec:** [Protocol](../protocols/2026-10-20-diagnostic-comparison.md).

## Constraints and decisions

- Authorized project checkout is the existing independent repository; preserve its GitHub/server synchronization. No unrelated worktree or directory migration is needed.
- 24 requests, four/session, three candidates/session; 4096 output tokens/request, 96 KiB input, 3000000 reserved tokens, 10 CNY. No automatic recovery this round.
- Planning diagnostics only for the two public prompt instances; symbolic diagnostics only train. All arms compute diagnostics, only B/C show them.
- C is an evidence-aware prompt intervention, not automatic causal verification or strategy self-rewriting.

## Tasks

- [x] Planning host replay: create `rsi_eval/planning_diagnostics.py`, tests `tests/test_planning_diagnostics.py`. Interface `is_public_prompt(task_id, root) -> bool`, `diagnose_plan(task_id, plan, root) -> dict`. Verify authorization before data access, typed actions/preconditions/effects, empty plans, limits, no candidate execution on host.
- [x] Symbolic residual summary: create `rsi_eval/symbolic_diagnostics.py`, tests `tests/test_symbolic_diagnostics.py`. Interface `summarize_residuals(X, y, predictions, input_names) -> dict`. Verify exact arithmetic examples, fixed/tied quartiles, nonfinite/overflow, bounded output/no sample rows.
- [x] Trace and executor integration: add bounded `rsi_eval/planning_trace.py`; planning worker uses it only when requested; executor `diagnostics=False` keeps old behavior. Only public planning tasks can request traces. Test truncation, exception handling, closed data boundaries and score equivalence.
- [x] Comparison controller and runner: add `rsi_eval/diagnostic_controller.py`, `scripts/run_diagnostic_comparison.py`, shared task prompts plus per-arm policy, JSON config. Reuse the SDK and ledger. Add tiny evaluation/feedback hooks to the old controller with default behavior unchanged. Test A hiding/B-C equal initial observations, session/task allowlists, all budget guards, no-key prepare, no overwrite, stop on provider/infra errors.
- [x] Offline interventions: create a deterministic no-model script that preserves originals, derives only declared patches, records hashes, runs original and modified candidates, and checks diagnostic/VAL agreement. Save all results, including unchanged failures.
- [x] Validate on the real server task and SDK environments. Freeze and synchronize implementation/config before the new paid comparison. Record all six sessions or honest partial results if stopped.
- [x] Review complete trajectories, evidence/cost accounting, references and limitations. Save user-facing explanation and reviewed evidence, update status and root navigation, push and verify all three Git heads.

## Interface review

Planning replay and symbolic residual modules only produce bounded observations and never decide candidate success. Executor binds observations to source/task; controller controls visibility. Trace is explicitly candidate-process evidence and cannot become a host score. Runner owns session IDs and budgets. Different modules have distinct files to permit parallel implementation; the primary agent alone edits executor/controller integration and runner.

Each code task starts with failing behavior tests, then the implementation, focused tests and review. Whole-server task/SDK tests run after integration; model calls happen only after those pass. Documentation-only updates do not trigger unnecessary repeated suites.

Execution note: the frozen six-session attempt ended as completed_with_stops after planning_B exceeded the input byte cap. Three later sessions have baseline checks only. This satisfies the planned honest-partial-results path, not completion of a full A/B/C experiment. No recovery or additional paid calls were made.
