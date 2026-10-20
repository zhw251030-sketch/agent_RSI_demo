# 配对修订 v01 完整证据归档

运行：`20261020-paired-repair-v01`；冻结代码：`5bb61dba33033e9dbd215efeca28b232ec844f8c`；OpenHands SDK 1.55.1；模型为 MiniMax-M3。根状态为 `attempts_completed`。八个会话各完成一次模型请求、一次真实候选执行，均为 `step_status=candidate_evaluated`。

这轮每个会话预先限定一个 SDK iteration。因此会话原始状态 `stopped`、`ConversationExecutionStatus.ERROR` 以及事件 `MaxIterationsReached` 均原样保留；这里的 SDK 终态表示到了预定边界，不能据此将已经执行的候选计为未完成，也不能据此忽略候选自身的失败结果。

## 配对起点与真实结果

P1 为旧检查轮 `planning_hidden/planning-001`，当时 0/10，且因同分未被旧控制器选中。本轮明确将这份程序本身作为新起点。S1 为旧检查轮 `symbolic_checked/symbolic-002`，train NMSE 为 `0.09639217003192727`。每个起点各运行 hidden/checked 两种条件、两次尝试，共八个会话。八份起点文件是对两个旧产物的复制，**没有重新执行基线，也不是八个不同的任务或独立起点**。

| 会话 | 实际新候选 | 新候选结果 | 本次主张 | 本次预测 |
|---|---:|---|---|---|
| P1-r1-hidden | 1 | 0/10 | contradicted | contradicted |
| P1-r1-checked | 1 | 0/10 | supported | contradicted |
| P1-r2-hidden | 1 | 10/10 | schema_invalid | supported |
| P1-r2-checked | 1 | 0/10 | contradicted | contradicted |
| S1-r1-hidden | 1 | train NMSE 0.004833343017581193 | contradicted | supported |
| S1-r1-checked | 1 | train NMSE 0.09588857767292072 | supported | contradicted |
| S1-r2-hidden | 1 | train NMSE 0.0958831006093933 | supported | contradicted |
| S1-r2-checked | 1 | train NMSE 0.09229497415800965 | schema_invalid | contradicted |

新执行共 44 次：规划 40 个实例、符号训练拟合 4 次。轨迹还包含 44 条复制而来的旧任务记录，不能加起来称为 88 次新执行。十六份源码全部按原字节保存，其中八份起点复制、八份本轮模型生成候选。

八次工具调用都实际进入控制器；主张结果为 3 项 supported、3 项 contradicted、2 项 schema_invalid，预测为 2 项 supported、6 项 contradicted。接口成功不等于证据声明正确，单个有限谓词成立也不认证整段理由。

这组结果没有显示检查结果可见时具有一致优势。两次尝试仍共享同一个开发起点，规划十题也由同一份生成程序一起完成，不能把它们作为独立机制样本计算显著性。没有封存测试评分，没有策略 S 更新，没有新方法或泛化结论。

## 比较范围和用量

四个配对均重新核对了真实请求：删除状态包中预先指定的 `checks_visible`、`audits`、`frozen_history_checks` 后，**完整公共状态包及包含系统提示、工具定义等字段的完整请求均逐字节一致**。仅检查结果字段可因条件不同；起点源码、参数数、历史声明、诊断和当前证据 ID 相同。证明见 `pair-input-verification.json`。

这里的请求指 SDK 发送前保存的消息与工具结构；未另捕获供应商原始 HTTP 报文。

检查组在第一次且唯一一次修订前看到的是冻结历史检查结果；新候选的事后检查已归档，但不会再触发第二次模型修订。因此这轮比较的是“同一起点上，历史检查结果是否改变下一次修订”，不是一个已经运行多轮的策略更新过程。

本轮八次请求全部 usage 已知：输入 74,548、输出 7,812，共 **82,360 tokens**。按配置单价估算 **0.2221716 CNY**，保守预留 **0.9782304 CNY**，不是供应商账单。账本无失败请求、无未知 usage、无未结算预约，也未触发预算停止。八次完整请求为 22,991–44,513 字节，均低于 98,304 字节上限。

## 文件与审查关系

- `summary.json`、`budget-ledger.json`、`config.json`、`base-config.json`：运行原始汇总、账本和配置，按字节复制。`run-outcomes.json` 是明确标记的简洁派生视图。
- 各会话 `trajectory.json`：对应原始 `candidates.json`，仅文件名映射，内容逐字节相同；所有候选的状态、理由、诊断、评分和选择结果均保留。
- 各会话 `candidates/`：全部十六份源码，字节数、SHA、角色、参数数和对应结果列在 `candidate-source-manifest.json`。
- 各会话 `diagnostics.json`、`evidence.json`、`evidence-registry-000.json`、`evidence-registry-001.json`、`evidence-registry.json`、`audits.json`、`repair-state-provenance.json`、`events.jsonl`：完整保留诊断、短 ID 到完整绑定的映射、声明展开、预测登记、事后结果和事件。
- 各会话 `requests/` 及 `task-prompt.txt`：完整保留八份真实请求、八份响应、八份输入审计和八份状态包，未对模型响应进行修复或重新执行。`request-index.json` 将请求 ID、工具调用、源码 SHA、实际子候选及 usage 连接起来。
- `manifest.json`：列出全部 148 个原始文件的长度、SHA 与归档映射，以及所有归档文件的哈希。原始 tar 包也已逐成员核对。原始副本在归档前后的哈希一致。

冻结控制器会在候选执行前写入原始声明、展开结果、注册父值和注册表摘要，再于执行后补充预测结果。这里收到的是终态 `audits.json`；运行未另存不可变的独立事前文件。本归档没有伪造这种文件，事前写入顺序的依据是冻结源码与对应回归验证，终态文件本身不构成独立时间戳证明。

所有原始文件均经过凭据、私人路径及服务器标识审查，本批次无需改写内容即可保存。因此原始摘要也按字节保留，并未制作隐式脱敏版本；派生文件均单独命名。整理仅在本地读取原始副本并写入本归档，没有访问凭据、调用模型、执行候选或修改旧运行、旧归档。
