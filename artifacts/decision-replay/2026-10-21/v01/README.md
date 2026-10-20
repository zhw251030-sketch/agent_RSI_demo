# 冻结检查证据回放的决策实验

运行版本 `ede8fc7`；服务端 `runs/decision-replay/20261021-decision-replay-v01` 的303份原文件全部逐字节复制。
本目录新增manifest.json、README.md不计入303份。原文件哈希和树摘要见manifest。

四个已见开发案例 × 两次生成重复 × hidden/checked = 16模型请求、16候选，0缺失；新增88任务评价、96次sandbox，0新probe、0封存评价、0权重/S更新。
inputs/cases.json固定研究者已见的旧状态与白名单观测；sessions/包含每次实际请求、响应、SDK dispatch、完整候选及逐题评价。
每案例四个实际SDK请求删除唯一probe_feedback字段后相同。summary中的最终status为attempts_completed；旧源码和旧分数没有重写。

见[完整结果](../../../../docs/analysis/2026-10-21-decision-replay-results.md)。回放验证反馈使用，不能当作独立任务泛化或新的完整两阶段实验。
