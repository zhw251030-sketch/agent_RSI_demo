# 真实诊断对照候选与反馈

来源：`20261020-diagnostic-comparison-v01`，代码 `c36af55`。本目录包含 9 个模型候选和六个固定起点副本，源码逐字节保留，未人工修复。三组仅完成起点评价后未启动，其目录不能被当作完整会话结果。

| 目录 | 实际状态 | 模型候选结果 |
|---|---|---|
| [planning_A](planning_A/trajectory.json) | completed | 0/10、0/10、10/10 |
| [planning_B](planning_B/trajectory.json) | error；下一请求发送前超输入上限 | 0/10、0/10、0/10 |
| [planning_C](planning_C/trajectory.json) | not_started_after_stop | 无模型候选 |
| [symbolic_A](symbolic_A/trajectory.json) | not_started_after_stop | 无模型候选 |
| [symbolic_B](symbolic_B/trajectory.json) | not_started_after_stop | 无模型候选 |
| [symbolic_C](symbolic_C/trajectory.json) | completed | train NMSE 0.09694021、0.09591726、0.09576767 |

每个目录包含候选 `.py`、`trajectory.json` 和 `diagnostics.json`。trajectory 去掉重复的 incumbent 源码和重复诊断；候选源码单独保存，诊断原文件保持不变。`rationale` 是模型自述，可能错误，不是已经证实的研究结论。A 的诊断由评价器计算并存档，但没有提供给 A 模型。

[manifest.json](manifest.json) 记录每个快照和原始候选／诊断文件哈希。[完整说明](../../../docs/operations/diagnostic-comparison.md)解释设计、停止原因和证据限制；[轨迹分析](../../../docs/analysis/2026-10-20-diagnostic-comparison-analysis.md)核对具体自述。

[reconstruction_script.py](reconstruction_script.py) 是本次离线 SDK 重建脚本的原样审阅快照，使用服务器已有运行记录，屏蔽网络和评价器。它仅重建消息体，不申请模型请求；另一次实际 BudgetLedger 输入门槛检查的结果见核验 JSON。不是新实验入口。
