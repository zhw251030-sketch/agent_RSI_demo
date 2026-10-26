# Shift-aware outcome gate v03 设计

日期：2026-10-26

## 研究问题

v02 的 shift gate 可以在输入偏离开发参考域时阻止 supported proposal，但会把可能在新条件下仍然有效的候选一并保留。stressstrain proxy 中出现了两个这样的案例：候选在 synthetic shift 上改善，但只要状态为 shifted 就被直接拒绝。

v03 研究一个更窄的问题：在输入发生 shift 且 replacement evidence 为 supported 时，能否使用冻结的开发期 outcome proxy 做一次低成本复核，减少有害替换，同时保留一部分真实改善候选的机会。

## 机制

动作由三层决定：

1. 原 replacement evidence gate 判断具体替换是否 supported、contradicted 或 unknown；
2. host-only shift gate 判断输入批次是 covered 还是 shifted；
3. 只有 `supported + shifted` 进入 outcome gate，在 `outcome_dev_v2` 派生的 synthetic proxy 上比较父结构与候选结构的固定参数 NMSE。

规则固定为：

| evidence | shift | outcome proxy | decision | deployment action |
|---|---|---|---|---|
| supported | covered | 不读取 | allow | execute_candidate |
| contradicted | 任意 | 不读取 | retain | retain_parent |
| unknown/keep | 任意 | 不读取 | defer | retain_parent |
| supported | shifted | 候选 NMSE 比父结构低至少 `1e-5`，且复核有效 | allow_after_validation | execute_candidate |
| supported | shifted | 没有有效复核或改善小于 `1e-5` | defer/retain | retain_parent |

`outcome_dev_v2` 的目标值只用于开发期 proxy 诊断；它不代表真实 OOD 标签。复核失败、非有限分数、样本数不足或输入哈希不匹配都必须进入 `defer`，部署动作保持 `retain_parent`。

## 数据与防泄漏

- 父/候选参数在 `fit_dev_v2` 上拟合并冻结；
- outcome proxy 从同一训练文件的 `outcome_dev_v2` 行派生，输入沿用 v02 的输入变换，目标值沿用对应训练行；
- 每个 proxy 记录源 split、源行索引哈希、fixture 规则、目标来源和 `not_benchmark=true`；
- `test_id`、`test_ood` 和任何官方封存文件不进入 v03 接口；
- 阈值 `1e-5` 固定，不根据最终 holdout 或本轮代理结果调节。

## 审计输出

每个 proposal 保存：`evidence_status`、`shift_status`、`validation_status`、`parent_nmse`、`candidate_nmse`、`delta_nmse`、`threshold`、`decision`、`final_action`、`target_source` 和 `not_benchmark`。汇总同时报告旧 replacement action、v02 hard shift action、v03 outcome action，避免把旧 gate 已经拦截的候选重复记为新机制收益。

## 验收标准

- 动作矩阵对 covered、shifted、supported、contradicted、unknown 的组合确定性一致；
- bactgrow proxy 的有害候选不能通过 v03；
- stressstrain proxy 的改善候选可以通过 v03，且报告标记为 development proxy；
- 缺失分数、非有限分数、目标来源错误和官方测试访问均被拒绝；
- fake replay、真实 proposal 读取、预测和汇总均不产生模型请求；
- 本地相关测试全部通过，服务器脚本可编译并与本地提交同步。

## 范围边界

v03 是开发期机制验证。它不提供真实 OOD 性能、不证明统计显著性、不更新模型权重、不更新持久策略，也不重新使用已经完成的最终 holdout。
