# Domain-blocked outcome v04 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从训练数据自然行构造 feature-wise domain blocks，替代 synthetic 输入变换后复用目标的 proxy，并为下一版双重 outcome gate 提供无泄漏开发数据。

**Architecture:** 以 `fit_dev_v2` 计算每个输入特征的固定 level/五分位分箱规则，在 `outcome_dev_v2` 上按每个 feature 的 region 生成可审计 block。每个 block 保留真实训练目标、原始行索引和哈希；当前阶段只生成 coverage 报告，不改变 v03 动作。

**Tech Stack:** Python 3、pytest、现有 `dev_splits`、JSON 哈希审计、symbolic sandbox 后续接入。

**Spec:** `docs/experiments/2026-10-26-domain-blocked-outcome-v04-design.md`

## Global Constraints

- 只读取 train.csv 的 `fit_dev_v2` 和 `outcome_dev_v2`；官方 test/test_ood 不可读。
- 分箱和 block 规则只使用输入列；目标值只作为 block 中的真实 score 标签。
- 每个有效 block 至少 32 行；稀疏 block 必须标记并不得进入 allow。
- 所有行索引、分箱边界、源文件哈希和 block 哈希必须写入报告。

---

### Task 1: Feature grouping contract

**Files:**
- Create: `tests/test_natural_domain_blocks.py`
- Create: `scripts/build_natural_domain_v04.py`

- [ ] 写分箱、精确 level、未见 level、block 最小样本和确定性哈希的失败测试。
- [ ] 运行 focused tests，确认模块尚不存在或行为不完整。
- [ ] 实现纯函数分组器，不读取文件、不调用模型。
- [ ] 运行 focused tests 和现有 shift/evidence tests。

### Task 2: Train-only coverage report

**Files:**
- Create: `docs/environment/2026-10-26-natural-domain-v04.json`
- Create: `docs/analysis/2026-10-26-natural-domain-v04-results.md`

- [ ] 从四个 train.csv 生成 manifest-bound 的 ordinary outcome 和 feature-wise blocks。
- [ ] 检查每个任务的 block 数、样本数、目标方差和输入覆盖。
- [ ] 输出 `official_test_read=false`、`official_test_ood_read=false` 和 `not_benchmark=true`。
- [ ] 交叉核对源文件及报告哈希，提交机器报告。

### Task 3: Natural-domain dual outcome gate

**Files:**
- Modify: `analysis/replacement_evidence/shift_outcome_gate.py`
- Create: `tests/test_natural_domain_gate.py`
- Create: `scripts/run_natural_domain_v04_replay.py`

- [ ] 先写 ordinary + block 双通过、单 block 失败、稀疏 block defer 的失败测试。
- [ ] 实现 `allow_after_dual_validation`，要求 ordinary outcome 改善且至少 80% 有效 blocks 改善，同时没有 block 超过预注册 harm 阈值。
- [ ] 对现有 v03 真实 proposal 做无模型 replay，比较 v02/v03/v04 动作。

### Task 4: Verification and decision

- [ ] 运行全套本地测试和服务器编译。
- [ ] 只在 v04 coverage 和 replay 结果清楚后，决定是否启动下一轮真实模型请求。
- [ ] 新 holdout 必须单独预注册，不能使用当前 holdout 调参。
