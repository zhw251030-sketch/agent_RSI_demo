# 工具响应契约核查与运行后保护修复

日期：2026-10-20。适用环境：OpenHands SDK/tools 1.55.1、LiteLLM 1.105.1、MiniMax-M3 的 Anthropic 兼容路径。

本文区分两类问题：v0.2 中部分工具参数的结构不正确，以及一次响应声称调用工具、却完全没有可执行工具调用。前者已有结构拒绝与反馈；后者被 SDK 当作正文结束，暴露了本项目响应契约的一项遗漏。本次修改只补上后一项保护，没有修复或猜测模型参数，没有修改已经冻结、运行的 v0.2，也没有启动第三轮模型实验。

## 1. 保存的嵌套参数异常出现在哪一层

证据目录为 `runs/checked-feedback/20261020-checked-feedback-v02/`。这些 `*.response.json` 是本项目在 LiteLLM 返回后保存的归一化响应，并非原始 HTTP 响应体。

`planning_hidden/requests/request-0002.response.json` 中，`claims` 有 14 项，其中 10 项是带 `$text` 的对象。本应位于引用对象中的 `task_id`、`version`、`scope`、`key` 等字段值被放入相邻数组项；这已经出现在保存的响应中，早于本项目的声明观察器及 SDK 的 Action 校验。其他规划响应也出现引用只有三个字段、其余字段移到顶层的情况。这样的参数不能被解释为有效声明。

只读检查安装版源码得到以下路径：

1. SDK `openhands/sdk/llm/llm.py` 的 `_transport_call` 调用 `litellm_completion`，返回 `ModelResponse`。
2. 本项目 [BoundedPilotLLM](../../rsi_eval/pilot_agent.py) 保存响应、核算 usage，然后 [StatePacketLLM](../../rsi_eval/checked_agent.py) 才观察声明结构。Agent 的工具参数解析与执行发生得更晚。
3. LiteLLM `llms/anthropic/chat/transformation.py` 的 `transform_response` 读取 `raw_response.json()`；`extract_response_content` 遍历 `tool_use` 内容；`convert_tool_use_to_openai_format` 对 `tool_use.input` 执行 `json.dumps`，生成工具参数字符串。该转换不重组引用的字段或声明的数组层级。
4. 请求方向的 `_map_tool_helper` 会调用 `sanitize_input_schema_for_anthropic`。用真实 request-0002 的 `submit_candidate` schema 离线经过安装版转换，整个 `parameters` 与转换后 `input_schema` 完全相等，`claims`、`prediction` 子树及引用要求的七个字段均保留。不是只比较了转换前的 SDK schema。
5. 将上述畸形 input 离线交给安装版响应转换函数，输出的 JSON 对象与输入完全一致，仍是 14 项声明和 10 个 `$text` 对象。对安装版 LiteLLM Python 源码的文本搜索没有找到 `$text` 字面量。

这些证据排除了目前检查到的本地观察器和 Anthropic 转换函数主动拆散对象的解释。但没有原始 HTTP 响应体，不能进一步确定是模型生成、提供商兼容层解析还是其他上游环节造成，也不能仅凭 `$text`/`item` 的外观认定某种 XML 解析器存在缺陷。离线转换只验证本地函数，不是对真实网络响应的直接重建。

同一轮中，符号侧返回过正确嵌套声明，规划第四次响应也形成可提交候选。因而结论是这个接口在当前任务、提示与模型设置下存在格式稳定性问题，不能写成“提供商不支持嵌套 schema”，更不能把格式失败解释为检查机制没有作用。声明语义是否合法仍由可信检查器判断。

## 2. 没有实际调用的 tool_calls 响应

`symbolic_hidden/requests/request-0013.response.json` 的事实如下：

| 字段 | 保存值 |
| --- | --- |
| `finish_reason` | `tool_calls` |
| `message.tool_calls` | 不存在 |
| `message.content` | 说明文字及未闭合的候选参数 JSON 片段 |
| prompt / completion / total tokens | 4607 / 925 / 5532 |
| 新生成且实际执行的候选 | 0 |

这里的输出 token 数低于 4096 上限，且 `finish_reason` 不是 `length`；这些记录没有给出常规输出上限截断的标记。它们不足以解释上游为何留下片段，也不能授权从正文补全候选、追加声明或执行代码。

安装版 `openhands/sdk/agent/response_dispatch.py` 的 `classify_response` 只依据实际 `message.tool_calls`、正文和 reasoning 判断响应类别。有非空正文而没有工具调用时，分类为 `CONTENT`；`_handle_content_response` 将会话设为 `FINISHED`。该分支不核对原始 `finish_reason`。本项目原来的 `BoundedPilotLLM` 只限制已有调用的数量与名称，因此也未拒绝这个组合；原 runner 随后记录 `completed`。

这意味着该会话完成了 SDK 的正文结束流程，没有完成一次候选提交。原始 `completed` 状态必须与“零生成候选、响应契约不一致”一起解释，不能将基线当作该条件的方法成绩。历史响应、事件、会话摘要和账本均保留，不回填成修复后的状态。

## 3. 本次运行后修复的精确范围

[checked_agent.py](../../rsi_eval/checked_agent.py) 新增 `IncompleteToolResponseError`，继承已有 `PilotResponseContractError`。仅在以下条件同时满足时拒绝响应：

```python
choice.finish_reason == 'tool_calls' and not choice.message.tool_calls
```

执行位置在 `BoundedPilotLLM` 返回以后、声明观察及 SDK 的响应分类以前。这时收到的归一化响应已经保存，usage 已完成结算。保护逻辑不读取正文以寻找 JSON，不补全、不重试、不提交候选，也不改变两组的声明检查规则、选择规则或模型参数。

新产生的 `input-audit-NNNN.json` 记录 `status=error`、固定 `reason=incomplete_tool_response` 及 `error_type=IncompleteToolResponseError`；请求预留、网络尝试标志保持真实值。SDK 将异常包装为 `ConversationRunError`，已有 `run_session` 会记录 `status=error` 和 `cause_type=IncompleteToolResponseError`。

费用账本仍为 `settled`、`usage_state=known`、`error_type=null`：这里表示传输和 usage 核算成功，不表示候选或会话成功。响应契约失败由输入审计和会话摘要表达，不能为了改状态再次结算已完成的请求。原始归一化响应文件保持收到的内容，不插入异常字段。普通 `finish_reason=stop` 的正文，以及真实存在的显式 `finish` 调用仍允许结束；这项窄保护不是“必须先生成候选才能结束”的新规则。

## 4. 实际验证

测试定义位于 [test_checked_sdk.py](../../tests/test_checked_sdk.py)。本机缺少 OpenHands SDK，因此有意义的 SDK 验证在服务器现有 1.55.1 环境完成：将修改后的两个 Python 模块编码传入内存，禁用字节码写入，输出仅写入自动清理的临时目录；模型 transport 和任务 evaluator 均为 mock，未修改服务器项目代码或历史运行文件。

- 修复前，新回归用例在 hidden/checked 两组、工具调用字段缺失/空列表四个组合中都复现错误的 `completed` / `FINISHED`；普通正文和显式 finish 对照通过。
- 修复后，完整 SDK 测试模块的 **11 项测试方法全部通过**（包含上述子用例）。验证了单次请求、零候选提交、不重试、原响应保留、5532 个已知 token、固定审计错误和正常结束对照。
- 此外直接加载完整的真实 request-0013 响应，在真实 SDK 会话中离线重放一次；得到 `error` / `IncompleteToolResponseError`，保存的 `choices` 和 usage 与原记录相等，只有一次 mock transport、零候选提交、5532 个已知 token。原记录只读。
- 原有四条件长历史替换、可见/隐藏检查反馈、工具 envelope、schema 拒绝恢复及预算拒绝测试继续通过。

回归用例内保存的是该真实响应关键字段及部分正文的投影，完整响应另以只读离线重放核对。测试结果证明新增保护及现有边界在这些输入下工作，不证明提供商以后一定输出有效工具参数，也没有新增科研性能或泛化结果。

## 5. 后续接口方案只作为备选

若继续改进格式稳定性，可先离线比较两个 JSON 字符串字段与可信证据 ID 方案。字符串方案需要严格解析，拒绝尾随内容、非有限数和重复键；SDK 自带的参数修复行为也必须纳入契约，不能只声明使用 `StrictStr` 就声称没有修复。证据 ID 方案由可信控制器精确映射到完整会话、候选哈希和证据字段，减少模型抄写七字段引用的负担，但它改变了声明接口，应在两组共同采用、独立冻结并披露。

两者都尚未实施或证明更好，不默认增加付费轮次。若将来专门验证兼容性，应使用预先限定的中性接口探针，并在不记录凭据的前提下保存原始响应的 `tool_use.input` 与归一化参数对应关系。本次只完成运行后的错误识别与保护，不修改 v0.2 的历史结论。
