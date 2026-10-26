# natural-domain outcome v04 真实提案回放结果

日期：2026-10-26  
状态：已完成 train-only replay；没有新的模型调用，没有读取官方 `test_id` 或 `test_ood`。

## 这一步做了什么

本轮把同一批已经由 MiniMax-M3 真实生成并接受的 8 个 v03 proposal，再通过 v04 双重结果门控回放一次。回放读取的 proposal、父结构、候选结构和 evidence 状态都来自已冻结的真实轮；参数仍只在 `fit_dev_v2` 上拟合。之后分别在两类训练集内数据上计算固定参数 NMSE：

1. `ordinary outcome`：`outcome_dev_v2` 的全部 1,500/2,000 行；
2. `natural domain blocks`：对 `outcome_dev_v2` 按每个输入特征分组，低基数特征按精确 level，连续特征按 fit 分位点分成 5 个 bin。

低基数的 `stressstrain.temp` 形成 5 个真实温度层；连续特征形成固定分位数区域。四个任务共得到 20、10、10、15 个有效块，每个块至少 32 行且目标方差为正。域块来自同一训练 outcome 行、按特征分别建立，因此不同特征的块之间可能重叠；它们是覆盖性审查区域，不是独立重复实验。

对于 `supported + shifted` proposal，v04 只有在普通 outcome 和每一个有效自然域块都满足候选 NMSE 比父结构低至少 `1e-5` 时才允许执行。`contradicted` 始终保留父结构，`unknown` 延迟并保留父结构，`covered` 沿用原替换证据门。任何块不可用都会返回 `defer`。

## 执行和数据完整性

- 真实提案：8 个，swap 7 个，keep 1 个；
- sandbox：145 次；模型请求：0；
- 官方 `test_id`：未读取；官方 `test_ood`：未读取；
- 自然域报告：`docs/environment/2026-10-26-natural-domain-v04.json`；
- 回放记录：`docs/environment/2026-10-26-natural-domain-v04-real-replay.json`；
- 回放记录哈希：`45824bca44bc4de8057b29e1ae022ae438ffd9882e714a569c85fea0ff2a29d7`。

回放过程中没有生成新的 proposal，也没有修改旧 round summary、策略 S、模型权重或封存状态。所有父/候选程序都先在固定 `fit_dev_v2` 拟合，再在同一自然域数据上预测；相同源码和相同块的分数通过缓存复用，但不改变数值结果。

## 结果

8 个 proposal 的 v04 决策为：2 个 `allow_after_dual_validation`，6 个 `retain`，没有 `defer`。其中：

| proposal | evidence | 普通 outcome ΔNMSE | 自然域结果 | v03 → v04 |
|---|---|---:|---|---|
| `oscillator2-p01-r1` | supported | -0.001826 | 10/15 块改善；`x::bin:1` 退化 +0.204479 | execute → retain |
| `oscillator2-p01-r2` | supported | -0.004733 | 10/15 块改善；最大退化 +0.051187 | retain → retain |
| `stressstrain-p01-r1` | supported | -1.680049 | 10/10 块改善 | execute → execute |
| `stressstrain-p01-r2` | supported | -1.680049 | 10/10 块改善 | execute → execute |
| `bactgrow-p01-r2` | contradicted | +0.004626 | 不进入数值放行 | retain → retain |
| `oscillator1-p01-r1` | contradicted | +0.090539 | 不进入数值放行 | retain → retain |
| `oscillator1-p01-r2` | contradicted | +0.082692 | 不进入数值放行 | retain → retain |

唯一改变的是 `oscillator2-p01-r1`：普通 outcome 看起来改善，但时间、状态和输入幅度的自然区域并不一致，尤其 `x::bin:1` 的 NMSE 增加约 0.2045，说明整体平均改善不能代表所有输入区域都安全。v04 因此把它从 v03 的执行改为保留父结构。

两个 stressstrain 候选在 5 个 strain 区域和 5 个真实 temperature level 上都改善，因此通过了双重门控。这个结果只说明它们在当前 `outcome_dev_v2` 的自然区域上具有一致的训练内表现；它没有证明 stressstrain 官方 OOD 上一定改善。

本轮自然普通 outcome 上有 3 个退化 swap，但这 3 个分别是 `bactgrow-p01-r2` 和两个 `oscillator1` proposal，它们的 evidence 已经是 `contradicted`，旧 replacement、v02、v03 和 v04 都没有部署。因此本轮 v04 没有新增“相对旧策略阻止有害部署”的数量；它新增的是对一个原本会被 v03 放行的 supported proposal 的区域一致性阻断。

## 应如何解释

这轮验证了一个更窄但更可靠的机制性质：当整体 outcome 改善与局部自然域证据不一致时，固定权重的 host-side gate 可以阻止候选执行。它没有验证模型能力提升，也没有验证 agent 能在新 OOD 上泛化；所有数值都来自既有训练文件的 `outcome_dev_v2`，而且 proposal 集是 v03 真实轮的同一批 proposal，不是新的独立抽样。

v04 相比 v03 的动作变化只有 1/8，说明自然域一致性门较严格；这既可能减少有害修订，也可能拒绝一部分只在局部区域改善的候选。当前结果没有足够的独立任务或独立 proposal 数量估计这种机会成本，不能写成稳定优势、统计显著或普适泛化。

## 下一步

下一步应先冻结 v04 的规则、分箱边界、阈值和哈希，再做一批新的开发 proposal，比较 `replacement`、`shift-aware`、`dual natural-domain` 三个动作条件；只有在新开发批次上完成审计后，才能预注册新的盲测。现有 holdout 结果只能用于事后失败审查，不能回填 v04 阈值或重新选择自然域规则。
