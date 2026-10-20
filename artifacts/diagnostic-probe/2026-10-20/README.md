# 无模型诊断重放

此目录保存上一轮候选的原件副本、人工局部修补及已有验收程序，共 10 份源码。**修补变体属于人工诊断干预，不能计入 Agent 生成成绩。** 原始候选仍完整保存在 `artifacts/pilot/2026-10-20/`。

- [manifest.json](manifest.json)：来源、固定哈希、干预说明和任务范围。
- [summary.json](summary.json)：70 次规划和 3 次符号评价的汇总及公开诊断。
- `sources/`：全部原件／变体副本。
- `patches/`：每个副本相对原件的明确 diff；原件的 diff 为空。

旧规划 002／003 在原件、仅修 at、再修 carrying 三种条件下均 0/10；手写验收程序 10/10。指标没有变化，但执行路径发生变化，详细解释见[离线诊断分析](../../../docs/analysis/2026-10-20-offline-diagnostic-probe.md)。模型调用和封存测试评价均为 0。

summary 中的 `feedback_files` 相对于服务器原始运行目录 `runs/diagnostic-checks/20261020-diagnostic-probe-v01/`，不是本快照内的文件；原始逐题日志留在服务器和本机忽略目录，核验哈希另存审阅记录。
