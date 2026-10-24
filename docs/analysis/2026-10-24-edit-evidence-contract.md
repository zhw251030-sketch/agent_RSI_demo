# 编辑级证据契约：从 A 起点诊断到下一轮机制实验

日期：2026-10-24。状态：契约实现完成，尚未接入真实 Agent 轮。

## 为什么需要适配层

`evidence_checks.py` 和 `evidence_ids.py` 已提供任务无关的数值/事实证据检查，
并通过 56 项相关测试。基函数 v02 的离线诊断进一步表明，当前缺少的是把一次
具体结构编辑作为分析单位。新增 `rsi_eval/edit_evidence.py` 将以下对象绑定在一起：

```text
父结构和源码
    + 拟议子结构和源码
    + removed / added feature IDs
    + 编辑前检查结果
    + 编辑后的任务结果
```

## 当前契约

- `build_edit()` 只接受保持原结构或一次 feature swap，拒绝多项同时替换；
- 父/子源码 SHA、任务 ID、父/子 feature IDs 和编辑差异生成唯一 `edit_id`；
- `attach_check()` 将 `supported`、`contradicted` 或 `unknown` 的检查绑定到该编辑；
- `decide_from_check()` 只产生临时的 `allow_candidate`、`retain_parent` 或 `defer` 建议；
- `classify_observed_outcome()` 在候选执行后单独记录改善、退化或容差内未知；
- 封存范围不能进入编辑前检查，避免测试集信息泄漏；
- 后验分数不会修改编辑前决策或伪造模型理由。

这不是策略晋升器，也不是候选执行器。最终是否部署仍需由两策略臂共用的宿主接受规则
决定；本适配层只保证“编辑—证据—结果”的记录不会混在一起。

## 与 A 起点结果的对应

对 `A={1,v,x,xv}` 的 `xv→x²` 或 `xv→v²`，下一轮可以先记录一个
`swap_one` 编辑，再绑定一个开发范围的 targeted check。若检查无法判断替换收益，
状态为 `unknown`，模型可以选择延期或保持；若候选仍被执行，实际 NMSE 退化应记录为
`posthoc_status=contradicted`。这两个字段分别回答“提交前有什么依据”和“执行后发生了
什么”，不允许互相替代。

## 下一轮接线要求

1. 在 basis actor 的提交工具中生成 `EditEvidence`，不再只提交 `feature_ids`；
2. 由宿主从父反馈生成可见的候选级证据 ID，模型只能复制 ID，不能自造哈希或范围；
3. 先实现一个人工校准的 targeted check，确认它能识别 `xv` 删除及替换收益未知；
4. 对无检查、等预算 sham 检查和真实检查使用相同部署门；
5. 通过 SDK 假 provider 预演和篡改审计后，才冻结小规模真实轮。

## 已完成的接线校准

`rsi_eval/basis_actor_evidence.py` 已将实际 basis actor 的 accepted business
payload（只含 `feature_ids`）转换为上述编辑记录，并核对可选的宿主执行 payload
没有改变 ID。`rsi_eval/targeted_edit_check.py` 已复用 `EvidenceRegistry`，把 typed
claim 的 `supported`、`contradicted`、`unavailable/schema_invalid` 映射为
`allow_candidate`、`retain_parent`、`defer`。三种固定情形的校准报告位于
`docs/analysis/2026-10-24-targeted-check-calibration/`。

这次校准只验证数据绑定和三态传播。示例中的系数阈值是研究者预先写入 claim 的
启发式条件，不能被解释为因果必要性，也没有替代真实的无检查/sham/真实检查对照。

本契约本身不构成机制效果证据；当前尚未执行新的模型请求、候选拟合或封存评价。
