# Shift-aware v02 真实开发轮与动作 replay 结果

日期：2026-10-26  
运行：`2026-10-26-v02-real-v01`  
模型：MiniMax-M3，OpenHands SDK 1.55.1，基础模型权重固定。

## 轮次目的

本轮首次让真实 MiniMax-M3 在四个 train-only v02 任务上提交 proposal，然后在不读取官方 holdout 的前提下重放 covered/shifted 两种输入状态。模型只提交 `feature_ids`；父结构、sandbox、拟合和 evidence 计算由宿主完成。

## 完整性与用量

- 8/8 模型请求接受，8/8 proposal，24/24 gate rows，outcome_dev 完成；
- 真实模型调用 8 次，usage unknown=0，无失败、无重试；
- 真实用量 9,300 tokens（prompt 8,645，completion 655），按账本估算 0.0236565 元，保守预留 0.7294434 元；
- `official_test_read=false`、`official_test_ood_read=false`；
- 机器核验见 `docs/environment/2026-10-26-shift-aware-v02-real-verification.json`。

## Agent proposal 与旧 evidence gate

每个任务使用一个预先登记父结构、两次重复：

| 任务 | proposal | keep | swap_one | supported | contradicted | unknown |
|---|---:|---:|---:|---:|---:|---:|
| `bactgrow` | 2 | 1 | 1 | 1 | 0 | 1 |
| `stressstrain` | 2 | 0 | 2 | 2 | 0 | 0 |
| `oscillator1` | 2 | 0 | 2 | 0 | 2 | 0 |
| `oscillator2` | 2 | 2 | 0 | 0 | 0 | 2 |

旧 `replacement_check` 在 outcome_dev 的 shadow 中执行 3 个候选，拦截 2 个有害候选，部署有害为 0。这只是 v02 开发基线，不是 shift-aware 的独立效果。

## covered/shifted action replay

对同一 8 个 proposal，`check_dev_v2` 的 profile 状态为 `covered`，synthetic fixture 状态为 `shifted`。真实 evidence 状态与输入状态组合后的动作如下：

- covered：3 个 supported proposal 执行候选，5 个 proposal 保留父结构；
- shifted：全部 8 个 proposal 保留父结构；
- 3 个真实 supported proposal 均发生 `execute_candidate → retain_parent` 的动作变化；
- replay 没有重新调用模型或执行候选程序。

这证明 shift gate 已经能在真实 Agent proposal 上改变宿主动作，而且变化只发生在“evidence supported 且输入发生 shift”的组合。它仍然没有证明 synthetic shift 上候选一定退化，因为本 replay 尚未对 synthetic 输入重新计算 candidate/parent NMSE。

## 结论边界与下一步

本轮支持一个工程级机制结论：shift-aware gate 已接入真实 proposal 的 host-side action replay，能够把 supported proposal 在 shifted 输入状态下转为保守保留。它不支持任务性能改善、OOD 风险下降或普适泛化结论。

下一步是在不读取官方测试的前提下，对 synthetic_shift_dev 的输入批次执行固定参数预测，计算 parent/candidate 的 shift outcome，并比较旧 replacement action 与新 shift-aware action 的潜在有害部署和保守代价。该分析仍属于 v02 开发证据；只有完成新的开发审查后，才能设计下一次独立 holdout。

