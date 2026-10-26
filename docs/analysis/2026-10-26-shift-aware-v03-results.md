# Shift-aware outcome gate v03 replay 结果

日期：2026-10-26  
真实 proposal 来源：`2026-10-26-v02-real-v01`  
机器记录：[2026-10-26-shift-aware-v03-proxy.json](../environment/2026-10-26-shift-aware-v03-proxy.json)

本轮把上一轮真实 MiniMax-M3 生成的 8 个 proposal 重新放入同一组 `synthetic_shift_dev` 输入变换，但把 proxy 目标切换为每个任务冻结的 `outcome_dev_v2` 目标行。父结构和候选结构仍然只在 `fit_dev_v2` 拟合，参数随后固定。这样可以在同一 proxy 上公平比较旧 replacement action、v02 hard shift action 和 v03 outcome action。

## 运行完整性

- 8 个冻结 proposal 全部完成；
- 0 次模型请求，26 次 sandbox fit/predict；
- `official_test_read=false`、`official_test_ood_read=false`；
- proxy 目标来源为 `outcome_dev_v2 target rows`，记录 `not_benchmark=true`；
- proxy report hash：`ae21c578ce67382e46f7b1bad4276122e5b9fdc01e01e5ad0d068cd23d3e855c`。

## 同一 proxy 上的三种动作

| 指标 | 结果 |
|---|---:|
| proposal | 8 |
| proxy harmful | 1 |
| old replacement 部署 harmful | 1 |
| v02 hard shift 部署 harmful | 0 |
| v03 outcome gate 部署 harmful | 0 |
| v02 相对 old 新增阻断 | 1 |
| v03 相对 old 新增阻断 | 1 |
| v03 相对 v02 新增阻断 | 0 |
| v03 相对 v02 动作变化 | 2 |
| v03 allow_after_validation | 2 |
| v03 retain | 3 |
| v03 defer | 3 |

## 逐任务解释

- **bactgrow**：supported proposal 的父结构 NMSE 为 0.990674，候选为 1.596515，差值为 +0.605841。old replacement 会执行，v02 和 v03 都保留父结构。v03 没有重复声称获得新的安全收益。
- **stressstrain**：两个 supported proposal 的父结构 NMSE 为 1.053094，候选为 0.918775，差值为 -0.134319。old replacement 会执行，v02 hard shift 会保留，v03 通过 outcome 复核后执行。两个动作变化都属于从保守保留恢复到有开发期证据支持的执行。
- **oscillator1**：两个 proposal 的 evidence 为 contradicted，候选在该 proxy 上改善，但三种机制都保留父结构；v03 不允许 outcome 分数越过 contradicted evidence。
- **oscillator2**：两个 proposal 为 unknown keep，v03 均延期并保留父结构。

## 结论边界

在这一组新的 train-only outcome proxy 上，v03 没有超过 v02 的有害部署拦截数量，v02 已经把唯一的 proxy harmful proposal 拦截掉；v03 的新增作用是恢复两个 stressstrain 候选，降低 shift gate 的保守机会成本。这个结果支持“shift 状态下加入 outcome 复核可以区分安全保留和可能有效的候选”的开发期机制信号，但不支持真实 OOD 性能、统计显著性或普适泛化结论。由于本轮 proxy 使用 `outcome_dev_v2`，不能把它与上一份使用 `fit_dev` 目标的 v02 proxy harmful 数字直接相减。

下一步是把同一决策函数接入 fake runner 的完整动作链，验证每一条 proposal 都同时保留 old/v02/v03 三种动作记录；完成 fake 契约后，再决定是否需要新的真实模型开发轮。
