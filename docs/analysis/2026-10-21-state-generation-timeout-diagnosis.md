# v01 第三次生成请求超时：离线诊断

诊断起始版本 `de372716c517db9a53db8b97b14ad21f8440dc26`。只读取冻结原档、服务器原始运行文件元数据和已安装依赖源码；未读取凭据，未调用 API 或执行候选。

## 可确定的结论

1. `artifacts/state-generation/2026-10-21/v01/generation-settings.json` 的 `public.timeout` 和 `effective.timeout` 均为60，实际输出上限8192，SDK `num_retries=0`、`stream=false`、`fallback_strategy=null`。原第三响应只有 `error_type=Timeout,http_status=408`；会话记录为 `ConversationRunError`，原因 `LLMTimeoutError`，没有 tool dispatch 或候选，usage未知。
2. 真实运行目录中的 request/response 文件字节哈希与归档一致。文件mtime差分别为 P-select-1 **37.232067846秒**、S-select-1 **26.927771815秒**、P-eval-1 **60.098721207秒**。这些是原始文件写入间隔，不是当时登记的单调时钟耗时；文件系统元数据未进入原字节归档，不能冒称原协议已记录精确请求延迟。第三次接近60秒与客户端配置相符，但单凭这个间隔不能证明根因。
3. 第一与第三规划请求的字节内容相同，原文件SHA256均为 `5a598d97a246a1dd8f8af5e5044743fcb095ebf3c01b2b59a430f1694d7cba24`；账本canonical payload SHA256同为 `1d34d037838f4eb091d51a0dcad2714505d20fac4106669d429e9eb75fe77125`。角色没有进入请求。这不排除服务时延或模型输出长度的随机变化；第三次没有输出/usage，不能估计其生成量。
4. 服务器实际版本：OpenHands SDK **1.55.1**、LiteLLM **1.105.1**、HTTPX **0.28.1**。Anthropic SDK 0.76.0虽安装，但本路径是 LiteLLM Anthropic handler 的 HTTPX 同步POST，不是直接调用 Anthropic Python SDK。

## timeout 传播与408的证据

以下依赖路径均相对服务器 `/home/hanwen/Project/project/agent_RSI_demo/.venv/lib/python3.12/site-packages/`。

| 路径与行号 | 证据 |
|---|---|
| 项目 `scripts/run_checked_feedback.py:112`、`:125`、`:132` | 旧公用模型配置校验锁定timeout60，effective仅覆盖输出与无重试等设置，没有覆盖timeout；旧文件受历史运行冻结约束，不能就地改成180 |
| 项目 `rsi_eval/pilot_agent.py:156`、`:178`、`:208` | 同步传输守卫显式把max_retries设0；异常只保存安全类型/状态码，最后以usage=None结算 |
| `openhands/sdk/llm/llm.py:2496`、`:2511`、`:2517`、`:2529` | `_prepare_transport_kwargs`把`self.timeout`和`max_retries=0`送给`litellm_completion` |
| `openhands/sdk/llm/llm.py:1141`、`:1154`、`:1816` | SDK外层同步重试装饰器读取`num_retries`；本路径没有async hard-timeout装饰器，不能把HTTP timeout说成强制总墙钟截止 |
| `litellm/main.py:5520`、`:2919`、`:2934` | completion解析timeout后将其传给Anthropic chat handler |
| `litellm/litellm_core_utils/completion_timeout.py:33` | 显式model_timeout优先于kwargs/global timeout，随后转float；显式180不会被默认全局值替换 |
| `litellm/llms/anthropic/chat/handler.py:498`、`:503`、`:508` | 同步非流式分支创建HTTPHandler并调用client.post(...,timeout=timeout) |
| `litellm/llms/custom_httpx/http_handler.py:1471`、`:1488`、`:1496`、`:1516` | HTTPX request得到timeout；捕获httpx.TimeoutException后转成litellm.Timeout |
| `httpx/_client.py:371`、`httpx/_config.py:127` | 标量timeout转换为connect/read/write/pool各阶段限制，不能承诺全过程恰好180秒退出 |
| `litellm/exceptions.py:356`、`:374` | LiteLLM Timeout默认`status_code=exception_status_code or 408`；本地超时也能产生408 |
| `litellm/litellm_core_utils/exception_mapping_utils.py:598` | 服务错误status408也会映射为Timeout，因此同一最终类型可以来自不止一条路径 |
| `openhands/sdk/llm/exceptions/mapping.py:52` | LiteLLM Timeout进一步映射为LLMTimeoutError |

用冻结公开设置和占位密钥实例化SDK，只执行`_prepare_transport_kwargs`、不调用provider，确认生成的安全字段为timeout60、max_retries0、num_retries缺省、streamFalse、max_tokens8192。这是当前安装版本的离线传播证据，不是补造v01发送前收据；v01 `*.request.json`本来未记录timeout。

因此最准确的表述是：**本地调用链记录了一次60秒配置下的超时，并将它标为408；现有原档无法区分HTTPX连接/读取/写入/连接池超时，也无法排除真实服务408。** 原档未保留异常全文、内部cause链、response.headers或网络追踪，不能进一步断言服务负载、服务器拒绝或模型规划难度是根因。相同请求一次成功一次超时，也不证明候选程序执行失败。

## 最小新批次建议

新增版本化配置/runner，把effective timeout显式设为180；保留8个全新槽位、原提示、相同8192输出上限、原请求/费用预算、SDK num_retries0、LiteLLM max_retries0、无流式/恢复/fallback。旧配置与公用校验器保持原样；新配置明确记录对60秒基配置的唯一运行覆盖。180是等待容忍度调整，不是已验证的故障修复，也不保证不会再次超时。

在真实`openhands.sdk.llm.llm.litellm_completion`调用边界增加只含允许字段的事前收据，绑定同session已持久化request文件，并记录单调时钟elapsed、returned/raised和安全异常类名。不得保存密钥、headers、任意kwargs或异常文本。包装必须在网络前拒绝timeout不是180、非零retry、stream、第二次dispatch及已有收据，保证无隐性补抽。原8槽全部重新冻结生成，不拼接v01的两份源码；任何未知usage仍停止新批次，保留旧笔未知费用。

本诊断没有实施配置变更，也未启动新批次。正在独立实现该最小transport收据模块和离线测试；不修改历史SDK适配器。
