# MiniMax-M3 配置与连接验收（2026-10-20）

用户已指定复用另一项目的 MiniMax 密钥。本项目已保存并激活 Canvas 模型配置 `minimax-m3`，网页显示该配置，实验 SDK 与网页后台 SDK 的工具往返检查均已通过。

## 当前配置

公开配置在 [configs/models/minimax-m3.json](../../configs/models/minimax-m3.json)：

| 项目 | 当前值 | 原因 |
|---|---|---|
| 实际模型 | `MiniMax-M3` | 沿用用户指定模型；不替换为 M3.1-Flash |
| SDK 路由名 | `anthropic/MiniMax-M3` | `anthropic/` 表示协议适配器，并不意味着调用 Claude |
| 接口 | `https://api.minimax.cn/anthropic` | 沿用参考项目的 MiniMax 中国区 Anthropic 兼容接口 |
| thinking | disabled | 沿用参考项目的 off 设置；后续推理实验可另设对照 |
| 单次输出上限 | 4096 tokens | 沿用参考项目配置；它不是整轮实验的总预算上限 |
| 自动重试 | 0 | 连接准备阶段避免错误请求自动重试造成额外消耗 |
| 超时 | 60 秒 | 限制单次请求等待时间 |

`reasoning_effort` 明确写为 `none`，并设置 `supports_reasoning_effort=false`。原因是当前 SDK 保存时会把 null 恢复为默认 high；MiniMax-M3 的 thinking 开关与 M3.1-Flash 的 effort 档位并不相同。请求另外显式携带 `thinking.type=disabled`。保留完整消息块序列化，避免随意截断工具调用历史。

## 密钥如何保存

提供的 `auth.json` 实际为单行密钥，不是 JSON 对象；源文件未改动。配置脚本只在服务器内存中读取它，并提交到本项目回环地址的 Canvas 配置 API。Canvas 用已有加密密钥保存模型凭据，文件位于被 Git 忽略的 `.canvas-state/` 中；检查未发现该状态目录中包含模型密钥明文。

实验 SDK 使用被忽略的 `config.local.json` 记录源文件路径，权限为 0600；其中没有再保存一份明文模型密钥。也可用 `MINIMAX_API_KEY_FILE` 指定来源。凭据未复制到本机，未写入公开配置、输出或 Git。

在服务器项目根目录重新配置：

```bash
.venv/bin/python scripts/configure_minimax.py
```

首次在新服务器配置时，提供 `--auth-file /absolute/path/to/existing/key-file`。参数是文件路径，不是密钥内容。该脚本保存并激活配置，本身不调用模型；源密钥轮换后需重新运行它，更新 Canvas 的加密副本。

## 已验证到什么程度

[check_minimax_connection.py](../../scripts/check_minimax_connection.py) 用一个只能在内存中求和的工具检查模型：请求计算 19+23，验证模型返回的函数名与参数，把结果 42 回传，再检查模型回复 42。没有暴露 shell、文件工具或运行生成代码。

| 环境 | 结果 | 最终检查请求数 | 记录的输入 / 输出 tokens |
|---|---|---:|---:|
| 实验 SDK 1.55.1 | 工具往返通过，最终回复 42 | 2 | 713 / 36 |
| Canvas 后台 SDK 1.56.0 | 工具往返通过，最终回复 42 | 2 | 713 / 36 |

每个验收请求最多输出 256 tokens。另有三次调试请求收到响应，以及两次在网络发送前失败的本地导入检查；没有隐藏失败尝试。首次探针错误地按原始 OpenAI 响应读取 SDK 对象，已修正字段访问；一次中间断言失败未记录足够细节，不能据此判断模型可靠性，现已补充失败阶段信息。最终四次请求共记录 1498 tokens；前三次调试响应未保存 token 用量，因此这不是完整账单，也不声称消费为零。

完整记录见 [验收 JSON](../environment/2026-10-20-minimax-verification.json)。这是连接与工具协议检查，**正式 Agent rollout、规划/符号任务实验仍为 0**；网页对话、流式响应、复杂推理和长上下文尚未完成端到端测试。首页模型下拉框已显示 `minimax-m3`，此前未配置模型提示消失。

如以后需要复查连接（会产生两次模型请求）：

```bash
.venv/bin/python scripts/check_minimax_connection.py --output tmp/minimax-check.json
```

## 同时修复的依赖问题

实际带工具请求暴露实验环境 `litellm==1.106.0` 与 `mcp==1.28.1` 的运行时冲突：LiteLLM 导入 MCP 2 才有的 `CacheableResult`。此前 `pip check` 通过，是因为相关要求属于可选依赖，未覆盖这条运行路径。

仅将实验环境 LiteLLM 固定为 **1.105.1**；SDK/tools 仍为 1.55.1，MCP 仍为 1.28.1。网页后台本来就是 LiteLLM 1.105.1，无需修改。更新了 `requirements/openhands.in` 与实际版本锁，并通过 `pip check`、真实工具请求及返回验证。替换包的官方来源和 SHA-256 保存在本轮验收 JSON 中；此前安装报告保留为历史快照。

这与 [OpenHands SDK 1.56.0 官方兼容约束](https://github.com/OpenHands/software-agent-sdk/blob/v1.56.0/openhands-sdk/pyproject.toml) 一致，其中明确限制 LiteLLM `<1.106` 以兼容 MCP 1.x。

## 后续使用边界

网页仍通过 http://127.0.0.1:18080/ 打开。刷新首页后若显示 Open Workspace，可从已登记的列表再次选中 `agent_RSI_demo`。完整 Agent 编排、任务执行器和生成代码隔离仍需后续接入，不能用此次算术工具检查代替研究实验。

模型选择已确定；此前人民币 300 元总预算仍有效，但目前没有自动强制的项目总费用限额。正式实验前需要增加预算记录、停机条件和实际账单核对，不能把未知计费或界面 0 值视为免费。

接口与参数依据：[MiniMax 官方 Anthropic 兼容接口](https://platform.minimax.cn/docs/api-reference/text-anthropic-api)。
