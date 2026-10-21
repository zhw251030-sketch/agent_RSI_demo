# 基函数接口使用与校准状态

本轮已完成接口和人工数据校准。优先读[结果与解释](../analysis/2026-10-22-basis-contract-results.md)，代码入口是[extensions/symbolic_basis_v01](../../extensions/symbolic_basis_v01/README.md)。完整未来策略调度器尚未接通；不得由工具层校准直接宣称真实 RSI 运行就绪。

模型仅提交 feature_ids/explanation；宿主固定 spec、数据角色、父结构和操作模式。swap_one 允许保留或恰好一删一加；add_one 必须恰好新增一项。host-only 的 evaluate_role 保留旧数据门禁，本轮未在真实数据上调用。

数值/接口测试使用系统 Python 与原 `.task-runtime/python`；SDK 测试使用原 `.venv`。不混装依赖：

```bash
PYTHONPATH=.task-runtime/python /usr/bin/python3 -m unittest extensions.symbolic_basis_v01.test_contract extensions.symbolic_basis_v01.test_executor extensions.symbolic_basis_v01.test_calibrate
.venv/bin/python -m unittest extensions.symbolic_basis_v01.test_sdk_adapter
.venv/bin/python -m unittest extensions.symbolic_basis_v01.test_archive
.venv/bin/python -m extensions.symbolic_basis_v01.calibrate verify --directory artifacts/symbolic-basis/2026-10-22/calibration-v01
```

最后两项只核对归档、重新计算人工分数及篡改测试，不执行候选/拟合。既有 calibration-v01 运行目录已完成，不重复调用 run 或恢复。52份上一轮真实数值诊断材料、当前99份人工校准材料分别保留。

后续先实现新接口在现有策略流程中的完整消息/调用绑定，再做假 provider 全流程。新模型实验的父状态、任务K、共同提示、选择规则、位置顺序和预算仍须冻结。模型权重、旧实验依赖及封存数据范围均不因本接口改变。

下一单元目标为完成上述必要接线后直接执行最多13请求的S0/S1开发对照（1提案＋2起点×2策略×3重复），不是再仅交付模拟准备包。13请求尚未分配/启动；发生接口、预算或基础设施异常应保留记录并停止，不恢复旧轮。
