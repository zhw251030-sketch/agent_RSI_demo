# 补充 B：程序、工作流与改进器演化

核查日期：2026-10-15。范围：基础 LLM 权重固定的程序／工作流优化及改进器自修改。本文是选题比较材料，不是系统综述、独立复现或已确定的创新结论。本轮仅检索和阅读，未安装环境、未调用实验模型、未运行仓库代码。

**当前研究顺序：先深入研究一个改进机制，定位可重复的问题并做受控干预，再尝试用于多类任务。** 更新器递归修改自身可作为后续扩展，不是第一阶段的必要条件。

## 1. 必须分开的证据

| 证据层次 | 实际检验的问题 | 不能自动推出的结论 |
| --- | --- | --- |
| 同一机制在多任务上分别优化 | 一套搜索／更新算法能否接入不同任务 | 已学经验或更新器发生跨域迁移 |
| 已优化 Agent 直接迁移 | 在任务 A 搜出的成品能否用于任务 B | 改进器自身变得更好 |
| 已优化改进器迁移 | 在 A 获得的更新器能否更有效地改进 B 的 Agent | 无界、自加速或适用于任意任务的 RSI |

“自修改”“多轮分数上升”“代码空间图灵完备”分别是实现属性、有限实验现象和表示能力，均不能单独证明通用递归自我改进。

## 2. 七种方法比较

以下每行将机制、评价条件和局限合并，避免把多个版本或重复基准计作独立证据。定位及链接见下一节。

| 方法 | 改什么、谁修改谁 | 评价与迁移边界 | 对当前研究的意义 |
| --- | --- | --- | --- |
| **ADAS / Meta Agent Search** | 固定 meta-agent 根据 Agent 档案和成绩编写新 `forward`；可改提示、组合、控制流，搜索算法自身固定。 | ARC、DROP、MGSM、MMLU、GPQA 分别搜索；MGSM 前 3 个成品另迁移到数学及非数学任务、不同执行模型。搜索用 validation，另设 test；GPQA 32／166，其他主要推理域 128／800。 | 轻量、清楚的代码搜索参照，便于研究档案怎样影响修改；有成品迁移证据，不能称作已学更新器迁移。 |
| **AFlow** | 固定 MCTS 变体选择父工作流；LLM 改提示与代码连接；把父子修改、成败反馈存回树。模型、温度、输出格式固定，提供预置 Operator。 | HumanEval、MBPP、GSM8K、MATH、HotpotQA、DROP 分别优化；20% validation、80% test，前者再筛高方差问题；每候选评估 5 次。未定位到成品跨域迁移实验。 | **优先机制入口**：选择、提议、执行反馈、经验记录可分别干预。父节点经验和失败记录已是已有机制，不能仅组合后声称创新。 |
| **STOP** | 改进器 `I(u,s,L)` 用效用函数改程序；下游程序收益构成 meta-utility，再由旧改进器改自己的代码。 | LPN 优化效用使用 20 个实例，另用 50 个独立实例测试；5 次独立运行。选一个较好改进器，直接用于字符串、二次分配、3-SAT、MaxCut、无噪声 parity，未再自优化。 | 改进器作为研究对象最清楚的参照；迁移证据规模小。强模型下改善、较弱模型下可退化，且单步更好的改进器未必更善于改自己。 |
| **Gödel Agent** | 通过运行时读写／monkey patching，同时修改任务策略和决定如何自改的逻辑。 | 四个推理基准各自优化，另有 Game of 24；每域 6 个周期、每周期最多 30 步，然后 test。未定位到改进器跨域迁移。100 次 MGSM 优化中，14% 最终低于初始策略。 | 能研究修改失效与恢复，但自由度大、归因较难。固定模型比较须采用 Gödel-base；Gödel-free 会请求更强模型。基线表来自 ADAS，不能当作完全独立重跑。 |
| **Darwin Gödel Machine（DGM）** | 编码 Agent 改自己的工具、提示和工作流；档案保留分支。改进指令生成与外层种群搜索固定。 | SWE-bench／Polyglot 搜索采用阶段性子集评价，主搜索曲线不是完全独立测试；两基准互换迁移有未见基准证据，另有跨语言／模型实验。 | 证明了编码系统层面的自改与成品迁移，不能据此断言非编码领域的更新能力。仓库测试、容器及候选评估较重，适合作后续对照。 |
| **HyperAgents / DGM-H** | task-agent 与 meta-agent 合入可编辑程序；修改任务逻辑及未来修改逻辑。主实验仍固定父代选择及外部评价。 | 论文录用预测、机器人奖励设计所得 meta-agent，固定后用于优化数学评分 Agent，直接测改进器迁移；`imp@50=0.630`。论文／数学评分各 train／validation／test 为 100／100／100。 | 长期 RSI 的重要近邻。初始零分部分来自格式不合规；对人工定制 DGM、以及继续优化时迁移初始化的优势并非都显著。应借鉴测量，避免把有限收益写成通用或加速 RSI。 |
| **AgentSquare** | 固定模块演化＋重组，搜索规划、推理、工具、记忆四类标准接口；重组候选用上下文性能预测器筛选。 | WebShop、ALFWorld、ScienceWorld、M3ToolEval、TravelPlanner、PDDL 分别搜索。已读方法及实验部分未定位到更新器跨域迁移，也未明确定位搜索／最终测试分割。 | 适合研究“改哪里、如何重组”，较全代码自改容易限制变量；模块化、重组、代理评价已有先例。分割细节需进一步核代码，当前不能据此断言泄漏。 |

## 3. 发表状态、一手来源与全文定位

发表状态与方法证据分开核实。下列七篇均达到相关主张的 **FULLTEXT_LOCATED**：已读取并定位与本比较相关的正文／附录，不表示通读所有代码、核验全部统计或独立复现。

| 方法 | 发表状态及负责来源 | 原文与定位 | 读取限制 |
| --- | --- | --- | --- |
| ADAS | **ICLR 2025 主会**；另有 NeurIPS 2024 Workshop 版本／奖项，不能混为主会。[正式论文](https://proceedings.iclr.cc/paper_files/paper/2025/file/36b7acf6f6010652b3f2a433774a66fe-Paper-Conference.pdf) | [arXiv v2](https://arxiv.org/html/2408.08435v2)：§3 搜索；§4.3、附录 A 迁移；附录 E 分割。 | 主要结论对照原文，未逐一重查每个生成 Agent。 |
| AFlow | **ICLR 2025 主会**；官方实现标注 Oral。[会议记录](https://proceedings.iclr.cc/paper_files/paper/2025/hash/5492ecbce4439401798dcd2c90be94cd-Abstract-Conference.html) | [全文](https://arxiv.org/html/2410.10762)：§3 搜索空间；§4 算法及分割；§5 设置和结果。 | 未将六域分别搜索写作跨域迁移；没有对算子逐一审计。 |
| STOP | **COLM 2024 主会 Spotlight**，不是 ICLR 2024。[COLM 官方名单](https://colmweb.org/2024/AcceptedPapers.html) | [论文 PDF](https://arxiv.org/pdf/2310.02304)：算法 1、§3–4 接口；§5.1–5.3 独立实例、迁移和模型差异；附录 M 代码来源。 | 迁移使用选定的较好改进器，不能当作所有独立运行都稳定迁移。 |
| Gödel Agent | **ACL 2025 主会长文**。[ACL 正式记录](https://aclanthology.org/2025.acl-long.1354/) | [正式 PDF](https://aclanthology.org/2025.acl-long.1354.pdf)：§3–4 自改；§5.2–5.3 设置／受约束版本；§6.2 退化；附录 B 分割。 | 不采用无约束版本的分数支持固定模型结论；未验证每次修改的归因。 |
| DGM | **ICLR 2026 主会 Poster**；[OpenReview 正式条目](https://openreview.net/forum?id=pUpzQZTvGY)，[作者发表记录](https://www.jennyzhangzt.com/)。 | [全文](https://arxiv.org/html/2505.22954)：§3 可修改边界；§4.2 阶段评价；§4 迁移分析／图 4；附录 E 任务清单。 | OpenReview 直接打开遇验证页；状态由官方索引检索与作者主页交叉核实。未重新计算任务重叠。 |
| HyperAgents | **2026 arXiv 预印本**；未核到正式主会录用。[arXiv 记录](https://arxiv.org/abs/2603.19461)；官方仓库仍给出 `misc` 引用。 | [全文 v1](https://arxiv.org/html/2603.19461v1)：§3–4 机制；§5.1–5.3 结果与显著性；表 2／附录 C 分割；附录 D.3–D.4 指标与转移 Agent 选择。 | 网页正文显示日期与摘要页版本日期不一致，本稿不据此宣称有新的正式版本；未独立核代码／日志的对应版本。 |
| AgentSquare | **ICLR 2025 主会**。[会议记录](https://proceedings.iclr.cc/paper_files/paper/2025/hash/0ae94013da7cd459402fd77874e09ee3-Abstract-Conference.html) | [正式 PDF](https://proceedings.iclr.cc/paper_files/paper/2025/file/0ae94013da7cd459402fd77874e09ee3-Paper-Conference.pdf)：§2 接口；§3 更新算法；§4.1、附录 A.1 实验。 | 只报告“本轮未定位到”明确分割，未用文本搜索失败证明该设置不存在。 |

HyperAgents 另有两项需保留的评价边界：机器人实验是一个训练目标与一个不同测试目标各重复六次，不是十二种任务；Polyglot 表 2 列 60 训练、165 测试，但正文也使用“full benchmark、largely unseen”措辞，精确复现前应核任务清单，不能把全部报告分数直接认作纯未见测试。

## 4. 官方代码入口与适配边界

以下仅核入口、README 和论文接口，没有安装、执行或复现验证。仓库可访问不意味着代码与论文版本完全一致。

| 官方仓库 | 可复用接口／实施条件 |
| --- | --- |
| [ADAS](https://github.com/ShengranHu/ADAS) | `forward(task)` 与 `evaluate_forward_fn()`；新域仍需改任务描述、输出格式及评价。README 使用 Python 3.11。 |
| [AFlow](https://github.com/FoundationAgents/AFlow) | Workflow、Operator、Evaluator；接入任务输入及数值反馈。官方提醒部分从 MetaGPT 迁移的 Operator 可能有 bug。 |
| [STOP](https://github.com/microsoft/stop) | 初始程序、效用函数及描述、冻结 LLM；嵌套执行及效用调用需要预算限制。README 未提供完整的一键复现流程。 |
| [Gödel Agent](https://github.com/Arvid-pku/Godel_Agent) | 初始 solver、反馈接口及运行时修改工具。仓库后续访问超时；论文实现已读，完整部署步骤未核。 |
| [DGM](https://github.com/jennyzzt/dgm) | Agent 代码仓库、测试与历史日志；官方流程使用 Docker 及 SWE-bench／Polyglot 环境。 |
| [HyperAgents](https://github.com/facebookresearch/HyperAgents) | meta-agent 接仓库位置、历史评价位置和剩余预算；task-agent 接领域输入。Python 3.12、Docker；机器人任务另需模拟器和 RL，基础 LLM 本身仍冻结。 |
| [AgentSquare](https://github.com/tsinghua-fib-lab/AgentSquare) | 四种模块标准 I/O 及任务评价器；Python 3.9.12，各环境仍分别配置。 |

## 5. 机制优先的候选研究问题

这些是基于比较得到的**候选实验问题**，不是已证明的新颖性或已观察到的失败。应先挑一个可重放的窄任务，再决定机制改变；暂不固定最终基准。

1. **更新器怎样选择和压缩历史反馈？** 以 ADAS／AFlow 为参照，固定可编辑空间、候选数和调用预算，比较完整档案、父节点相关经验、轨迹摘要等输入。研究目标应是解释一种重复失败，例如错误总结怎样引导无效修改，而非泛泛宣称“加入经验更好”。
2. **带噪声评价怎样影响修改的接受与回退？** 固定提议器或候选集合，检查重评估、选择和回退如何改变错误接受及后续退化。先判断评价噪声是否是实际瓶颈，再设计方法；不能仅凭存在验证集就认定过拟合。
3. **任务成绩和改进能力怎样分开测？** 借鉴 STOP 的 meta-utility、HyperAgents 的 `imp@k`，在正常工作的初始 Agent 上测固定预算产生的改进。后续再冻结机制、换任务检验适用性。`imp@k` 在这里是测试性能增益，不是成功概率。

初期宜从 AFlow／ADAS 中选择一个受控骨架，另一项作最近对照；STOP 用来明确“好的改进器”的评价对象。DGM、Gödel Agent 和 HyperAgents 帮助划清后续递归扩展的边界。首版无需同时实现七套系统。

## 6. 检索记录与覆盖限制

来源：Web Search 发现候选；会议、ACL Anthology、arXiv、作者主页和官方 GitHub 核查。检索日期均为 2026-10-15；无发表日期过滤；只有查询显式包含 `site:` 时限制域名。工具未提供可靠总命中数和可审计分页记录，以下记录用于追踪发现路径，不支持穷尽性主张。

关键精确查询（含用于纠正状态或扩展边界的查询）：

```text
"Automated Design of Agentic Systems" ICLR 2025
"AFlow" "Automating Agentic Workflow Generation" ICLR 2025
"Darwin Gödel Machine" publication 2026 ICLR
"Self-Taught Optimizer" ICLR 2024 STOP
"Automated Design of Agentic Systems" site:openreview.net
"AFlow" site:openreview.net "ICLR 2025"
"Self-Taught Optimizer" site:openreview.net
"Gödel Agent" ICLR 2025 ACL 2025
"AFlow: Automating Agentic Workflow Generation" "ICLR" poster
"Darwin Gödel Machine" site:iclr.cc/virtual/2026
"Hyperagents" conference ICLR ICML NeurIPS 2026
"Darwin Gödel Machine" "ICLR 2026" site:openreview.net/forum
"Darwin Gödel Machine" site:proceedings.iclr.cc
"Self-Taught Optimizer" site:proceedings.iclr.cc
"Hyperagents" "accepted"
"Self-Taught Optimizer" conference COLM ICLR 2024
"HyperAgents" "Zhang" site:openreview.net
"Darwin Gödel Machine" "ICLR 2026 Poster"
"AgentSquare" conference ICLR 2025
"A Self-Improving Coding Agent" conference 2026
"HyperAgents" "2603.19461" conference
"Hyperagents" "August 24, 2026"
"Hyperagents" "0.630"
"Darwin Gödel Machine" "pUpzQZTvGY" site:openreview.net
"Hyperagents" site:jennyzhangzt.com
```

SICA（A Self-Improving Coding Agent）仅完成边界发现，未纳入这七篇的正文比较；相关检索结果存在 Workshop 与后续载体表述，本文不据此给出未经核实的正式发表结论。没有用二手综述、搜索摘要或 GitHub 星数代替原文方法证据。
