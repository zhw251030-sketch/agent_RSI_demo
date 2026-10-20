# checked-feedback v01 停止事件与证据边界

日期：2026-10-20。运行：`20261020-checked-feedback-v01`；冻结代码提交：`c4d4f60f852208494e214bd226882e532172c799`；OpenHands SDK：1.55.1。证据入口：[归档说明](../../artifacts/checked-feedback/2026-10-20/v01-stopped/README.md)、[紧凑汇总](../../artifacts/checked-feedback/2026-10-20/v01-stopped/summary.json)、[请求对应表](../../artifacts/checked-feedback/2026-10-20/v01-stopped/request-index.json)、[文件清单](../../artifacts/checked-feedback/2026-10-20/v01-stopped/manifest.json)。

本轮因 SDK 工具封装字段与额外格式观察器不一致而人工停止。观察器将实际能够执行的提交标为 `submission_schema`，错误标记又进入后续状态包。同时，进入检查器的全部八条主张、五个预测都使用了不合规的证据引用，未产生有效语义检查。**本轮是故障运行，不能判断显示检查反馈是否有益，也不能与另一条件或旧轮次做方法优劣比较。**候选的可信执行和开发评分仍是实际发生的记录，须与错误提示分开保存。

## 发生了什么

1. 首次规划响应带有 SDK 工具封装字段 `summary`、`security_risk`。冻结版本的 `_observe_submission_schema` 对整个参数对象直接调用 `CheckedCandidateAction.model_validate(arguments)`，留下 `invalid_request/submission_schema`。
2. 实际 SDK 仍执行该响应对应的 `planning-001`：保存了匹配源码 SHA、十条任务结果、`ActionEvent` 和 `ObservationEvent`。第二次请求的状态包同时包含 `latest_candidate=planning-001`、剩余候选数 2 和错误的 `last_tool_validation` 标记。因此该标记不能解释成“第一次候选未执行”。这不是只靠模型口述推断；[请求对应表](../../artifacts/checked-feedback/2026-10-20/v01-stopped/request-index.json)保存了逐请求的对应关系。
3. 第 2、3 次规划响应还存在真正的提交结构错误。第 2 次把 `kind/op/value` 等字段散落在顶层；第 3 次的 `claims` 是对象而非列表，且缺少有效 `prediction`。事件日志为二者记录 `AgentErrorEvent`，没有对应候选文件或候选记录。它们必须与第 1、4 次实际执行的规划提交区分。
4. 第 4 次规划响应执行 `planning-002`，随后达到 SDK 四次迭代上限。事件日志以 `ConversationErrorEvent/MaxIterationsReached` 结束；保存的会话终态为 `ConversationExecutionStatus.ERROR`，runner 将其分类为 `stopped`，`model_error_type` 为空。这个 `stopped` 状态未阻止下一条件启动。
5. 第 5–7 次响应在 symbolic_checked 中执行三个候选；第 8 次响应调用 `finish`。人工停止记录时间为 `2026-10-20T05:39:59.480118+00:00`，当时第 8 次请求已在途。账本被写入 `operator_stop_sdk_envelope_validation_mismatch`，禁止后续预约；第 8 次仍正常结算。另两条件未启动模型会话，仅保留准备阶段的基线。

第 1、4、5、6、7 次实际提交都被额外观察器标为结构错误；第 2、3 次确有独立的结构问题。冻结观察器把两类情况压成同一条提示。后续修复必须以 SDK 实际封装/解析规则为依据，并用含 `summary/security_risk` 的真实响应形状验证；本归档不把之后的修复或新运行追溯套用于 v01。

## 实际执行矩阵

| 条件 | 模型请求 | 实际生成候选 | 开发结果 | 保存终态 |
|---|---:|---:|---|---|
| planning_hidden | 4 | 2 | 基线及两候选均 0/10 | `stopped`；SDK `ERROR/MaxIterationsReached` |
| symbolic_checked | 4 | 3 | train NMSE：1.0 → 0.09694020964575169 → 0.09505566357265445 → 0.09376229967010528 | `completed`；SDK `FINISHED` |
| planning_checked | 0 | 0 | 仅准备基线 0/10 | `not_started_after_stop` |
| symbolic_hidden | 0 | 0 | 仅准备基线 train NMSE=1.0 | `not_started_after_stop` |

全部四条件共有九份实际候选/基线源码：四个准备基线、五个模型候选。运行保存了 45 次任务执行记录，其中规划 40 次（四个规划产物各十题），符号 5 次（两个基线及三个候选各一次训练拟合）。没有封存集评分，没有策略 S 更新。第 2、3 次规划请求中的未执行源码完整留在原响应里，不计入九份候选文件或五次候选提交。

## 检查反馈为何无法支持本轮比较

实际进入控制器审计的五个候选共产生八条主张：planning_hidden 为 1+2 条，symbolic_checked 为 1+2+2 条；八条全部是 `schema_invalid/reference_schema_invalid`。五次预测注册全部是 `schema_invalid/prediction_schema_invalid`，后续五次预测核查均为 `schema_invalid/registration_schema_invalid`。这里的“八条”不包括在 SDK 层即失败、未进入控制器审计的请求内容。

已审计引用采用了 `reference: {binding: {...}, key: ...}`，而契约要求绑定字段与 `key` 在 `reference` 内同一层；部分声明还缺失绑定字段，或引用不存在的 `atoms`。结构错误不表示命题被反驳，也不表示预测兑现或失败。检查器没有得到可用于这些判断的合法输入。

symbolic_checked 的第三次候选理由称前两次“被拒绝、未执行”，但保存的 `symbolic-001/002` 源码、成功状态和拟合分数证明它们已经执行。下一输入同时提供了额外错误标记、真实声明格式错误及实际评分，后续模型确实混淆了“声明不合规”和“候选未执行”；本轮无法分离两种错误对行为各自的影响。这个观察是接口故障和解释失真的案例，不能当作“语义检查纠错能力弱”或“隐藏反馈更好”的结论。

## 最后总结还出现了产物描述错位

最终响应中部分分数与历史一致，但公式描述并不可靠。按实际源码应记录为：

| 候选 | 实际返回的结构 |
|---|---|
| symbolic-000 | 常数 `c0` |
| symbolic-001 | `c1*x + c2*v` |
| symbolic-002 | `c1*x + c2*v + c3*x**3` |
| symbolic-003 | `c1*x + c2*v + c3*x**3 + c4*v**2 + c5*x**5` |

第 8 次响应把基线写成 `c0*x`，将第一候选写成已含三次项，并把第二候选写成已含五次项；这些说法与原始源码不符。它对结构“主导增益”等叙述也不能替代可执行产物核验。该差异进一步说明，模型总结不能作为实验事实来源。保留全部八份响应是为了复查这些错误，不是认可其中的机制或因果解释。

## 输入与费用证据

规划四次实际请求为 22,663、29,185、29,185、29,185 字节；符号四次为 15,017、16,970、19,232、21,517 字节。八次均低于固定 98,304 字节上限，`excess_bytes=0`。归档按原请求对象的 canonical UTF-8 JSON 重算哈希和字节数，与输入审计一致。本轮没有因输入长度停止；这只证明这八个实际输入合规，不证明所有允许文本组合都能容纳。

八次请求全部返回已知 usage：输入 50,142 tokens、输出 11,395 tokens，总计 61,537 tokens；本轮未知 usage、未结算预约和失败请求数均为 0。按保存单价估算费用为 **0.2010162 CNY**，累计保守预留为 **0.7970802 CNY**。这不是服务商账单；此前其他轮次的未知费用仍然保留。本次停止是人工故障停止，不能被根汇总的通用 `budget_halted` 文本误读成花光金额、token 或请求额度。

## 归档与后续边界

归档目录为仓库根下 `artifacts/checked-feedback/2026-10-20/v01-stopped/`。`manifest.json` 覆盖原始安全副本的全部 74 个文件，保存逐字节 SHA-256、长度及复制/派生关系；九份源码保留全部原始字节及 LF。全部八份响应和八份输入审计原样保存，完整原始请求和状态包只保存哈希与必要上下文摘录，避免把整份重复历史加入仓库。两个未启动条件的空审计数组明确代表“无审计记录”。

本次整理仅读取本机安全证据副本，没有加载 API 密钥、请求模型、重跑候选、读取封存数据或修改旧运行。旧文件在整理前后的哈希一致。v01 保持停止状态；若修复后运行新版本，应作为新的、单独冻结和计费的开发尝试，不恢复 v01，不把新分数拼接到本矩阵。
