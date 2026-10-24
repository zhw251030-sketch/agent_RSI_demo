# 编辑级 targeted check 校准

日期：2026-10-24。范围：无模型调用、无候选执行、无旧归档写入。

## 校准目的

验证一个有界的 typed claim 是否能稳定传递为编辑级的三态决策：
`supported → allow_candidate`、`contradicted → retain_parent`、
`unavailable/schema_invalid → unknown → defer`。

## 结果

| 情形 | 原始检查 | 编辑级状态 | 临时决策 |
|---|---|---|---|
| small_coefficient | supported (comparison_supported) | supported | allow_candidate |
| large_coefficient | contradicted (comparison_contradicted) | contradicted | retain_parent |
| missing_coefficient | unavailable (reference_not_found) | unknown | defer |

校准通过：`True`。

## 边界

这里验证的是记录和决策映射，不是机制效果。特别是“系数较小”之类的 claim 只有在宿主预先定义其含义时才可作为检查；它不能单独证明删除某项的因果必要性。
下一步仍需在相同部署门下比较无检查、sham 检查和真实编辑检查。
