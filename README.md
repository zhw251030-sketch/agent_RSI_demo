# agent_RSI_demo

**2026-10-24 进展：已完成基函数策略 v02 的编辑级离线诊断、编辑证据契约、basis actor 宿主接线、targeted check 校准和三条件门控协议。** 读取同一 A 父结构的 6 个真实槽位，核对父/子结构、源码、反馈和 NMSE 绑定；5 次实际结构修改全部退化，6 个槽位的编辑前反馈均没有支持具体替换的证据。新协议改用 `oscillator2/train` 的三输入基函数开发状态，固定3个父结构、6个候选、18条配对门控记录；服务器 OpenHands SDK 假 provider 预演6/6接受且每槽一次请求，相关证据/compact/协议测试服务器79项通过。尚未启动新的真实模型或候选评分；下一步是完成 shadow outcome 接线后再进行真实三条件小试。

**最新：v02完整真实对照已完成，发现较好起点仍被反复改坏。** 2026-10-22完成基函数策略v02：实现ed96ac9a、冻结6eba8793，171运行文件；两个工具只接ID，可选说明仅归档，旧编译器宿主转换显式绑定。完整SDK模拟13/14通过，44项新测试服务器全过、本机32过12SDK跳过。独立真实13/13接受（1新S1提案R01/R02/R05/R08+12终稿）、无重试；14fit+14predict/28sandbox，220拟合公式调用、28人工启动warmup另计。A父NMSE0.00452983：S0三退化，S1一保持两退化；B父0.09588372：两臂均三改善，最佳均0.00452983；12终稿仅5种结构，不能据均值称稳定优势。两父各6份SDK共同输入一致，服务器14保存预测分数重算通过，本机绑定核验通过、双端汇总逐字节相同。模拟422/真实421原文件归档，旧运行与档案未改。新增58406tokens、估算0.1288014元、预留1.5012354元；累计184请求、已知1448729tokens、估算4.4065266元、预留21.3231102元，旧两笔usage未知保留。无策略晋升、权重更新或封存访问。 见[结果与解释](docs/analysis/2026-10-22-basis-trial-v02-results.md)、[操作说明](docs/operations/basis-trial-v02.md)、[验收](docs/environment/2026-10-22-basis-trial-v02-verification.json)。

**历史：完整SDK预演通过，v01真实小对照首请求停止。** 2026-10-22完成基函数策略13位置完整SDK接线与冻结预演（13接受/14人工测量，含10keep和2swap，165运行文件，最大88898字节）。实现7eeb4c0、执行冻结d76a952；真实measured-v01首请求正常8.926秒返回，合法R01/R05/R04/R08因explanation4223字符超过2000被整体拒绝，0接受、无S1冻结、其余12未启动；真实CSV/fit/sandbox/S与权重更新/封存访问均0。42项运行前及3项事后不同测试服务器45全过，本机36过9SDK跳过；实际SDK同请求/原参数假provider回放复现拒绝。模拟398/真实18/回放13原文件逐字节归档，旧258运行文件/3665v03档/52数值档/99校准档未改。新增26154tokens，估算0.0608706元、预留0.2727018元；累计171请求、已知1390323tokens、估算4.2777252元、预留19.8218748元，旧2笔usage未知。解释存在旧结果误读；本轮没有新机制效果。 见[结果与解释](docs/analysis/2026-10-22-basis-trial-results.md)、[操作说明](docs/operations/basis-trial.md)、[验收](docs/environment/2026-10-22-basis-trial-verification.json)。

**上一轮：基函数接口与人工校准。** 2026-10-22完成符号基函数/直接系数接口：完整三阶内单项式字典1–4输入共4/10/20/35项，严格feature_ids/explanation、宿主K≤16、规范排序、同K保留/单换项及单增项独立约束；沿用原隔离/拟合器。OpenHands实际schema/Action/Executor假宿主回调通过，未做完整Conversation/provider预演。10人工fit+12predict/22sandbox全部按预期，9例可评分、常数目标NMSE不可用，共线初值已精确，K16人工例通过；194拟合公式调用，22warmup另计。67项新测试服务器全过，本机64过3SDK跳过；双端人工分数回放一致，99文件146046字节归档，旧258运行文件/3665v03档案/52数值档案不变。真实CSV/任务fit/模型/S/权重/封存更新均0，累计170研究请求和旧费用不变。接口校准不证明RSI有效。 见[结果与解释](docs/analysis/2026-10-22-basis-contract-results.md)、[操作说明](docs/operations/symbolic-basis.md)、[验收](docs/environment/2026-10-22-basis-contract-verification.json)。

**上一轮：八条件符号数值诊断。** 2026-10-22完成8条件真实符号数值诊断，8/8成功，每条件一次：stress同族7→4参数NMSE仅差4.51e-12，fit候选调用106→17（优化器内部105→16）；bact四种等14项平方表示均优于三次14项，NMSE为0.728202/0.728076/0.772260/0.799326，完整15项0.728058。新增8fit+8predict/16sandbox，人工校准5fit尝试+2predict/7sandbox另计，23次启动warmup另计。36项新测试及15项旧审计测试双端通过；服务器从保存预测重算8个分数一致，52原文件逐字节归档，258旧运行文件/3665旧档案不变。模型/策略/权重更新及封存访问均0，累计仍170请求、已知1364169tokens/估算4.2168546元/预留19.5491730元，两笔usage未知。仅支持已见train上的参数化/特征诊断，不证明稳定RSI优势。 见[结果与解释](docs/analysis/2026-10-22-symbolic-numerical-diagnostic.md)、[操作说明](docs/operations/symbolic-diagnostic.md)、[验收](docs/environment/2026-10-22-symbolic-diagnostic-verification.json)。

**上一轮：全量离线机制审查。** 2026-10-22完成v03全量离线机制审查：32终稿/16配对，完整请求及传输设置分组；四后续状态各有3次相同S0输入，新策略各1次。32个事后窄编辑谓词25支持/4矛盾/3未知；16符号终稿7保持公式/9改变表示，4个数值正向配对均增参数；stress原7参数仅4个有效系数。15项新离线测试两端全过，分析核验逐字节一致；235引用文件、3665档案文件与258旧运行文件核对通过。新增模型/执行/拟合/封存/S/权重更新均0，累计170请求和旧费用不变。已写8次无LLM数值诊断设计；168请求选择器方案仅草案，execution_ready=false。 见[机制审查](docs/analysis/2026-10-22-strategy-mechanism-audit.md)、[后继设计](docs/experiments/2026-10-22-mechanism-next-design.md)、[核验](docs/environment/2026-10-22-strategy-mechanism-verification.json)。

固定基础 LLM 权重，研究 Agent 如何利用执行反馈更新修订策略，并在**形式规划与符号发现**两个环境中检验同一更新机制。

**已完整执行真实策略学习—选择—后续评价；观察到有限正向配对，尚无稳定优势结论。** 2026-10-21启动、22完成measured-v03，实现0065d8c：单步Agent仅公布业务提交工具，199项不同相关测试服务器全过，本机175过24跳过；同一258文件实际SDK假provider预检36/716通过。真实36请求全部接受、无重试，四提案三种内容、32份终稿、716测量（696规划/20符号）、734 sandbox调用、356 VAL、20拟合尝试。r1选择unknown保留S0，r2凭oscillator2训练收益晋升R02/R01/R05/R08；两S*在后续起点的基线、反馈与评分开始前冻结。r2后续P-eval1固定0/63、新策略63/63；P-eval2均0/63；bactgrow NMSE0.8448014490→0.7280577515、14→15参数；stressstrain均0.3436165736/7参数。r1两臂同S0，P-eval2仍0/63与63/63，不算更新收益。16对完整共同请求一致；真实3642原文件、模拟3644原文件逐字节归档，双端审计/分析一致passed_complete/passed，旧档与运行文件不变。285127tokens、估算0.9252390元、预留4.8029352元；累计170研究请求、已知1364169tokens、估算4.2168546元、预留19.5491730元，两笔旧usage未知保留。0封存/probe/权重更新。首次完整后续评价仅支持本次2项正向配对，不证明稳定机制优势或普适性。终态后滞留SSH客户端已单独清理，服务器实验进程此前已退出；CLI退出码未知，原档不变。 见[本轮说明](docs/operations/strategy-measured-v03.md)、[结果与解释](docs/analysis/2026-10-21-strategy-measured-v03-results.md)、[核验](docs/environment/2026-10-21-strategy-measured-v03-verification.json)。

网页入口：完成本机 SSH 转发后打开 **http://127.0.0.1:18080/**。MiniMax-M3 已配置并通过两套 SDK 的工具往返检查。启动、访问和停止方式见 [网页使用说明](docs/operations/canvas.md)，实际结果见 [部署验收](docs/environment/2026-10-20-canvas-deployment.md)。

## 当前选择

| 层次 | 当前状态 |
|---|---|
| 研究路线 | 已选择形式规划与符号发现一起推进；基础 LLM 权重固定 |
| 规划任务 | Spanner 400题已下载；官方训练去重后学习10/选择19/后续评价63，排除8副本；300官方测试继续封存 |
| 符号任务 | LLM-SR四方程12CSV；学习oscillator1、选择oscillator2（有手写评分暴露）、后续评价bactgrow/stressstrain；8测试CSV封存 |
| 更新对象 | 外部四规则有序策略S；四提案三种内容，r1保留S0、r2晋升；后续仅观察到有限正向配对 |
| 方法参照 | 借鉴ExpeL的经验/规则分离与GEPA的反馈驱动外部提示更新；当前有限规则选择不是两篇论文的完整复现 |
| Agent 框架 | OpenHands SDK/tools 1.55.1、MiniMax-M3；单步仅业务工具；measured-v03全部36真实请求接受 |
| 任务执行层 | 八起点与32终稿共716测量；两S*先冻结再开放四评价状态；r2两项收益两项持平，封存集未评分 |
| 交互网页 | Agent Canvas 1.28.1 已部署，工作区已选中；独立后端 SDK 1.56.0，MiniMax-M3 配置已启用 |

模型配置与验收：[MiniMax-M3 使用说明](docs/operations/minimax.md)。连接检查与开发小试分开计数。小试 8 次请求含 1 次服务错误，7 次有响应；费用仍有一笔未知用量，详见 [真实小试说明](docs/operations/agent-pilot.md)。

## 阅读入口

- [最新策略学习—选择—后续评价结果](docs/analysis/2026-10-21-strategy-measured-v03-results.md)：真实配对结果、同策略重复差异、源码核查、费用与限制。
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
