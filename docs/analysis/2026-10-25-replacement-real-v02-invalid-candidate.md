# replacement 真实轮 v02 无效候选记录

日期：2026-10-25（中国标准时间）  
运行目录：服务器 `runs/replacement-agent-round/2026-10-24-real-v02/`  
状态：第一个 actor 槽位后按协议停止。

## 请求和账本

- 真实 MiniMax-M3 请求：1；
- 接受候选：0；
- usage：已知，`prompt_tokens=1227`、`completion_tokens=92`、`total_tokens=1319`；
- 估算费用：0.0033495 元；
- 后续 11 个请求：未发送；
- fit、check、gate、outcome_dev：均未执行。

## 无效原因

provider 返回了一个结构正确的 `submit_basis` 工具调用，工具名和参数 JSON 均通过外层 envelope 检查，但 `feature_ids` 没有包含编译器要求的常数特征。宿主的 `compile_submission` 因 `the constant feature is mandatory` 拒绝该候选。

这不是传输错误、usage unknown 或 sandbox 错误，也不是模型权重更新。它是一个被固定业务契约拒绝的结构无效候选；本轮没有重试或补抽。

## 修复方向

在不改变候选空间和 gate 规则的前提下，下一版 actor system prompt 与 packet 会明确写出：父结构中的常数 feature 必须保留，合法候选只能是父结构原样或恰好一次 feature swap。之后先重新跑 12 槽 FakeProvider + Linux sandbox 预演，再用新的真实 run-id 启动。该提示修复会被纳入受保护代码路径，旧 v04 证书不会继续授权新的真实轮。

