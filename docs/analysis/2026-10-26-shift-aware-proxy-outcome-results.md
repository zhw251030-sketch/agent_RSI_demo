# Shift-aware v02 synthetic shift proxy outcome 结果

日期：2026-10-26  
真实 proposal 来源：`2026-10-26-v02-real-v01`  
机器记录：`docs/environment/2026-10-26-shift-aware-proxy-outcome.json`

本轮把真实 Agent 生成的 8 个 proposal 在 `fit_dev_v2` 上拟合参数，然后在输入变换后的 `synthetic_shift_dev` 上做固定参数预测。为了形成可计算的 proxy NMSE，复用了对应 fit 行的目标值；因此这是输入 shift 的工程诊断，不是物理上有效的 OOD benchmark。

| 指标 | 数值 |
|---|---:|
| proposal | 8 |
| synthetic proxy 退化 | 3 |
| 旧 replacement action 部署 proxy 有害 | 1 |
| shift-aware action 部署 proxy 有害 | 0 |
| shift-aware gate 相对旧 action 新增阻断 | 1 |
| 原 evidence gate 已保留的 proxy 有害 | 2 |
| 模型调用 | 0 |
| 官方 test/OOD 读取 | 否 |

这 3 个 proxy 退化候选都来自 synthetic shift 输入，最终均未部署。相较旧 replacement action，只有 bactgrow 的 1 个 supported 候选属于 shift-aware gate 的新增阻断；oscillator1 的 2 个候选原本已因 evidence contradicted 被旧 gate 保留。真实 action replay 仍显示 3 个 supported proposal 在 shifted 状态下全部变为 retain_parent，但其中两个在本 proxy 中并不构成新增阻断。由于 proxy 标签沿用 fit_dev，不能把这些计数写成真实 OOD 性能提升，也不能与最终 holdout 的 5/9 拦截数字合并。

本轮完成了从真实 Agent proposal 到 shift profile、固定参数预测、动作重放和审计记录的完整开发链路。下一步是对 proxy 失败案例做逐任务分析，决定是否需要新的开发切分或 shift 指标；若要形成论文级结论，还需在未参与本轮设计的新 holdout 上重新预注册。

