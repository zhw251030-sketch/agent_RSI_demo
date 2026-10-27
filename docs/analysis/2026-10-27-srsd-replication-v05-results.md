# SRSD-Feynman Easy replication v05 真实轮结果

## 目的

本轮在不改变模型权重、提示、候选编辑规则和 gate 阈值的前提下，加入两个独立物理语境的公开 SRSD Easy 任务，检验 Easy 轮观察到的证据门行为是否只依赖单一数据文件。`i.12.5` 与已有 `i.12.1` 同为双线性结构但数据分布和物理语义不同；`i.14.3` 为带系数缩放的双线性结构。

数据来源是公开的 [SRSD-Feynman Easy 数据卡](https://huggingface.co/datasets/yoshitomo-matsubara/srsd-feynman_easy)，test 在规则冻结前保持未读。本轮仍不是官方 leaderboard 实验，而是可复核的外部机制重复。

## 冻结与执行

两个任务各 8000 条 train、1000 条 val，train 固定为 4800/1600/1600 的 fit/check/outcome；每题 10 个有效自然域块。FakeProvider 预演 4/4 请求、12/12 gate、0 次真实调用后，才发送 4 次 MiniMax-M3 请求。

真实轮共 4/4 请求接受、4 次真实调用、12/12 gate、usage unknown=0；prompt 3914、completion 304、合计 4218 tokens，估算成本 0.010773 元。两个 swap 和两个 keep 均被接受；四个证据状态全部为 `unknown`。

## 冻结验证结果

真实候选在 val 上重新拟合 train 参数并固定预测：

| proposal | 普通 val ΔNMSE | 域块改善 | action |
| --- | ---: | ---: | --- |
| `i12.5-r1` swap | +0.001263 | 4/10 | retain_parent |
| `i12.5-r2` keep | 0 | — | retain_parent |
| `i14.3-r1` swap | −0.011869 | 8/10 | retain_parent |
| `i14.3-r2` keep | 0 | — | retain_parent |

`i14.3-r1` 的总体和域块结果都较好，但证据状态为 unknown，因此规则仍拒绝部署；这保持了“性能结果不能替代事前证据”的设计。

## 一次性 test 复核

在 val action 冻结后才读取 test。`i12.5-r1` 的候选 ΔNMSE 为 +0.001731，属于有害候选；`i14.3-r1` 的候选 ΔNMSE 为 −0.012827。候选有害数为 1/2，实际部署有害数为 0/4，因为四个 val action 全部为 retain_parent。

## 结论边界

本轮提供了跨物理语境的重复证据：只看 val 性能会接受一个未知证据候选，但固定证据门避免了 test 上的有害部署。它仍不能支持普适性或统计显著性；当前重复仅覆盖双线性族，下一步应增加经过数值缩放校准的新公式族。
