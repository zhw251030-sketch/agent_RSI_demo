# Shift-aware v02 synthetic outcome 回放结果

日期：2026-10-26  
运行脚本：`scripts/run_shift_gate_outcome_preflight.py`  
机器记录：`docs/environment/2026-10-26-shift-aware-outcome-preflight.json`

本轮使用预先声明的 synthetic fixture 验证统计绑定，而不是报告任务性能。四个任务各包含四类状态：`supported+covered`、`supported+shifted`、`contradicted+covered`、`unknown+shifted`。其中前者设为有利候选，后三者设为有害候选，父结构 NMSE 固定为 1.0；这些数值只用于检查计数逻辑。

| 指标 | 旧 `replacement_check` | 新 `replacement+shift_gate` |
|---|---:|---:|
| proposal 数 | 16 | 16 |
| 部署有害 | 4 | 0 |
| 拦截有害 | — | 12 |
| 执行有利 | — | 4 |
| 保守拒绝有利 | — | 0 |

结果表明，shift 状态可以在 host 层阻止 `supported+shifted` 的候选，同时允许 `supported+covered` 的候选继续执行。它没有证明 shift detector 的真实预测准确率，也没有使用训练任务的真实候选分数；真实开发轮必须重新计算模型候选、fit 参数和 replacement evidence。

完整性：0 模型请求、0 真实候选执行、未读取 `test_id/test_ood`，synthetic fixture 明确标记为非 benchmark 结果。

