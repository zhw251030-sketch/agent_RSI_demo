# 推断证据检查 v0.1 完整原始归档

服务器运行：`runs/inference-policy/20261020-inference-policy-v01`。实跑提交：`568f833eebffb4505e87903029ace9eb5f9e0b78`。14次请求完成，6份策略、8个新候选、44个新的任务执行结果。

230份原文件按原名逐字节复制，没有将candidates.json改名为trajectory.json。`manifest.json`给出原文件hash、完整树hash及来源；本README与manifest是新增说明，不冒充原始运行记录。树SHA256：`199e2b584e2121fd3121f4abaad952295ce6763ca8707c59f24113949172c06d`。

- [summary.json](summary.json)：顺序、每个槽位、候选成绩、预算与运行代码hash。
- [update-bundle.json](update-bundle.json)：两个历史经验的完整差分、诊断及预测。
- [update-phase-freeze.json](update-phase-freeze.json)：六个更新槽的冻结文件清单。
- `p1-proposal/`、`p2-proposal/`：两个新初稿。
- `p1-self/`、`p1-checked/`、`p2-self/`、`p2-checked/`：自行或检查后复查，各一次真实请求。
- `p1-P-A002-*`、`p1-S-poly5-*`、`p2-P-H002-*`、`p2-S-odd4-*`：各一次候选修订，`candidates/`保留父/子源码，`candidates.json`保留实际结果，`diagnostics.json`、`audits.json`保留诊断和声明审计，`requests/`保留完整SDK发送前请求及原响应。
- [budget-ledger.json](budget-ledger.json)：14次已知用量，140226tokens、配置估算0.3802617元、预留1.6864848元。

分析在归档外保存：[操作与结论](../../../../docs/operations/inference-policy.md)、[逐项审计](../../../../docs/analysis/2026-10-20-inference-policy-audit.json)。这些是研究者已见开发任务；没有封存测试、供应商账单核对或开放解释正确性认证。p2两组最终策略相同，不能将下游生成差异归因于检查反馈。
