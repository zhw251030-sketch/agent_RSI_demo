# SRSD-Feynman Easy 一次性 test 回放

本报告只读取 SRSD-Feynman Easy 的公开 `test` 行。读取前已经冻结真实 proposal、val 自然域规则和每个 proposal 的 `val_action`；回放不调用模型，也不修改阈值、候选或权重。

| proposal | val action | parent test NMSE | candidate test NMSE | 实际部署 NMSE |
| --- | --- | ---: | ---: | ---: |
| `i12.1-r1` | retain | 0.458969 | 8.22e−37 | 0.458969 |
| `i12.1-r2` | retain | 0.458969 | 0.079486 | 0.458969 |
| `i14.4-r1` | retain | 0.824122 | 2.60e−35 | 0.824122 |
| `i14.4-r2` | retain | 0.824122 | 0.828279 | 0.824122 |
| `ii8.31-r1` | retain（keep） | 0.003422 | 0.003422 | 0.003422 |
| `ii8.31-r2` | allow | 0.003422 | 1.17e−39 | 1.17e−39 |

如果不做 gate，6 个 proposal 中有 1 个 candidate 会在 test 上退化（`i14.4-r2`，ΔNMSE≈+0.00416）；按冻结 val action 部署时，有害部署数为 0。四个 `unknown` swap 在 test 上实际改善，但由于事前证据不足，仍被保守保留父结构。这说明本轮 gate 的作用是控制风险，而不是最大化单轮 test 分数。

## 证据边界

这是 3 个公开物理方程、6 个 proposal 的一次性描述性回放，不能支持统计显著性、普适泛化或对所有 SRSD/LLM-SRBench 任务的结论。test 文件哈希、下载地址、fit 来源、val action 和结果已绑定在[机器报告](../environment/2026-10-27-srsd-feynman-easy-real-v01-test-holdout.json)中；后续不得用这批 test 结果重新调 gate。
