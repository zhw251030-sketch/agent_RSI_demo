# Shift-aware v02 四任务 fake round 结果

日期：2026-10-26  
运行：`2026-10-26-v02-fake-v06`  
机器核验：`docs/environment/2026-10-26-shift-aware-v02-fake-verification.json`

## 轮次定位

本轮把新的 train-only v02 manifest 接入现有 OpenHands SDK、Linux sandbox、符号拟合器和 replacement evidence runner。模型端使用 FakeProvider，未调用 MiniMax；四个任务各选择一个预先固定父结构、每个父结构重复两次，共 8 个 bounded session。这是接线预演，不能视为真实 Agent 机制效果。

## 完整性

- 4 个任务、8/8 proposal 接受、24/24 gate rows、outcome_dev 读取完成；
- FakeProvider 8/8 调用，usage unknown=0，真实模型调用 0；
- `official_test_read=false`、`official_test_ood_read=false`；
- 实际账本 960 tokens，估算 0.003024 元，保守预留 0.7294434 元；
- v02 split report SHA-256：`eaf1150dff785fc7ac87f18ce00868b6941f1291ce673777b6a74818b39713af`；
- round summary SHA-256：`2766e8ef038e410f73330b97e1aaaff5da1934d79fb82195f2a875467f4352a0`。

## 任务级记录

每个任务 2 个 proposal：1 个 keep 和 1 个 swap_one。`bactgrow`、`stressstrain`、`oscillator1` 的 swap evidence 为 `contradicted`；`oscillator2` 的两个记录均为 `unknown`。这些状态由 FakeProvider 产生的固定候选和真实 sandbox 诊断得到，只能说明 SDK/计算链路工作。

## 基线 shadow 结果

本轮的 shadow 使用的是现有 `no_check`、`sham_check`、`replacement_check`，不是新的 shift-aware gate：

| 条件 | 候选执行 | 保留父结构 | 有害影子结果 | 部署有害 | 拦截有害 |
|---|---:|---:|---:|---:|---:|
| `no_check` | 4 | 4 | 3 | 3 | 0 |
| `sham_check` | 4 | 4 | 3 | 3 | 0 |
| `replacement_check` | 0 | 8 | 3 | 0 | 3 |

这组数字是 v02 runner 的基线接线结果，不能称为 shift gate 的新效果。shift-aware 逻辑目前只在独立 synthetic action/outcome preflight 中通过，下一步需要将输入覆盖状态绑定到同一 runner 的冻结 gate 和 outcome replay。

## 下一步

1. 在不改变模型候选生成的前提下，新增 v02 host-side gate replay：分别重放 `check_dev_v2` 的 covered 状态和 `synthetic_shift_dev` 的 shifted 状态；
2. 对同一批 8 个 proposal 比较旧 replacement action 与新 `replacement+shift` action；
3. 只有 replay 和审计通过后，才考虑真实 MiniMax v02 round；真实结果仍需使用新的开发分母，不能与旧 holdout 混合。

