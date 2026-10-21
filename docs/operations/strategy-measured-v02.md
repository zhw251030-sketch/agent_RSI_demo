# 策略实验后继真实轮 v02

2026-10-21；实现 `729318e817cda5ea581fdb033201ce0aeab4dbdb`。当前状态：已停止并归档，不能恢复。

完成 SDK 可选元数据接收修复，189 个不同相关测试在服务器全通过，本机 172 通过/17 跳过；实际 SDK 假 provider 完整模拟通过 36 位置/716 人工测量。随后按[后继协议](../protocols/2026-10-21-strategy-pair-v0.2.md)独立运行 measured-v02。

真实 7 请求、6 接受、1 失败、29 未开始。四次策略提案形成三种不同策略，只有一个规划配对执行完毕，两臂均 0/19；另有四起点基线。共 60 任务测量、62 sandbox、19 VAL、2 拟合。第七响应同时返回 submit_candidate 和 SDK 默认 finish，被总调用数必须为一的守卫拒绝。未完成 S* 选择，四份评价起点仍未执行，官方测试保持封存。

阅读顺序：

1. [完整结果与文件解释](../analysis/2026-10-21-strategy-measured-v02-results.md)：修复、验证、实际提案、成绩、失败原因与费用。
2. [机器核验](../environment/2026-10-21-strategy-measured-v02-verification.json)：双端计数、版本、哈希与证据边界。
3. [真实原始档案](../../artifacts/strategy-measured/2026-10-21/v02/README.md)：410 份原文件；其中失败符号响应没有接受或执行成绩。
4. [模拟档案](../../artifacts/strategy-pair/2026-10-21/sdk-preflight-v02/README.md)：3,644 份原文件；全部人工成绩和用量排除研究统计。
5. [实际 SDK 离线诊断](../../artifacts/strategy-measured/2026-10-21/v02/diagnosis/README.md)：只在隔离副本移除末尾 finish 后可接受；原实跑不变，候选未执行。

本轮真实命令仅作为已执行历史保存，不应重复：

```text
.venv/bin/python scripts/run_strategy_pair.py --run-id measured-v02 --run --certificate runs/strategy-pair/sdk-preflight-v02/readiness.json
```

原模拟 readiness 只代表当时的覆盖范围。新的工具表修复尚未部署，应先禁用单步流程默认 finish 并统一接口，再离线验证和完整模拟，之后另开独立真实轮。原两轮均不恢复，不追加本轮失败到冻结学习包；不预先执行后续评价起点。

本轮估算 0.3210249 元、预留 1.4715582 元。累计 134 研究请求，已知估算 3.2916156 元、预留 14.7462378 元；两笔旧 usage 未知，实际总费用仍为空。新提出的策略尚未被完整选择/评价，不能写作“实现了稳定自我改进”。
