# Shift-aware outcome gate v03 fake round 结果

日期：2026-10-26  
运行：`2026-10-26-v03-fake-v02`  
机器记录：`docs/environment/2026-10-26-shift-aware-v03-fake-v02-verification.json`

本轮把已有 v02 fake runner 与 v03 outcome wrapper 串成一次完整离线链路：FakeProvider 通过 OpenHands SDK 生成 proposal，v02 runner 冻结 evidence/gate/round summary，v03 wrapper 再读取冻结记录、执行开发期 proxy 预测并输出 old/v02/v03 三套动作。整个过程没有 MiniMax 请求，没有官方 holdout 访问。

## 机器结果

- FakeProvider：8 次请求，8/8 accepted slots，24 条 gate 记录；
- 真实模型调用：0；synthetic tokens：960；
- v03 proposal：8；v03 sandbox calls：24；
- `supported_proposals=0`；5 个 proposal 为 defer，3 个为 retain；
- 官方 `test_id/test_ood`：均未读取。

## 解释

这轮验证了 SDK、预算、round summary、v03 proxy 和三套动作字段可以在同一运行链路中连接起来，并验证了 unknown/contradicted 分支的保守动作。FakeProvider 的固定回复没有产生 supported proposal，因此本轮没有观察到 `allow_after_validation` 分支，也不能把 fake round 写成 outcome gate 的正向效果证明。supported 分支已经由真实 proposal 的 v03 replay 和 7-case action contract 覆盖。

下一步若启动真实 v03 开发轮，需要先保持 8 槽预算和现有 holdout guard，确认真实 proposal 中同时出现 supported、contradicted、unknown 后，再比较 v02 hard shift 与 v03 outcome 的动作变化。
