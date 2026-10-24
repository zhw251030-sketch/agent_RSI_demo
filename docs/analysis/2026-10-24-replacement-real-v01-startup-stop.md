# replacement 真实轮启动停止记录

日期：2026-10-24  
运行目录：服务器 `runs/replacement-agent-round/2026-10-24-real-v01/`  
状态：在第一个模型请求前停止。

## 发生了什么

真实 runner 已通过 v04 fake-provider 证书、代码保护路径检查、split report/runtime lock 检查，并创建了新的 12 槽账本。随后按用户此前提供的路径尝试读取：

`/home/hanwen/Project/project/siNRA-pi/docs/auth.json`

服务器返回 `FileNotFoundError`。runner 在读取 auth 文件阶段停止，尚未创建任何 OpenHands provider 请求。

## 账本证据

- `model_requests=0`；
- `request_count=0`；
- `reserved_count=0`；
- `usage_unknown_count=0`；
- 实际 token 和估算费用均为 0；
- 没有候选、拟合、gate 或 `outcome_dev` 结果写入该真实轮。

服务器上发现的其他 `auth.json` 文件属于 siNRA-pi 运行时或 Codex 组件，均未通过本项目要求的“单个非空 token 文件”校验；它们没有被读取为模型凭据，也没有被尝试用于真实请求。

## 后续条件

真实轮只需在服务器上恢复原路径，或提供一个正确的只读 token 文件路径，然后使用新的 run-id 重新启动。`real-v01` 不恢复、不补抽、不重用账本；它作为启动前配置停止记录保留。该停止不改变 v04 fake 预演证书和代码。

