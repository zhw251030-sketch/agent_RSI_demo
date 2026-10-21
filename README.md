# agent_RSI_demo

固定基础 LLM 权重，研究 Agent 如何利用执行反馈更新修订策略，并在**形式规划与符号发现**两个环境中检验同一更新机制。

**最新真实轮首请求后停止，已定位SDK字段接收契约缺陷；当前版本需要修复。** 2026-10-21在cf8804bb（冻结实现15144dc0）启动真实measured-v01，首个请求6.436899秒返回后因SDK可选字段与业务契约不一致停止：实际schema公布summary/security_risk，响应包含它们，接收器拒绝；原始规则R01/R02/R05/R08未被接受。1真实请求、0接受策略、0任务/拟合/sandbox/VAL/封存/S与权重更新，后35位置未启动，v02八来源仍未执行。26,027tokens、既有费率估算0.056679元、预留0.2763096元；累计127请求、已知952489tokens、估算2.9705907元、预留13.2746796元，旧两笔未知保留。33原文件逐字节归档，双端停止审计record_consistent_incomplete及只读核验一致；254运行文件、旧236文件/693原档与3653文件模拟档未改。此前模拟只覆盖省略SDK可选字段的回复，旧readiness保留历史含义，当前运行版本需修复后才能另开真实轮。 见[本轮说明](docs/operations/strategy-measured-v01.md)、[停止原因与结果](docs/analysis/2026-10-21-strategy-measured-v01-results.md)、[核验](docs/environment/2026-10-21-strategy-measured-v01-verification.json)。

网页入口：完成本机 SSH 转发后打开 **http://127.0.0.1:18080/**。MiniMax-M3 已配置并通过两套 SDK 的工具往返检查。启动、访问和停止方式见 [网页使用说明](docs/operations/canvas.md)，实际结果见 [部署验收](docs/environment/2026-10-20-canvas-deployment.md)。

## 当前选择

| 层次 | 当前状态 |
|---|---|
| 研究路线 | 已选择形式规划与符号发现一起推进；基础 LLM 权重固定 |
| 规划任务 | Spanner 400题已下载；官方训练去重后学习10/选择19/后续评价63，排除8副本；300官方测试继续封存 |
| 符号任务 | LLM-SR四方程12CSV；学习oscillator1、选择oscillator2（有手写评分暴露）、后续评价bactgrow/stressstrain；8测试CSV封存 |
| 更新对象 | 外部策略S历史已有一次更新；最新实现任务收益与配对策略接受接口，最新真实轮1请求、0接受策略，仍无新的S学习/选择 |
| 方法参照 | 借鉴ExpeL的经验/规则分离与GEPA的反馈驱动外部提示更新；当前有限规则选择不是两篇论文的完整复现 |
| Agent 框架 | OpenHands SDK/tools 1.55.1、MiniMax-M3；旧36位置模拟通过；真实首请求暴露SDK字段契约缺陷，需后继修复与重验 |
| 任务执行层 | 新角色执行器复用隔离/VAL/拟合；学习与选择按角色限制，评价需两个S*冻结凭证；人工校准通过，尚未执行新真实任务 |
| 交互网页 | Agent Canvas 1.28.1 已部署，工作区已选中；独立后端 SDK 1.56.0，MiniMax-M3 配置已启用 |

模型配置与验收：[MiniMax-M3 使用说明](docs/operations/minimax.md)。连接检查与开发小试分开计数。小试 8 次请求含 1 次服务错误，7 次有响应；费用仍有一笔未知用量，详见 [真实小试说明](docs/operations/agent-pilot.md)。

## 阅读入口

- [最新真实轮停止结果](docs/analysis/2026-10-21-strategy-measured-v01-results.md)：真实1请求、接口拒绝原因、费用、离线复现和后继修复范围。
- [策略调度与完整模拟验收](docs/operations/strategy-pair.md)：实际SDK、阶段顺序、预算、原始记录与真实运行命令。
- [此前策略实验接口](docs/operations/strategy-interface.md)：历史学习包、任务角色、实测绑定、验收与SDK调度器边界。
- [最新完整新批次](docs/operations/state-generation-v02.md)：8份来源、180秒传输证据、结果与后续接口。
- [此前冷启动来源生成](docs/operations/state-generation.md)：第一批中止记录与原始生成协议。
- [此前任务收益规则与任务划分](docs/operations/goal-alignment.md)：接受器、全量回放、任务角色与边界。

1. [项目状态与下一步](STATUS.md)
2. [形式规划与符号发现联合设计](docs/research/planning-symbolic-design-2026-10-17/形式规划与符号发现_联合研究设计_v0.1.md)
3. [研究资料及导入来源](docs/research/README.md)
4. [OpenHands 安装与检查结果](docs/environment/2026-10-20-setup-and-verification.md)
5. [两类任务的共用研究契约](docs/protocols/2026-10-20-shared-contract.md)
6. [GitHub 与服务器同步约定](docs/operations/git-sync.md)
7. [两类任务下载、替代选型与验收说明](docs/operations/task-data.md)
8. [当前符号数据接口：LLM-SR 公开原始任务](docs/protocols/2026-10-20-symbolic-public-data.md)
9. [任务执行器、隔离与 OpenHands 工具使用说明](docs/operations/task-executors.md)
10. [首轮真实 Agent 小试：操作、结果与限制](docs/operations/agent-pilot.md)
11. [首轮全部候选源码与开发成绩](artifacts/pilot/2026-10-20/README.md)
12. [上一轮诊断对照：操作、部分结果与下一步](docs/operations/diagnostic-comparison.md)
13. [诊断对照全部候选与反馈](artifacts/diagnostic-comparison/2026-10-20/README.md)
14. [观测、理由与代码逐条核对](docs/analysis/2026-10-20-diagnostic-comparison-analysis.md)
15. [上一轮：可执行检查的实现、真实结果与下一步](docs/operations/checked-feedback.md)
16. [检查轮逐项证据与解释审查](docs/analysis/2026-10-20-checked-feedback-v02-analysis.md)
17. [v0.1停止轮完整归档](artifacts/checked-feedback/2026-10-20/v01-stopped/README.md) · [v0.2修复轮完整归档](artifacts/checked-feedback/2026-10-20/v02/README.md)

18. [上一轮：固定同一起点的单步修订与结果](docs/operations/paired-repair.md)
19. [配对轮源码、声明与解释分析](docs/analysis/2026-10-20-paired-repair-analysis.md) · [全部证据](artifacts/paired-repair/2026-10-20/v01/README.md)
20. [上一轮：策略更新、三条件结果与操作说明](docs/operations/policy-transfer.md)
21. [本轮为什么这样设计](docs/analysis/2026-10-20-policy-method-rationale.md) · [结果与更新理由核查](docs/analysis/2026-10-20-policy-transfer-analysis.md) · [全部证据](artifacts/policy-transfer/2026-10-20/v01/README.md)

22. [上一轮：策略前提检查、停止原因与下一步](docs/operations/grounded-policy.md)
23. [事实与推断逐条审查](docs/analysis/2026-10-20-grounded-policy-analysis.md) · [完整停止轮](artifacts/grounded-policy/2026-10-20/v01-stopped/README.md)

24. [上一轮：推断证据检查的完整对照与结果](docs/operations/inference-policy.md)
25. [固定命题、解释与机制边界](docs/analysis/2026-10-20-inference-policy-analysis.md) · [8候选逐条审查](docs/analysis/2026-10-20-inference-candidate-analysis.md) · [机器审计](docs/analysis/2026-10-20-inference-policy-audit.json)

26. [此前：可执行干预校准与编辑验证](docs/operations/intervention-probes.md) · [结果分析](docs/analysis/2026-10-21-intervention-results.md) · [核验](docs/environment/2026-10-21-intervention-verification.json)

27. [两阶段登记—检查—修订及混淆分析](docs/operations/two-stage.md)
28. [此前：冻结证据回放决策](docs/operations/decision-replay.md) · [结果](docs/analysis/2026-10-21-decision-replay-results.md) · [核验](docs/environment/2026-10-21-decision-replay-verification.json)

29. [此前：编辑声明一致性检查](docs/operations/edit-consistency.md) · [原文标注](configs/analysis/edit-consistency-v0.1.json) · [机器报告](docs/analysis/2026-10-21-edit-consistency-report.json)

## 仓库边界

研究资料保留日期、来源链接与证据限制；较早稿件中的任务排序以当前联合设计和后续明确决定为准。新研究稿、实现、配置模板及经过检查的实验摘要在本仓库继续维护。论文全文、第三方源码镜像、受限数据、模型、虚拟环境、凭据和原始运行目录不直接纳入 Git。

当前包含文献比较、设计、安装证据、离线检查脚本和任务清单草案。安装环境、拿到数据、运行基线与验证新机制分别记录，不互相替代。
