# SRSD-Feynman Easy 真实轮结果

本轮在固定 MiniMax-M3、OpenHands SDK 1.55.1 和已冻结的 SRSD-Feynman Easy train/val 协议上运行。模型权重没有更新，真实轮只生成候选并完成 train `fit_dev/check_dev/outcome_dev` 的既定评分；随后在冻结的 val 自然域报告上做 model-free replay。

## 真实请求与候选

- 6/6 请求完成，6/6 候选被 SDK 接受，18/18 gate 记录生成；每个槽位一次请求、无重试。
- 5 个 proposal 是单项结构替换，1 个 proposal 保留父结构。
- 事前 evidence 为 1 个 `supported`、5 个 `unknown`；没有把未知证据自动当成可执行。
- MiniMax usage 全部可知：prompt 5712、completion 444、合计 6156 tokens，账本估算 0.0157248 元。

## 冻结 val replay

对真实候选使用 train fit 子集重新拟合参数，再在 val 全体和 25 个有效自然域块上固定参数预测：

| proposal | 普通 val ΔNMSE | 自然域块改善 | gate action |
| --- | ---: | ---: | --- |
| `i12.1-r1` | −0.387725 | 10/10 | retain（evidence unknown） |
| `i12.1-r2` | −0.321975 | 9/10 | retain（evidence unknown） |
| `i14.4-r1` | −0.882583 | 10/10 | retain（evidence unknown） |
| `i14.4-r2` | +0.002951 | 4/10 | retain |
| `ii8.31-r1` | 0（keep） | — | retain |
| `ii8.31-r2` | −0.003714 | 5/5 | allow |

ΔNMSE 定义为 candidate−parent，负值代表候选更好。前三个 swap 的数值结果很好，但 evidence 仍为 unknown，因此按事先规则保留父结构；这体现了“结果好”不能回写成“事前证据充分”。`i14.4-r2` 同时在普通 val 和自然块上较差，也被保留。只有 `ii8.31-r2` 满足三项条件，得到 `allow_after_val_dual_validation`。

## 证据边界与下一步

这轮证明了固定权重 Agent 的真实候选可以在新公开物理方程任务上进入同一证据门控和自然域验证流水线；它不证明跨任务泛化、统计显著性或最终 test 性能。SRSD test 仍保持未读取状态。下一步是冻结本轮 action 和所有哈希后，执行一次只读 SRSD test 描述性回放；test 结果不得用于修改本轮阈值或重新选择 proposal。
