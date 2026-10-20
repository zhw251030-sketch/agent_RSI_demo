# 任务收益接受规则与状态划分实施计划

**目标：** 完成可运行的目标/命题/收益判定、策略接受接口、24份历史终稿全量回放和新任务角色清单。

**设计依据：** [冻结协议](../protocols/2026-10-21-goal-alignment-v0.1.md)。用户已授权继续上一轮建议的下一步和持续同步；本轮无需新增模型调用。

**实现结构：** 新增独立模块，保持全部历史运行模块和档案字节不变。纯函数接受器不导入模型、SDK、候选执行器；回放器绑定旧归档；任务划分工具只核对清单及文件完整性。

- [x] `rsi_eval/goal_alignment.py` 与 `tests/test_goal_alignment.py`：先失败测试；明确命题极性、精度/简化目标、逐任务保持、策略配对约束。
- [x] `configs/tasks/strategy-partition-v0.1.json`、`rsi_eval/strategy_partition.py`、`scripts/check_strategy_partition.py` 与对应测试：按官方训练清单去重分配角色，保留暴露史和所有封存限制。
- [x] `configs/analysis/goal-alignment-v0.1.json`、`scripts/analyze_goal_alignment.py` 与对应测试：先绑定全部历史输入，再回放24终稿和四状态的probe；不新增执行。
- [x] 相关测试、独立审查及有意义篡改检查；提交实现后同步服务器，执行一次双端离线复算与任务清单核验。
- [x] 保存中文操作/逐例解释、机器报告、验收与状态；提交推送，核对三处HEAD、干净工作树和原档哈希。

执行由当前会话协调子任务。组件完成后才进入依赖它的回放；不并行修改同一文件，不改写旧结论，不把接口模拟测试记成真实S学习。
