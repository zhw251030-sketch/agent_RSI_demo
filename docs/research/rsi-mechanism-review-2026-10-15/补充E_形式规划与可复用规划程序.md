# 补充 E：形式规划与可复用规划程序

日期：2026-10-15。性质：定向检索、原文阅读与官方代码静态核查；未安装环境、未运行生成器或求解器、未调用实验模型，未复现任何论文结果。以下方案尚未冻结，不代表已选定博士课题。

## 1. 结论与两套配对

如果重点是理解固定权重系统如何根据不完全反馈改善做法，优先采用 **llm-genplan＋明确的 PDDL 任务族**：更新一个能处理新实例的 Python 规划程序，观察有限失败反馈带来的修复与退化。若更关心算法效率和较整齐的公开划分，则采用 **IPC 2023 Learning Track＋LLM 生成启发式函数**，固定状态转移与搜索算法，只更新搜索指导函数。

两条路线都比“对单题多搜索几次”更直接地保留可复用产物。多种 PDDL 域属于规划领域内部的多域证据，不自动等于跨数学、逻辑和程序任务族的通用性；模型不训练也不自动意味着更新器自身发生递归改进。

## 2. 主方案：llm-genplan 与三个具体域

Silver 等的 *Generalized Planning in PDDL Domains with Pretrained Large Language Models* 正式发表于 AAAI 2024。固定 LLM 从域描述和少量任务生成 `get_plan(objects, init, goal)`，再根据执行异常、计划语法、计划语义和超时反馈修订程序；最终冻结程序，求解独立任务。[正式正文](https://ojs.aaai.org/index.php/AAAI/article/download/30006/31766)；[可读全文](https://arxiv.org/html/2305.11014)，定位：Background and Problem Setting、Automated Interactive Debugging、Experimental Setup。

首轮推荐 **Spanner、Miconic、Ferry**。选择理由是：它们有清楚的状态、先决条件和顺序约束，原实现已配套训练/测试文件，可先研究修订作用，避免先搭新环境。不是声称三个域已出现稳定失效或足够新颖。

| 论文域／官方实现标识 | 输入规则及目标 | 对修订机制的观察价值 | 论文对象规模：训练→测试 |
|---|---|---|---|
| Spanner／`pg3-spannerlearning` | 单向走廊上收集扳手，用一次性扳手拧紧螺母 | 漏收集资源、不可回退移动；局部错误可能来自更早的决策 | 9–15→30–60 |
| Miconic／`pg3-manymiconic` | 多栋楼各有电梯，按乘客起点和目标楼层接送 | 对象分类、分组与循环是否能推广；修补一个乘客是否破坏其他情况 | 6–30→11–150 |
| Ferry／`pg3-manyferry` | 用一次最多载一辆车的渡轮，将车送到目标岛屿 | 可达性、位置跟踪、装卸顺序与重复操作 | 13–20→30–50 |

官方 [run_all.sh](https://github.com/tomsilver/llm-genplan/blob/master/scripts/run_all.sh) 明确给这三域设置每个种子 2 个提示实例、8 个额外训练实例、30 个测试实例，种子 0–9。官方 [envs/__init__.py](https://github.com/tomsilver/llm-genplan/blob/master/llm_genplan/envs/__init__.py) 的 `_get_pg3_tasks` 从 `assets/pddl/pg3/<domain>/seed<seed>` 与 `<domain>_test/seed<seed>` 分开读取。第一轮应保留这些原划分，不把全体文件重新随机混洗。

后续扩展生成器的正式入口为 [AI-Planning/pddl-generators](https://github.com/AI-Planning/pddl-generators)，其目录包含 spanner、miconic、ferry，部分用于历届 IPC。**同名生成器不保证等于 llm-genplan 使用的 PG3 变体**：新增实例前必须核对域文件、对象分布和可解性。当前已读数据加载与运行脚本，未逐一核定这三个通用生成器与原变体完全兼容；因此原始文件可用于复现设计，新增生成数据仍是下一步静态核对事项。Heavy 和 Forest 可作后续扩展，但本轮没有核实它们可直接使用的独立生成器入口。

任务输入是域动作规则、对象集合、初始状态和目标；输出是动作序列。计划只需逐步满足先决条件且最终达到目标，不要求等于某条参考序列。有效性与长度分开计分；程序异常、超时、首个非法动作和未满足目标分别记录。通过有限实例不证明程序在整个任务族上正确。

## 3. 第一个实验：先看一次修改到底改好了什么

以下是拟议协议，不是现有结果。问题收敛为：**相同父程序收到相同失败实例后，错误诊断能否帮助它修复一类错误，同时保留已成功的能力？收益能否超过多抽一个程序再筛选？**

1. **建立父程序集合。** 用原始生成流程获得程序及训练轨迹，保留失败、部分成功和成功程序；先按错误种类及能力水平分层。初步可以利用官方缓存了解现象，但缓存结果不能替代新模型的重复实验。
2. **共同起点做单步更新。** 每个父程序复制到各组：不更新；原版执行反馈直接修订；同反馈先诊断再修订；同调用预算独立重采样。先只产生一个候选，直接评价修改，避免选择环节掩盖坏修改。
3. **问题实例隔离。** 提示/修改实例与评价实例分开。若另做多候选选择，需再有独立选择集。原始 30 个测试实例不反馈给更新器；审计结果不能再用于挑选最终赢家。若反复依据测试结果改研究方案，应另留最终封存集，而非继续称原集为未见测试。
4. **程序层次隔离。** 方法开发用一部分父程序；最终机制评价用未参与调规则的父程序与新生成种子。来自同一生成运行的多个修订是相关样本；独立单位以完整生成/更新运行为主，不能将所有任务调用算成独立重复。
5. **测量与决策。** 报告独立实例覆盖率变化、原成功实例损失率、修复迁移率、候选退化率和总代价。计划长度只在有效计划上比较，并同时报告未解比例。单步现象稳定后，才恢复连续更新，检查收益是否累积。

必要方法对照为原版 llm-genplan、无调试、等预算重采样选择；再加入下节的策略层修订近邻。传统求解器如 Fast Downward、FF 等用于校准任务可解性、难度和计划质量。它们不是“弱模型基线”；若只研究更新可靠性，论文主张也不必变成全面战胜成熟规划器。

反馈条件需要进一步区分“真实执行错误”与“对错误原因的解释”。验证器可以确定某一步违反了前提，却通常不能直接确定应该修改哪段策略；后者仍是待检验的诊断。第一实验不必人为随机翻转真假标签，更有解释力的条件是：只给首个非法动作、给其缺失前提、再给完整执行轨迹，检查信息增加是否改变修改位置及泛化效果。每组拿到的例子、允许的候选数和累计执行预算应对齐；额外调用验证器的收益不能全算成更聪明的更新。

可预先规定退出判断：若三个域的首个程序已经稳定解决所有独立实例，则这些域只保留为校准，不围绕饱和结果堆叠记忆模块；若失败主要是格式解析或依赖安装，先修基础设施，不当作推理机制；若独立重采样已消除差异，研究问题应转向何时修订值得使用；只有当特定错误在多个父程序和独立运行中重复出现，且现有修订方法仍有不足，才提出针对性新机制。跨域扩展同时区分“同一算法分别学习”和“一个域所得程序直接迁移”，二者证据不能互相替代。

## 4. 第二方案：IPC 2023 与启发式程序

IPC 2023 学习赛道原协议就是离线获得域知识，再把冻结知识交给求解器处理未见实例。知识可以是程序、策略、启发式或宏动作。[官方规则](https://ipc2023-learning.github.io/)；[任务仓库](https://github.com/ipc2023-learning/benchmarks)。

Corrêa、Pereira、Seipp 的 *Classical Planning with LLM-Generated Heuristics: Challenging the State of the Art with Python Code* 为 **NeurIPS 2025**。它固定 Pyperplan/GBFS，由 LLM 产生域专用 Python 启发式，并在训练任务上选择；正式实验使用 IPC 2023 的 8 域，每域 90 个测试实例，测试通常更大。Ferry、Satellite 因实现支持问题排除。[会议录](https://proceedings.neurips.cc/paper_files/paper/2025/hash/3bf4b55960aaa23553cd2a6bdc6e1b57-Abstract-Conference.html)；[原文](https://arxiv.org/html/2503.18809)，定位 §3、§4；[官方实现](https://github.com/abcorrea/llm-generated-heuristics)。

可先取 Blocksworld、Spanner、Floortile，分别检查基本接口、顺序资源约束和较复杂搜索。只开放 `h(state)`，真实规则和搜索器固定，测覆盖率、展开状态数、时间与更新退化。**原方法是相同提示独立采样 25 个候选再选择，没有反馈往返修订。** 它应是强采样选择对照，不能描述成已有反思循环。其搜索保证来自固定正确的搜索实现与转移规则，不来自启发式代码被证明正确；异常和过慢仍会影响求解。

## 5. 直接近邻与方法边界

| 新近邻 | 本轮核实的内容 | 对项目的约束 |
|---|---|---|
| Stein 等，*Improved Generalized Planning…Strategy Refinement and Reflection*，ICAPS 2026 | 17 域；先调试伪代码，再生成、反思修订、选择 Python 程序；每域 6 个小调试任务；最终程序用 4 种对象/事实排列评测 | 归因、伪代码修订、多候选已存在。原文明确：计划错误未必源于策略错误，也可能是 LLM 没正确执行策略 |
| GenePlan，ICAPS 2026 | 固定模型进化 Python 规划器种群，代码与运行反馈回流；8 域，各 5–10 个训练、30 个测试任务；优化计划长度 | 最接近程序持续改进。原文另报告 Sokoban 失败；SAT score 是相对计划成本分数，不是正确率 |
| AutoToS，ICAPS 2026 | 从单元测试反馈修订后继函数与目标函数，再由 BFS/DFS 解新实例；含 24 Game、BlocksWorld、PrOntoQA、填字、Sokoban | 证明框架可用于多个任务族；有限测试不保证整体正确。Sokoban 仅 11 个容易实例，PrOntoQA 最终以真假标签核验 |

正式身份由 [ICAPS 2026 日程 Session 7A](https://icaps26.icaps-conference.org/program/schedule/) 核对。正文与定位：[Stein 方法、实验、附录数据节](https://arxiv.org/html/2508.13876)；[GenePlan §4–5 与附录算法](https://arxiv.org/html/2603.09481)；[AutoToS §4–7](https://arxiv.org/html/2408.11326)。本轮未找到可核实的 GenePlan 官方实现仓库，不能据论文附录称源码已公开。

[RAP，EMNLP 2023](https://aclanthology.org/2023.emnlp-main.507/) 的 Blocksworld/GSM8K/PrOntoQA 展示题内 MCTS 搜索，不是跨题持久策略学习。[LLM-Modulo，ICML 2024 position paper](https://proceedings.mlr.press/v235/kambhampati24a.html) 是外部验证器与 LLM 双向交互框架，不自动提供长期更新算法。两者可作执行/反馈设计参照，不能直接顶替当前更新机制。

## 6. 实现、任务选择与证据边界

llm-genplan README 写 Python 3.11+、在 MacOS 测试；pyproject 写 ≥3.8，需部署时校准。依赖作者 PDDLGym fork、pathos 等，有历史聊天缓存。IPC 启发式代码要求 Python ≥3.10、uv，含 Pyperplan 和公开 split。Stein [仓库 README](https://github.com/coli-saar/genplan-strategy-refine) 写 Python 3.10/Linux、VAL、Fast Downward、CUDA/sglang，并称完整数据暂需联系作者；不能承诺全部数据开箱即用。AutoToS [官方代码](https://github.com/IBM/AutoToS) 使用 LiteLLM Proxy 风格接口，规划验证还需 VAL。当前均未验证 Windows 运行。

PlanBench 是 [NeurIPS 2023 Datasets & Benchmarks](https://proceedings.nips.cc/paper_files/paper/2023/hash/7a92bcdede88c7afd108072faf5485c8-Abstract-Datasets_and_Benchmarks.html)，覆盖生成、验证、重规划等能力，有 IPC 来源生成器；它不是统一的标准学习划分。其小 Blocksworld 静态集已有高分，不能单独支撑研究。[官方 README](https://raw.githubusercontent.com/karthikv792/LLMs-Planning/main/plan-bench/README.md) 还涉及 Linux、VAL、Fast Downward、PR2Plan，较老接口需适配。

选择判断：PDDL 程序是算法构造的受控子问题，规则与失败点易定位，适合先研究更新机制；一般算法发现能提供更丰富目标，但需不同评价器；ARC 涉及未知规律归纳，会同时引入表示和规则识别难点。此比较是研究设计判断，本轮没有对 ARC 方法做全面审查。

主要限制：网页部分目录无法读取；GitHub 递归树 API 受限流，改读公开 HTML 和 raw 文件完成关键加载/运行脚本核查；未完成全部代码审计与版本冻结。正式发表不等于独立复现。没有证明目标失败现象、方法收益或新颖空缺。

## 7. 阅读范围与检索留痕

已定位阅读：Silver 的任务定义、调试、实验及官方任务加载/运行脚本；NeurIPS 启发式 §3–4 及 README/依赖；Stein 方法、实验、数据附录和 README；GenePlan §4–5、附录 Planner/PlannerDB 算法；AutoToS §4–7；RAP §3–4；PlanBench 元数据与生成器 README。其余来源以正式身份、摘要或官方说明核查为限。

检索日期 2026-10-15；Web search，未设日期过滤，默认排序，无可控分页及总量记录。以下保留改变判断的原样查询；并非完整系统综述：

```text
"Generalized Planning in PDDL Domains" official github
"Improved Generalized Planning" "Strategy Refinement"
site:ojs.aaai.org "Improved Generalized Planning with LLMs"
"Classical Planning with LLM-Generated Heuristics" AAAI 2026 github
site:proceedings.neurips.cc "Classical Planning with LLM-Generated Heuristics"
"Automating Thought of Search" site:github.com/IBM
"Automating Thought of Search" "ICAPS 2026"
"GenePlan: Evolving Better Generalized PDDL Plans" github
"GenePlan" "github.com" planning
"GenePlan" "code" "Murray"
"Self-Improvement for Fast, High-Quality Plan Generation" weights
"Successor-Generator Planning with LLM-generated Heuristics" github
"ipc2023" "learning" "training" "testing" github
"PDDL Generators" github AI-Planning
"Reasoning with Language Model is Planning with World Model" EMNLP 2023
"Position: LLMs Can’t Plan" proceedings.mlr.press
```
