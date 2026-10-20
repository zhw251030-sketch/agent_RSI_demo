# 可执行主张检查与有界上下文：开发对照 v0.1

日期：2026-10-20（Asia/Shanghai）。本轮在新增模型请求之前冻结。承接旧诊断对照暴露的上下文超限、规则误读和量级误判；旧轮次保持原样，不恢复、不追加额度。

## 问题与条件

本轮问题是：在相同任务观测、提交格式和搜索预算下，显示有限结构化主张的机器检查结果，能否帮助下一次修订？两个条件均提交主张和预测、均计算检查，只有 `checked` 向模型显示检查结果，`hidden` 隐藏检查结果。检查不阻止候选执行、不改写评分、不参与 best 选择；格式不合规的请求仍受共同工具接口限制。

固定顺序：planning_hidden、symbolic_checked、planning_checked、symbolic_hidden。每类每条件只有一个会话；没有独立重复或显著性检验。仍使用已见的 Spanner seed0/problem0..9（2 个公开输入、8 个开发评分）和 oscillator1/train、相同空计划/常数起点。这是基于旧案例设计的探索性开发，不是独立新状态验证。两边证据来源相同；checked 获得额外派生反馈，不能称为完整信息相同。

## 机器检查的确切边界

每次候选提交包含 1–2 个结构化主张和一个修改前预测，自由文本理由只存档、不由检查器认证。证据引用绑定 session_id（含运行 ID）、candidate_id、candidate_sha256、task_id、version、scope 和 key。只有上下文当前提供的 incumbent 或最新候选证据可以引用。

两条件的 claims+prediction 集合均限制在 2048 字节（Python JSON 默认 ASCII 转义编码）；格式非法的拒绝以固定枚举保留到下一请求。原始声明与完整检查保存在磁盘，上下文中的检查用候选 ID/claim_index 对应共同声明，避免重复原子及引用。设施错误或未完成的评分批次不提供数值证据，预测为 unavailable。

- `fact`：核对公开 PDDL 派生的规范化原子是否属于指定集合。参数用 `$0` 等位置标识并保留顺序；前提及效果分别记录正/负原子。公开 init/goal 也可检查。核心检查器不知道 Spanner 规则，不硬编码解题建议。
- `scalar`：核对可信分数/训练残差聚合与事前阈值。提供 MSE、NMSE、bias、abs_bias、RMSE、bias_squared_over_mse（分母为零则 unavailable）和固定分箱聚合。布尔值、非有限值不当作数字；空箱无标量。
- `prediction`：提交前持久化所引用旧候选的标量及 decrease/increase、非负绝对 min_delta，提交后用同任务/范围/指标的实际子候选核对。即使子候选未被选中也检查该子候选，而不是 best。分箱边界由固定训练 X 决定。

四种状态：supported、contradicted、unavailable、schema_invalid。数值容差固定为 `1e-10 + 1e-8 * max(abs(actual), abs(expected))`；严格大小必须超过容差，等号在容差内，非严格大小允许容差。缺失、错绑定、零分母不等于反驳。预测 decrease 为 before−after，increase 为 after−before，与 min_delta 比较。

正确引用一个动作前提不证明程序遵守了它；计划执行仍由 VAL 和可信重放检查。残差相关或预测兑现不证明物理因果、结构必要性、泛化或显著性。模型可以挑选平凡主张，因此报告全部主张数量、类型、覆盖及自由文本越界，不能把支持率当作整体解释准确率。

## 全输入控制

每次 transport 前以确定性状态包替换全部非 system/developer 消息：固定任务说明和公开例子、一个当前 best 完整源码、最新候选反馈、全部候选简表、当前 best/最新候选可引用证据，以及 checked 可见的检查记录。历史被拒源码和完整轨迹保留磁盘；输入明确声明省略，不把未命中或省略作为反证。不使用模型摘要，不截断源码，不追加摘要后继续发送旧历史。

单候选源码限制为 16,384 UTF-8 字节，两条件一致。请求按实际 SDK 传给 transport 的 model/messages/tools/tool_choice/max_output_tokens 对象、ensure_ascii=False/sort_keys=True JSON 测量，继续保持 98,304 字节上限。超限在网络前记录固定枚举原因、实际/上限/超出字节、payload SHA、transport_called=false，然后停止；不现场扩容或偷偷丢失必要信息。保留状态包与完整原始候选/诊断、请求/响应。离线验证四次请求、重复源码、非 ASCII 与工具 schema 开销后才能实际运行。

状态包本身另有 65536 字节上限；任务说明/公开例子/证据各≤32768，最新反馈≤32768，紧凑检查记录≤24576。受限声明和去重的检查视图通过连续三次大声明测试；不承诺所有极端文本组合都能发送。非法状态包在网络前记录 state_packet_contract，完整序列化尚未形成时字节数为空；这与已形成请求的精确字节超限区分。

## 运行边界

固定 MiniMax-M3、原端点/thinking-off、OpenHands SDK 1.55.1、工具 submit_candidate/finish。最多四会话，每会话三候选/四请求；总请求≤16、输出≤4096 tokens/次、输入≤98304 字节/次、保守预留≤3000000 tokens 和 10 CNY，归入项目原有 300 CNY 上限。沿用本日已核验的输入 2.1/输出 8.4 CNY 每百万 token 估算，并区分实际账单。旧未知费用继续保留。

无自动重试、无恢复。任一设施错误、预算拒绝、未知 usage 停止后续会话；未启动条件明确报告。所有 baseline 和观测一致性检查完成后才读取现有凭据。旧任务权限、沙箱、可信评分不变；封存数据不读不评分。策略 S 本轮固定，没有策略自动更新。

## 证据与输出

保存配置/提示/源码哈希、实际请求大小、完整候选与失败、评分、检查及事前预测、是否采纳、全部会话终态、真实用量/未知费用。先冻结代码并同步三处，再发起新轮次。报告完整矩阵，不挑最佳组。后续仍需新搜索状态、独立划分和重复；本轮不是正式 RSI 有效性证明。

CRITIC（ICLR 2024）已有工具验证—批评—修订及工具反馈消融；ProCo（EMNLP 2024）已有关键条件核验。本实现的明确谓词、绑定和反馈隔离是实验设计细节，不能据此声称方法新颖。来源：[CRITIC 正式论文](https://proceedings.iclr.cc/paper_files/paper/2024/file/fef126561bbf9d4467dbb8d27334b8fe-Paper-Conference.pdf)、[ProCo 正式论文](https://aclanthology.org/2024.emnlp-main.714.pdf)。
