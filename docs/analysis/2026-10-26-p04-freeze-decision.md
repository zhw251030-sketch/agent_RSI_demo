# p04 开发阶段冻结决策

## 审计状态

p04 真实 round、v03 synthetic replay 和 v04 natural-domain replay 的三层账本已经通过 5/5 机器检查：8 个 proposal ID 唯一且完全对应，evidence 状态逐条绑定，v04 `decision.final_action` 与 `v04_action` 一致，官方 `test_id/test_ood` 读取标志均为 false。机器记录见 `docs/environment/2026-10-26-natural-domain-v04-p04-audit.json`。

## 槽位级状态

| task × parent × repeat | edit/evidence | ordinary ΔNMSE | v04 结果 | 解释 |
|---|---|---:|---|---|
| bactgrow-p04-r1 | swap / unknown | -0.002126 | defer | 证据未知，未进入数值放行 |
| bactgrow-p04-r2 | swap / unknown | -0.011804 | defer | 证据未知，未进入数值放行 |
| stressstrain-p04-r1 | keep / unknown | 0 | retain | 无候选编辑 |
| stressstrain-p04-r2 | swap / contradicted | -0.158909 | retain | replacement evidence 已矛盾 |
| oscillator1-p04-r1 | keep / unknown | 0 | retain | 无候选编辑 |
| oscillator1-p04-r2 | swap / supported | -0.000310 | retain | 7/10 自然块改善，存在局部退化 |
| oscillator2-p04-r1 | swap / supported | -0.004905 | retain | 10/15 自然块改善，存在局部退化 |
| oscillator2-p04-r2 | keep / unknown | 0 | retain | 无候选编辑 |

因此 p04 的两个 supported swap 都没有通过 v04 双重结果门；这不是拟合失败或样本不足，而是局部自然域一致性不足。p04 为当前机制提供了一个完整的开发重复，但不能把 8 个槽位当作 8 个独立任务样本。

## 继续推进的决策

1. 冻结 p04 的父结构、proposal、阈值、自然域规则和所有回放结果，不根据本批结果放宽 `required_fraction=1`、`min_rows=32` 或 `max_domain_harm=0`。
2. 不再次读取已经解封的官方 `test_id/test_ood`。对同一 holdout 重新评价 v04 会把 holdout 失败模式用于新机制的后验选择，不能升级为独立证据。
3. 下一阶段必须二选一：引入新的公开符号任务/数据，或在现有 train 数据上预先冻结一个新的嵌套开发盲区。后者只能作为内部开发证据，不能替代官方 benchmark。
4. 新阶段仍固定模型权重，比较原 replacement evidence、shift-aware gate 和 natural-domain dual gate；分析单位保持 task×parent×repeat，先完成 fake/contract 审计，再发送真实请求。

在新的数据或预注册盲区到位前，项目的可辩护结论停留在“固定权重下的 host-side 证据门可以阻止整体改善但局部退化的修订”，不延伸为 OOD 泛化或稳定性能提升。
