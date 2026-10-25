# 跨任务替换充分性开发重复协议

状态：配置已实现，等待服务器生成 train-only split manifest 和 FakeProvider 预演；尚未发送新的真实模型请求。

## 目的与证据分级

本轮用于检查上一轮替换充分性机制能否从 `bactgrow/stressstrain` 迁移到另一组符号方程。任务为公开 LLM-SR 数据中的 `oscillator1` 和 `oscillator2` train；项目早期已经使用过这两个任务，因此本轮只能称为“跨任务开发重复”，不能称为未见分布或最终泛化测试。

最终 holdout 仍是独立阶段：本轮不读取 `test_id`、`test_ood` 或其他封存文件，不根据本轮结果调阈值，也不更新模型权重、长期策略或持久记忆。

## 固定任务与父结构

每个任务固定 3 个父结构，每个父结构发送 2 个一次性 actor 请求，共 12 个槽位。父结构在第一条请求前冻结；常数项必须保留。候选只允许 `keep` 或恰好一次 `swap_one`，其他结构立即停止整轮，不补抽、不重试。

- `oscillator1(x,v→a)`：
  - `oscillator1-p01`: `1, x, v, x·v`
  - `oscillator1-p02`: `1, x, v, x²`
  - `oscillator1-p03`: `1, x, v, v²`
- `oscillator2(t,x,v→a)`：
  - `oscillator2-p01`: `1, t, x, v`
  - `oscillator2-p02`: `1, t, x, v, t·x`
  - `oscillator2-p03`: `1, t, x, v, x·v`

特征 ID、任务输入顺序、CSV 源文件哈希和行索引均记录在配置与 split manifest 中；模型只能提交 `feature_ids`。

## 证据门与对照

沿用已冻结的门控规则，不根据上一轮 5 次拦截结果调整：

\[
I^- = NMSE(common)-NMSE(parent),\quad
I^+ = NMSE(common)-NMSE(added),\quad R=I^+/I^-.
\]

`I^- > 1e-8`、`I^+ > 1e-5` 且 `R ≥ 1` 才标记 `supported`；不满足、拟合/预测失败或方差不可用均保留父结构。每个 proposal 复制到 `no_check`、`sham_check` 和 `replacement_check` 三臂。所有 gate 冻结并哈希后才读取 `outcome_dev` 做 shadow outcome。

## 数据与运行约束

- 每个 train.csv 重新生成确定性的 `fit_dev/check_dev/outcome_dev`，split 版本为 `replacement-cross-task-v0.1`；只保存行索引和哈希，不复制原始样本到报告。
- 最多 12 个真实模型请求，每个 SDK session 一次请求，禁止重试；usage unknown、网络失败、协议字段错误、结构非法或 runtime integrity failure 立即停止。
- 固定 MiniMax-M3、OpenHands SDK 1.55.1、锁定 symbolic sandbox；预算账本上限 4 元，远低于用户授权上限。

## 预先登记的报告指标

记录 12 槽接受率、结构无效率、`keep/swap_one` 数、`supported/contradicted/unknown` 数、三臂候选执行率、`outcome_dev` 有害率和 `prevented_harm`。本轮的主要比较仍是同一 proposal 的三条件配对，不把 12 槽当作独立任务样本。

只有跨任务重复在方向上与上一轮一致，且完整性条件满足，才设计下一阶段的 holdout 解封；holdout 只能用于最终报告，不能用于选择父结构、阈值或提示词。
