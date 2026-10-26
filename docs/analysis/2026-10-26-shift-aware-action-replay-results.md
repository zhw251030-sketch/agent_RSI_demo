# Shift-aware v02 covered/shifted action replay 结果

日期：2026-10-26  
输入 round：`2026-10-26-v02-fake-v06`  
机器记录：`docs/environment/2026-10-26-shift-aware-action-replay.json`

本轮在不调用模型、不执行候选程序的情况下，把同一批 8 个 v02 proposal 的 evidence 状态分别放在 `covered` 和 `shifted` 两种输入状态下重放。规则是：只有 `supported + covered` 才执行候选；`supported + shifted`、`contradicted` 和 `unknown` 均保留父结构。

结果：8/8 proposal 被覆盖，`covered_execute=0`、`shifted_execute=0`、`changed_on_shift=0`。原因是 FakeProvider 产生的 4 个 swap proposal 均为 `contradicted` 或 `unknown`，没有 `supported` proposal。因此本轮没有观察到动作变化，但动作绑定本身通过；`supported+shifted` 的正向变化已由 16-case synthetic action/outcome preflight 单独验证。

本轮不构成机制效果结论。下一步真实 v02 round 使用 MiniMax 生成 proposal，完成新的开发证据后，再执行相同 covered/shifted replay。

