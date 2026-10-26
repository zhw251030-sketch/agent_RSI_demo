# Domain-blocked outcome v04 设计

日期：2026-10-26  
状态：下一轮开发设计，尚未调用模型，尚未读取新的 holdout。

## 动机

v03 的 stressstrain synthetic condition-collapse 使用输入变换后的样本，但复用了原始训练目标。它能检验 host action 是否改变，却不能保证变换后的输入与目标仍构成真实任务关系。v02 holdout 失败表明，真实 OOD 可能同时改变输入覆盖和响应关系。因此下一版使用训练文件中的自然行构造 domain-blocked outcome，避免目标错配。

## 数据构造

1. 只读取四个任务的 train.csv；
2. 以 `fit_dev_v2` 每个输入列的固定四分位点建立 4-bin 分箱；
3. 对 `outcome_dev_v2` 每行生成有序 bin tuple；
4. 计算 `sha256(task_id|bin_tuple|row_index)`，按哈希模 5 固定分为五个 domain blocks；
5. 选择 block 0 作为 `blocked_outcome_v4`，其余行组成 `ordinary_outcome_v4`；
6. 目标值直接来自对应训练行，不做输入变换和目标复用；
7. 记录每行原始索引、block id、分箱边界、源文件哈希和 split 哈希。

该分块规则只使用输入和行索引，不使用目标值。若某任务的 block 0 少于 32 行或目标方差为 0，则该任务的 blocked outcome 标记 unavailable，相关 proposal 只能 defer。

## v04 动作规则

- `supported + covered`：沿用 replacement evidence，执行候选；
- `contradicted`：保留父结构；
- `unknown`：defer；
- `supported + shifted`：父/候选必须在 ordinary outcome 和 blocked outcome 上都满足 `candidate_nmse <= parent_nmse - 1e-5`；
- 任意一个 outcome 不可用、退化或哈希不匹配：retain/defer；
- 只在两种 outcome 都改善时产生 `allow_after_dual_validation`。

## 评价

同一批冻结 proposal 上同时保存 old replacement、v02 hard shift、v03 synthetic outcome 和 v04 dual natural-domain outcome。报告：

- harmful deployment、prevented harm；
- 从 v02 恢复的候选数；
- ordinary/block 双通过、单通过、双失败和不可用数量；
- 每个任务及每个 domain block 的样本数和目标方差；
- 任务级结果，不把重复 proposal 当作独立任务样本。

## 防泄漏与边界

- 官方 test_id/test_ood 永远不可读；
- 分箱边界、哈希规则、阈值和最小行数在真实请求前冻结；
- v04 只使用 train.csv 的自然目标，不声称 OOD benchmark；
- 只有完成新的开发审查后，才可以单独预注册下一批 holdout；现有 holdout 不用于调参。
