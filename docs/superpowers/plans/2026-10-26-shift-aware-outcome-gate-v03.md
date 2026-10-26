# Shift-aware outcome gate v03 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 shift-aware v02 的 host-only shift gate 后增加一个开发期 outcome proxy 复核，使 supported 且 shifted 的候选只有在固定参数预测显示明确改善时才执行。

**Architecture:** 新增纯函数动作决策模块，输入 evidence 状态、shift 状态和父/候选 outcome 结果，输出审计完整的 decision 与 deployment action。新增开发期 proxy outcome 构造和 replay 脚本，复用现有 fit、预测、sandbox 和冻结 proposal，不修改模型调用协议。

**Tech Stack:** Python 3、pytest、现有 symbolic sandbox、JSON 审计记录、OpenHands SDK 仅用于读取已经冻结的真实 proposal。

**Spec:** `docs/experiments/2026-10-26-shift-aware-outcome-gate-v03-design.md`

## Global Constraints

- 只读取 `fit_dev_v2`、`check_dev_v2`、`outcome_dev_v2` 和 synthetic shift fixture；官方 test/test_ood 永远不可读。
- 父结构和候选参数在 `fit_dev_v2` 上拟合后固定；阈值固定为 `1e-5`，不根据 holdout 调参。
- v03 proxy 记录必须包含目标来源、源行索引哈希、fixture 规则和 `not_benchmark=true`。
- 不新增真实模型调用、权重更新、持久策略更新或封存访问。

---

### Task 1: Add the decision contract test

**Files:**
- Create: `tests/test_shift_outcome_gate.py`
- Create later: `analysis/replacement_evidence/shift_outcome_gate.py`

**Interfaces:**
- Planned function: `decide_shift_outcome(*, evidence_status, shift_status, parent_nmse=None, candidate_nmse=None, n_rows=0, min_improvement=1e-5) -> dict`
- The result must contain `decision`, `final_action`, `validation_status`, `delta_nmse`, and `reason`.

- [ ] **Step 1: Write failing tests** for supported/covered, supported/shifted improvement, supported/shifted harm, contradicted, unknown, missing score, and nonfinite score.
- [ ] **Step 2: Run `python -m pytest -q tests/test_shift_outcome_gate.py`** and confirm failure because the module does not exist.
- [ ] **Step 3: Implement the smallest pure decision function** with no file access and no sandbox calls.
- [ ] **Step 4: Re-run the focused test and then the existing shift tests.**
- [ ] **Step 5: Commit the decision contract and tests.**

### Task 2: Build labeled development proxy fixtures

**Files:**
- Modify: `scripts/build_shift_aware_dev_v02.py`
- Create: `scripts/build_shift_aware_outcome_proxy_v03.py`
- Create: `tests/test_shift_outcome_proxy.py`

**Interfaces:**
- `build_shift_outcome_proxy(repo_root, shift_report) -> dict` returns one fixture per task with `X`, `y`, source indices, rule, hashes, and `not_benchmark=true`.

- [ ] **Step 1: Write failing fixture tests** for deterministic source indices, target alignment, and explicit not-benchmark metadata.
- [ ] **Step 2: Run the focused fixture tests and confirm failure.**
- [ ] **Step 3: Implement proxy construction from `outcome_dev_v2` rows using the frozen v02 input transform.**
- [ ] **Step 4: Reject official-test paths and missing target sources.**
- [ ] **Step 5: Run fixture tests and commit.**

### Task 3: Integrate fixed-parameter replay

**Files:**
- Create: `scripts/run_shift_aware_v03_replay.py`
- Create: `docs/environment/2026-10-26-shift-aware-v03-proxy.json`
- Create: `tests/test_shift_outcome_replay.py`

**Interfaces:**
- Replay loads the frozen v02 real round summary, fits parent/candidate on `fit_dev_v2`, predicts on the v03 proxy fixture, calls the decision function, and writes row-level and aggregate actions.

- [ ] **Step 1: Write failing replay tests** for the bactgrow harmful case and stressstrain improvement case.
- [ ] **Step 2: Run focused replay tests and confirm failure.**
- [ ] **Step 3: Implement zero-model-call replay with candidate execution through the existing sandbox.**
- [ ] **Step 4: Add old/v02/v03 action comparison and leakage flags.**
- [ ] **Step 5: Run the replay locally and commit its machine record and report.**

### Task 4: Full verification and synchronization

**Files:**
- Modify: `STATUS.md`
- Create: `docs/analysis/2026-10-26-shift-aware-v03-results.md`

- [ ] **Step 1: Run the full relevant local test suite, Python compilation, JSON cross-checks, and `git diff --check`.**
- [ ] **Step 2: Run the replay on the server without API calls and compare hashes.**
- [ ] **Step 3: Record the exact opportunity-cost counts and all conclusion boundaries.**
- [ ] **Step 4: Commit, push GitHub, fast-forward the server by bundle, and verify both HEADs.**
