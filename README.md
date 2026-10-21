# agent_RSI_demo

固定基础 LLM 权重，研究 Agent 如何利用执行反馈更新修订策略，并在**形式规划与符号发现**两个环境中检验同一更新机制。

**已修复SDK元数据接口并完成后继真实尝试；第7请求暴露默认finish工具冲突，当前停止。** 2026-10-21完成SDK可选元数据接收/schema修复，实现729318e；同一256运行文件的189项不同测试服务器全通过、本机172通过17跳过。实际SDK假provider模拟36位置/716人工测量通过。独立真实measured-v02运行7请求、6接受、1失败、29未开始；四次策略提案形成三种不同策略，两份新规划终稿唯一配对均0/19。四选择起点基线与两终稿合计60测量、62sandbox、19VAL、2符号拟合；第七响应同时含submit_candidate/finish，被总调用数守卫拒绝，符号终稿未接受/执行。无S*选择、后续评价、封存/probe/权重更新；四评价起点仍未执行。真实410原文件、模拟3644原文件逐字节归档，双端审计/分析一致，旧档未改。当前需单步工具表后继修复，旧readiness只认证当时模拟；实际SDK离线双调用回放仅作诊断、不追认旧轮。126553tokens、估算0.3210249元、预留1.4715582元；累计134研究请求、已知1079042tokens、估算3.2916156元、预留14.7462378元，两笔旧usage未知保留。尚无稳定机制优势或独立泛化。 见[本轮说明](docs/operations/strategy-measured-v02.md)、[结果与解释](docs/analysis/2026-10-21-strategy-measured-v02-results.md)、[核验](docs/environment/2026-10-21-strategy-measured-v02-verification.json)。

网页入口：完成本机 SSH 转发后打开 **http://127.0.0.1:18080/**。MiniMax-M3 已配置并通过两套 SDK 的工具往返检查。启动、访问和停止方式见 [网页使用说明](docs/operations/canvas.md)，实际结果见 [部署验收](docs/environment/2026-10-20-canvas-deployment.md)。

## 当前选择

| 层次 | 当前状态 |
|---|---|
| 研究路线 | 已选择形式规划与符号发现一起推进；基础 LLM 权重固定 |
| 规划任务 | Spanner 400题已下载；官方训练去重后学习10/选择19/后续评价63，排除8副本；300官方测试继续封存 |
| 符号任务 | LLM-SR四方程12CSV；学习oscillator1、选择oscillator2（有手写评分暴露）、后续评价bactgrow/stressstrain；8测试CSV封存 |
| 更新对象 | 外部策略S；最新接受四次提案、三种内容，尚未完成S*选择，无策略效果结论 |
| 方法参照 | 借鉴ExpeL的经验/规则分离与GEPA的反馈驱动外部提示更新；当前有限规则选择不是两篇论文的完整复现 |
| Agent 框架 | OpenHands SDK/tools 1.55.1、MiniMax-M3；元数据修复与36位置模拟通过，真实7请求后因默认finish/单调用契约不一致停止 |
| 任务执行层 | 四选择起点与两规划终稿共60测量；唯一规划配对均0/19；两个S*冻结前评价门关闭，四评价起点仍未执行 |
| 交互网页 | Agent Canvas 1.28.1 已部署，工作区已选中；独立后端 SDK 1.56.0，MiniMax-M3 配置已启用 |

模型配置与验收：[MiniMax-M3 使用说明](docs/operations/minimax.md)。连接检查与开发小试分开计数。小试 8 次请求含 1 次服务错误，7 次有响应；费用仍有一笔未知用量，详见 [真实小试说明](docs/operations/agent-pilot.md)。

## 阅读入口

- [最新真实轮结果与接口诊断](docs/analysis/2026-10-21-strategy-measured-v02-results.md)：元数据修复、四策略提案、实际配对成绩、第七请求停止与费用。
- [此前首请求停止](docs/analysis/2026-10-21-strategy-measured-v01-results.md)：原始SDK元数据拒绝问题，历史记录不变。
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
