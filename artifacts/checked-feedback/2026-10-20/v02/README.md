# checked-feedback v02 证据归档

运行：`20261020-checked-feedback-v02`；冻结提交：`e298713f575ea04d99984a32fc4c1f6dfbc6a5ce`；SDK 1.55.1。根汇总 `completed_with_stops` 表示 runner 已走完会话顺序，不表示完整机制对照完成。各条件实际产生的候选数量不同，symbolic_hidden 没有产生可执行工具调用；本轮不能作为检查反馈有效性的完整比较。

## 实际发生的工作

| 条件 | 模型请求 | 实际生成候选 | 评分与终态 |
|---|---:|---:|---|
| planning_hidden | 4 | 1 | 候选 0/10，十题均 invalid_output；SDK ERROR/MaxIterationsReached，runner stopped |
| symbolic_checked | 4 | 3 | train NMSE 1.0 → 0.09694020964575169 → 0.09639217003192727 → 0.09505566357265445；SDK FINISHED |
| planning_checked | 4 | 2 | 两个候选均 10/10；同分保留较早候选；SDK FINISHED |
| symbolic_hidden | 1 | 0 | 仅准备基线 train NMSE=1.0；SDK FINISHED，但唯一响应无实际 tool_calls |

共十份实际候选/基线源码：四份基线、六份生成候选。共 55 条任务执行记录：规划 50 条、符号训练拟合 5 条。没有封存评分、没有策略 S 更新。请求 1/2/3/9 均有 AgentErrorEvent 而无候选执行记录；未执行的提议保留在原始响应中，不计入六次生成候选执行。

第 13 次响应 `finish_reason=tool_calls`，但消息对象不存在 `tool_calls` 字段；内容中有未闭合的 JSON 风格候选提议。事件日志只有 assistant MessageEvent，没有 ActionEvent、ObservationEvent 或新候选。归档保留原貌，明确区分 SDK 的 FINISHED 状态与任务修订实际完成；不把文本里的提议作为工具调用执行，也不臆测这一不一致发生在服务端还是 SDK 转换层。

## 检查与用量

实际进入控制器的六份提交产生十二条主张：八条 supported、四条 schema_invalid。六次预测注册成功；事后预测四次 supported、两次 contradicted。这些计数只覆盖已执行提交；hidden 条件的检查虽被保存，模型当时不可见。支持某条有限谓词不等于整个解释成立。planning_checked 第二次预测 min_delta=0，评分维持 10/10 即满足它，不能解释成进一步提升。

共十三次响应、105,932 tokens（输入 86,530，输出 19,402）；未知 usage、未结算预约和失败请求均为 0。按保存单价估算 0.3446898 CNY，保守预留 1.3346382 CNY，均不是账单。账本没有 halted 或 halt_reasons；本轮存在会话停止和空工具调用异常，并非因金额/输入上限耗尽停止。

十三次完整请求均低于 98,304 字节上限，最小 17,044、最大 36,996 字节。请求逐项字节和 canonical SHA 与输入审计、账本一致；这些观测不能推出所有允许输入都能容纳。

## 文件与可追溯性

- `summary.json` / 各条件 `session-status.json`：紧凑派生汇总，保留原状态并添加归档解释。
- 各条件 `trajectory.json`、`diagnostics.json`、`evidence.json`、`audits.json`、`events.jsonl`：全部产物与反馈。symbolic_hidden 原始审计文件不存在，此处空数组表示零条审计，不是新计算。
- `candidates/`：十份源码按原始字节复制，保留 LF；SHA 见 `candidate-source-manifest.json`。
- `requests/*.response.json` 与 `input-audit-*.json`：全部十三份安全响应、十三份输入审计按原始字节复制。
- `request-index.json`：将请求、事件、源码 SHA、执行候选及输入中的最新状态连起来，明确区分四个未执行提议、真实执行、正常总结和第十三次异常响应。
- `manifest.json`：覆盖原始安全副本全部 97 个文件，保存长度、SHA 与复制/派生关系，并记录原始 tar 包 SHA。全部 tar 成员都已与副本逐文件核对。

完整原始请求、状态包、task-prompt 和重复 summary 没有复制入归档；保存它们的哈希及必要上下文摘录。没有复制密钥、主机名或私人绝对路径。整理仅做本机读取与归档写入，没有读取 API 凭据、调用模型、运行候选、修改旧运行或服务器。原始副本在整理前后的哈希一致。
