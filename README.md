# agent_RSI_demo

固定基础 LLM 权重，研究 Agent 如何利用执行反馈更新修订策略，并在**形式规划与符号发现**两个环境中检验同一更新机制。

**已完成两阶段真实Agent开发对照：10次模型请求、6个新候选。** 规划有效配对两臂均8/8开发+2/2公开；两个符号checked分支避免self的删项退化，但存在“测试干预被当成最终编辑”的混淆，未证明稳定方法优势。一个登记结构拒绝、两条分支未启动，原样保留。见[最新完整说明](docs/operations/two-stage.md)、[结果与边界](docs/analysis/2026-10-21-two-stage-results.md)、[157份原始记录](artifacts/two-stage/2026-10-21/v01/README.md)。实跑前701项不同服务器测试通过。

网页入口：完成本机 SSH 转发后打开 **http://127.0.0.1:18080/**。MiniMax-M3 已配置并通过两套 SDK 的工具往返检查。启动、访问和停止方式见 [网页使用说明](docs/operations/canvas.md)，实际结果见 [部署验收](docs/environment/2026-10-20-canvas-deployment.md)。

## 当前选择

| 层次 | 当前状态 |
|---|---|
| 研究路线 | 已选择形式规划与符号发现一起推进；基础 LLM 权重固定 |
| 规划任务 | Spanner 的 400 问题与域文件已下载到服务器，完整性检查和固定 prompt 的 VAL 验收通过；seed0 的2提示/8开发已运行，30封存题未评分 |
| 符号任务 | 按用户要求替换受限数据，已下载 LLM-SR 原论文四任务的 12 个 CSV（89,341 行），先用 oscillator1/2；结构检查通过，oscillator1/train已开发运行，独立评价协议待冻结 |
| 更新对象 | 已分开产物P与持久策略S；当前S为人工八规则中四规则的有序选择，已完成首次更新；最新两初稿各做self/checked复查并冻结，四状态后续评价完成 |
| 方法参照 | 借鉴ExpeL的经验/规则分离与GEPA的反馈驱动外部提示更新；当前有限规则选择不是两篇论文的完整复现 |
| Agent 框架 | OpenHands SDK/tools 1.55.1、MiniMax-M3；受控策略与候选工具已运行，最新实跑前701项不同服务器测试通过 |
| 任务执行层 | 规划解析/VAL 与符号拟合/评分已接通；Bubblewrap/seccomp 限制候选文件、网络、进程和资源；当前只开放开发反馈 |
| 交互网页 | Agent Canvas 1.28.1 已部署，工作区已选中；独立后端 SDK 1.56.0，MiniMax-M3 配置已启用 |

模型配置与验收：[MiniMax-M3 使用说明](docs/operations/minimax.md)。连接检查与开发小试分开计数。小试 8 次请求含 1 次服务错误，7 次有响应；费用仍有一笔未知用量，详见 [真实小试说明](docs/operations/agent-pilot.md)。

## 阅读入口

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

26. [最新：可执行干预校准与编辑验证](docs/operations/intervention-probes.md) · [结果分析](docs/analysis/2026-10-21-intervention-results.md) · [核验](docs/environment/2026-10-21-intervention-verification.json)

## 仓库边界

研究资料保留日期、来源链接与证据限制；较早稿件中的任务排序以当前联合设计和后续明确决定为准。新研究稿、实现、配置模板及经过检查的实验摘要在本仓库继续维护。论文全文、第三方源码镜像、受限数据、模型、虚拟环境、凭据和原始运行目录不直接纳入 Git。

当前包含文献比较、设计、安装证据、离线检查脚本和任务清单草案。安装环境、拿到数据、运行基线与验证新机制分别记录，不互相替代。
