# Replacement Agent Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate the runner that executes the frozen 12-slot replacement-sufficiency protocol without changing model weights, historical runs, or sealed evaluation data.

**Architecture:** A new additive runner loads only the frozen train split manifest, prepares one parent packet per slot, dispatches one OpenHands actor session, validates a keep/one-swap submission, evaluates parent/common/added structures through the locked symbolic sandbox on `fit_dev` then fixed-parameter `check_dev`, freezes the three gate conditions, and only then attaches `outcome_dev` shadow outcomes. FakeProvider mode exercises the exact control flow without network; real mode reads the existing credential only after all preflight checks pass.

**Tech Stack:** Python 3.12 on the Linux server, OpenHands SDK 1.55.1, existing `basis_trial_v02.sdk_controller`, symbolic basis compiler and locked sandbox, `pytest`, JSON/JSONL audit records.

**Spec:** `docs/experiments/2026-10-24-replacement-agent-round-protocol.md` and `docs/experiments/2026-10-24-replacement-evidence-design.md`.

## Global Constraints

- Use exactly two tasks, three fixed parent structures per task, two independent actor slots per parent, twelve maximum model requests.
- Read only the frozen public `train.csv` files and the row-index split manifest; never open official test, OOD, Spanner, or sealed paths.
- The actor submits only `feature_ids`; explanations are archived but never enter acceptance, evidence, or gate decisions.
- A candidate is valid only if it keeps the parent or replaces exactly one feature at fixed K; invalid submissions are recorded and never resampled.
- Fit parent/common/added on `fit_dev`; freeze parameters; predict on `check_dev` without targets in the prediction request; compute evidence before gates.
- Freeze all three gate rows and their hash before reading `outcome_dev`; shadow outcomes cannot modify gate decisions.
- Stop on the first unknown usage, transport failure, protocol error, or runtime-integrity failure; no retry or resume within this round.
- Do not update model weights, long-term strategy, or sealed evaluations.

---

### Task 1: Protocol audit artifact

**Files:**
- Create: `docs/analysis/2026-10-24-replacement-agent-round-review.md`
- Modify: `STATUS.md`

**Interfaces:**
- Consumes: frozen protocol, split report, evidence module, sandbox preflight, FakeProvider preflight.
- Produces: a checklist stating which protocol requirements are already evidenced and which are delegated to the new runner.

- [ ] Verify the exact 12 slot IDs, parent feature IDs, split hashes, thresholds, budget cap, and stop conditions against the protocol.
- [ ] Record that no real request is authorized by this artifact; runner preflight remains the next gate.
- [ ] Run a text-level consistency check that every planned runner stage has a corresponding output receipt.

### Task 2: Frozen data and structure adapters

**Files:**
- Create: `analysis/replacement_evidence/round_runner.py`
- Test: `tests/test_replacement_round_runner.py`

**Interfaces:**
- Consumes: `dev_splits` report, `compile_submission`, `sandbox_call`, `evaluate_triplet`, `build_edit`, and `bind_accepted_submission`.
- Produces: typed task/parent definitions, CSV split loader, feature-ID compiler, fit/predict callbacks, and candidate structural validator.

- [ ] Load the split report and verify source file hashes before selecting row indices.
- [ ] Convert only the requested split rows to numeric arrays with task-specific input names and target.
- [ ] Compile fixed parent structures and build the common structure by removing the proposed feature.
- [ ] Reject any candidate whose feature set is neither identical to the parent nor a one-for-one feature swap.
- [ ] Cache only immutable parent/common fit results within one run, keyed by source and split hash; never reuse a result across task or protocol hashes.

### Task 3: FakeProvider full 12-slot runner

**Files:**
- Modify: `scripts/run_replacement_agent_preflight.py` or add a dedicated `scripts/run_replacement_agent_round.py` fake mode.
- Test: `tests/test_replacement_round_runner.py`

**Interfaces:**
- Consumes: Task 2 adapters and the existing SDK controller.
- Produces: 12 actor session receipts, 36 frozen gate rows, frozen gate hash, synthetic outcome attachment, and budget summary.

- [ ] Use one synthetic response per slot and verify the provider call count equals 12.
- [ ] Run all fits before each candidate's check predictions, preserving `fit_dev -> check_dev` order.
- [ ] Assert `outcome_dev_read` is false until `freeze_gate_decisions` returns successfully.
- [ ] Execute the same candidate under all three conditions and report paired execution/retention counts.
- [ ] Test keep, supported swap, contradicted swap, invalid submission, fit failure, and prediction failure paths.

### Task 4: Server preflight and real-mode guard

**Files:**
- Modify: `scripts/run_replacement_agent_round.py`
- Create: `docs/environment/2026-10-24-replacement-agent-round-preflight.json`

**Interfaces:**
- Consumes: FakeProvider certificate, server auth path resolver, real model settings.
- Produces: a server-side preflight certificate and a guarded `--execute-real` entry point.

- [ ] Run the full fake 12-slot round on `13695090` under the existing `.venv`.
- [ ] Verify OpenHands SDK version 1.55.1, runtime lock, split hashes, and clean new run directory.
- [ ] Make real mode refuse to start unless the fake certificate and protocol review are present and valid.
- [ ] In real mode, read the existing auth file only in memory, use `num_retries=0`, and stop on the first unsettled usage or protocol error.
- [ ] Never print, copy, or commit the credential; store only safe hashes and counts.

### Task 5: Evidence report, tests, and synchronization

**Files:**
- Modify: `docs/analysis/2026-10-24-replacement-evidence-preflight.md`
- Modify: `README.md`
- Modify: `STATUS.md`
- Create: `docs/environment/2026-10-24-replacement-agent-round-verification.json`

**Interfaces:**
- Consumes: local/server test and preflight outputs.
- Produces: reproducible verification record and GitHub-synced commit.

- [ ] Run targeted unit tests, Python compilation, and the server fake-provider preflight.
- [ ] Record historical full-suite failures only as unrelated environment/legacy fixture limitations.
- [ ] Review the diff for credential leakage, sealed-data access, and accidental edits to historical archives.
- [ ] Commit and push the additive runner and evidence, then verify local/server/GitHub commit identity.

