# Shift-aware outcome gate v03 真实开发轮结果

日期：2026-10-26  
运行：`2026-10-26-v03-real-v01`  
机器核验：[2026-10-26-shift-aware-v03-real-verification.json](../environment/2026-10-26-shift-aware-v03-real-verification.json)  
动作记录：[2026-10-26-shift-aware-v03-real-proxy.json](../environment/2026-10-26-shift-aware-v03-real-proxy.json)

## 真实 proposal 阶段

在固定 MiniMax-M3、OpenHands SDK 1.55.1、8 槽位预算和 train-only v02 切分上，8/8 请求接受，8 个 proposal 和 24 条 gate 记录全部生成；真实模型用量 9,296 tokens，按账本估算 0.0236544 元，usage unknown=0。官方 `test_id/test_ood` 没有读取，模型权重、持久策略和封存成绩没有更新。

## v03 outcome replay

读取这 8 个真实 proposal 后，父结构和候选结构在 `fit_dev_v2` 拟合参数并固定，在 `outcome_dev_v2` 派生的 synthetic shift proxy 上进行 30 次 sandbox fit/predict。v03 replay 没有新的模型请求。三种动作在同一 proxy 上的结果为：

| 指标 | 结果 |
|---|---:|
| proposal | 8 |
| proxy harmful | 1 |
| old replacement 部署 harmful | 1 |
| v02 hard shift 部署 harmful | 0 |
| v03 outcome gate 部署 harmful | 0 |
| v02 相对 old 阻断 | 1 |
| v03 相对 old 阻断 | 1 |
| v03 相对 v02 新增阻断 | 0 |
| v03 相对 v02 动作变化 | 3 |
| `allow_after_validation` | 3 |
| `retain` | 4 |
| `defer` | 1 |

## 逐项解释

- `bactgrow-p01-r2`：evidence 为 contradicted，候选 proxy 差值为 -0.013329；evidence precedence 使三种动作都保留父结构。
- `stressstrain-p01-r1/r2`：evidence 为 supported，候选差值均为 -0.134319；v02 hard shift 保留，v03 outcome 复核通过后执行，形成两个从 retain 到 execute 的动作变化。
- `oscillator2-p01-r1`：evidence 为 supported，候选差值为 -0.017704；v03 复核通过并恢复执行。
- `oscillator2-p01-r2`：evidence 为 supported，但候选差值为 +0.116023；v02 和 v03 都保留父结构，避免旧 action 的有害部署。
- `bactgrow-p01-r1`：evidence 为 unknown，进入 defer；不使用 outcome 分数越过 unknown 状态。
- 两个 `oscillator1` proposal：evidence 为 contradicted，均保留父结构。

## 结论边界

这轮真实 Agent proposal 证明 v03 的宿主 replay 能在同一开发 proxy 上同时实现两种行为：保留 oscillator2 的退化候选，并恢复 stressstrain 与 oscillator2 的部分 supported 改善候选。相对于 v02，当前样本没有新增安全拦截，主要收益是降低 shift gate 的保守机会成本。proxy 标签来自 `outcome_dev_v2` 的训练行，记录明确标记 `not_benchmark=true`；因此本轮不支持真实 OOD 性能、统计显著性或独立泛化结论。

下一步应把本轮真实 proposal 的行级结果与 v02 失败审查合并，检查 outcome 复核是否依赖任务特定的 synthetic 变换；在此基础上再决定是否预注册新的开发切分和独立 holdout。
