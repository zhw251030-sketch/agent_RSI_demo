# 冷启动来源真实中止轮：独立只读复核

复核日期：2026-10-21。对象为 `artifacts/state-generation/2026-10-21/v01`，冻结实现 `cb40fee10a6f1f589328f8e3f8cbcc926b644c0d`。本次仅读取原档、源码与 Git 对象，并重算已有审计；没有模型调用、候选执行、公式拟合、probe 或封存数据访问，未改生产代码和原始归档。

结论：未发现阻断本次“记录一致但分配未完成”结论的矛盾。使用本机 Python 3.12.14 重新运行 `scripts/analyze_state_generation.py`，返回 `record_consistent_incomplete`；生成的 `tmp/state-generation-independent-audit.json` 与正式 `docs/analysis/2026-10-21-state-generation-audit.json` 逐字节相同。独立原档检查另见 `tmp/state-generation-independent-filecheck.json`。本复核没有扩大运行测试或补跑实验。

## 原始链路与停止

- `manifest.json` 中43份原始文件全部按实际字节重新计算，文件集合、逐文件哈希与整树哈希一致；整树为 `769fa632ad992506f2276d6d79ceb9c4891de1ad1f4b4549c153f698cd4577e5`。归档新增 README 和 manifest 不计入43份。
- 账本仅有连续的 `request-0001` 至 `request-0003`，对应三个实际请求文件及三份输入审计。三个均记录已预留且调用传输；单槽请求上限1，模型有效设置 `num_retries=0`，无 fallback，超时60秒。
- 前两个原始响应的 `submit_candidate` 业务字段，去除允许的 SDK 元数据 `summary/security_risk` 后，与 SDK 收据的 `source/n_params` 完全相同；其中源码 UTF-8 字节与保存的 `source.py` 相同。候选身份及提交尝试由现有审计交叉核验。没有把只出现于响应文本的程序当成 SDK 已接受提交。
- 前两个会话的 `status=stopped`、`ConversationExecutionStatus.ERROR` 必须结合事件解释：它们依次出现 ActionEvent、同一 tool_call_id 的 ObservationEvent，最后是 `MaxIterationsReached`，核心已接受源码。这是单次请求上限导致会话结束，不是源码缺失或候选执行失败。
- 第三个原始响应仅为 `Timeout`、HTTP408；会话汇总为 `ConversationRunError`，原因为 `LLMTimeoutError`。事件没有 ActionEvent，也没有 SDK 提交、候选或源码文件。它不能被解释为生成程序运行失败。
- 第三请求的账本 `usage=null`、`usage_state=unknown`，无伪造实际费用；账本 `halted=true`、原因 `usage_unknown`。总实际估算 `actual_estimated_cost_cny=null`。前两次合计6354 tokens、已知费用估算0.0316512元，三次保守预留合计0.298788元；预留不等于实际支出。
- 第三槽为 blocked，其余五槽保持 not_started、无会话目录或请求。摘要所称6份缺失/未尝试源码=1个已请求但失败槽+5个未开始槽；不是6次生成失败。记录和客户端设置支持无客户端重试、无恢复、无补抽，不提供供应商内部执行次数的独立证明。

## 源码冻结时序

`source-freeze.json` 包含完整8槽分配的终态及34份会话文件哈希，与 `summary.json` 的槽位记录完全相同。源码冻结哈希 `99c218339fdf02b016d9c0d99212123bcf7b1a01ae9bc2d96a882217de3839f8` 同时被摘要和静态报告引用。失败与未开始槽位也被保留，没有从冻结清单删除。

冻结实现中 `execute` 在请求循环结束/中止并再次核对运行与输入后，先 `freeze_sources`，再 `analyze_frozen_sources`；后者先核对34份会话文件与历史索引哈希，才解析新源码。核心提交检查仅处理字段、类型、大小和参数元数据，不先执行新候选或按 AST 质量选择保留。这里的“全部尝试结束”应理解为停止规则结束了本轮已获准进行的请求序列，并非8槽均已发出请求。

旧149份历史源码的 AST 索引属于请求前准备；这不违反“新生成源码冻结后才静态解析”的约定。代码顺序与哈希依赖提供可信记录器范围内的阶段证据，但文件没有外部时间戳签名，不能声称从独立时钟证明真实世界的先后顺序，也不能把本地哈希当作供应商认证。

## 结果边界与复现边界

两份源码均可解析、入口签名符合约定、彼此以及与149份历史索引无字节或 AST 碰撞。比较只忽略注释、位置等 AST 未保存信息，不验证变量重命名、代数或程序语义等价。因此不支持“语义上独立的新状态”“从未见过的任务”或新颖算法结论。

本轮候选执行、任务评分、probe、封存执行、策略更新均为0。规划源码正确性、资源可行性和 VAL 成功率未知；六参数符号表达式没有拟合或 NMSE，不能称为发现了 oscillator2 规律。没有生成任何评价角色源码，8槽批次不完整，不满足未来完整配对策略试验的启动前提；不能据此报告策略改善、跨任务优势、独立预测能力或 RSI 有效性。

本次独立核验使用 Python 3.12.14。正式记录已解释系统 Python 3.10 的历史 AST 哈希差异；本复核不再次运行3.10，不将其他解释器的拒绝混同为原档篡改或此次模型超时，也不改冻结索引使其兼容。后续重算应使用冻结实现及对应3.12环境。

已检查的操作说明和结果分析总体保留了这些边界；root 已确认将前两个 `MaxIterationsReached` 与第三个超时的区别补入结果说明。原轮应保持中止状态。若另开完整批次，必须事前冻结新批次与预算，不能将现有两份源码加上后补抽样冒称原先8槽完整完成。
