# SRSD-Feynman Easy val 自然域 replay

本轮在 FakeProvider 预演生成的 6 个候选结构上执行 model-free replay。参数只在每题 train 的 `fit_dev` 拟合，普通分数和自然域块分数全部来自冻结的 val 报告；没有读取 test，也没有新增模型调用。

| 槽位 | 编辑 | 普通 val ΔNMSE | 自然域改善 | 当前 dual gate |
| --- | --- | ---: | ---: | --- |
| `i12.1-r1` | keep | 0 | — | retain |
| `i12.1-r2` | swap | +0.00860 | 2/10 | retain |
| `i14.4-r1` | keep | 0 | — | retain |
| `i14.4-r2` | swap | −0.39811 | 7/10 | retain |
| `ii8.31-r1` | keep | 0 | — | retain |
| `ii8.31-r2` | swap | −0.00371 | 5/5 | allow |

这里的 ΔNMSE 定义为 candidate−parent，负数代表候选更好。`i14.4-r2` 的普通 val 改善很大，但三个自然域块退化，因此被保留父结构；这说明仅用整体验证集会把区域性退化误判成可靠改善。`ii8.31-r2` 同时满足事前 evidence= supported、普通改善和全部有效块改善，因此才通过当前 dual gate。

这些结果只验证评分绑定和门控动作，候选本身由 FakeProvider 预先指定，不能归因于 MiniMax，也不能推断外部 benchmark 性能。真实轮必须重新生成候选，并在真实请求结束后冻结动作再做同样的 val replay。
