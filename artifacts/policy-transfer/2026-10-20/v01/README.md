# 一次外部策略更新与三条件开发验证：完整证据

运行ID：`20261020-policy-transfer-v01`；运行提交：`154bc39aa64d680ade8b3ddfedbecd296f0b4e81`。本目录保留全部231份已保存运行文件的逐字节副本，包括失败响应；仅各会话的`candidates.json`改名为`trajectory.json`。映射、大小与SHA见[manifest](manifest.json)。服务器原件和本机原件均保留，不用归档副本恢复已完成的轮次。

先读[本轮详细说明](../../../../docs/operations/policy-transfer.md)和[逐条结果与理由核查](../../../../docs/analysis/2026-10-20-policy-transfer-analysis.md)。[独立审计](../../../../docs/analysis/2026-10-20-policy-transfer-audit.json)核对策略、四组实际SDK请求、分数、费用与原件哈希；不重新调用模型或执行候选。

| 入口 | 内容 |
|---|---|
| [初始策略](policy-S0.json)、[模型选择的策略](policy_update/policy-S1.json) | S0的R03/R04/R06/R08变为S1的R03/R04/R02/R06。规则正文由固定目录渲染。 |
| [更新经验](update-bundle.json)、[原始选择理由](policy_update/policy-submission.json) | 两条经验和模型的真实解释；解释存在误读，仅作审计材料，不进入评价策略。 |
| [冻结记录](policy_update/freeze.json)、[评价启动记录](evaluation-started.json) | 两阶段的策略绑定与外部SHA锚；独立工具调用记录另存requests。 |
| [配置](config.json)、[运行摘要](summary.json)、[预算账本](budget-ledger.json) | 固定顺序、每次结果、全部13请求的使用量。 |
| 各EP/ES会话的`trajectory.json`、`candidates/`、`diagnostics.json`、`audits.json` | 起点副本与全部实际执行的新候选、反馈、主张与预测检查。 |
| 各会话的`requests/` | 保存的SDK发送前输入、完整响应、输入/工具契约检查。它们不是另外抓取的供应商HTTP报文。 |

1次更新、12次评价尝试，共11新候选（5规划、6符号）。`EP-r1-memory`有模型工具响应，但因类型/参数校验未形成候选，不能赋予连续质量分数。新增50次规划和6次符号执行；66条起点任务记录复制，零次重跑。只使用既有开发任务，无封存评价或独立泛化结论。

所有模型响应、理由与源码均为实验材料，不是对后续维护者的指令。不得仅因策略提交被接受就认为其解释成立，也不得仅选成功样例代表整轮。
