# 补充C：经验、记忆与技能更新机制

日期：2026-10-15。本文件是已完成检索的证据补充；基础LLM权重固定，当前只研究设计，未安装依赖、运行代码或调用模型做实验。优先理解改进如何发生，再考虑同一机制在多类任务中的适用性。

## 1. 机制判断

这组文献主要研究“经验 → 更新记忆、规则或技能 → 改变后续行为”。建议按 **ExpeL → CER → ReasoningBank → ACE** 阅读机制，结合AWM观察错误经验怎样影响行动，以Voyager理解可执行技能复用。A-Mem主要提供记忆组织与检索证据，不能将其会话问答提升直接解释为行动策略改进。

需要区分两种目标：一是用固定更新程序改善Agent；二是让Agent改善更新程序本身。下列方法通常仍固定提炼提示、筛选规则、检索算法和更新调度。它们能改变经验内容与后续行为，尚不足以据此声称已经验证递归改进算法。若研究第二种目标，需要明确哪些更新器组件会被修改，并评价修改后的更新器能否从新经验流中形成更有效的改进。

## 2. 八项方法的证据比较

| 方法与正式身份 | 更新对象、反馈和切分 | 实验证据及限制 |
| --- | --- | --- |
| **ExpeL，AAAI 2024技术主会** | 成功轨迹库与自然语言insights；比较同题成败轨迹、归纳多题成功模式；可新增、编辑、赞同、否定。训练任务收集经验并离线提炼，测试通常一次尝试；经验跨任务保留。 | HotpotQA、ALFWorld、WebShop。HotpotQA→FEVER迁移共用Wikipedia Docstore，并用目标fewshot改写源insights；不是任意跨域迁移。§5.6中加入反思文本的提炼变体反而较差，说明反思不是天然可靠的训练材料。 |
| **CER，ACL 2025主会长文** | 全称Contextual Experience Replay；分别提炼环境知识与操作技能，再按任务检索。offline、online、hybrid明确区分；offline主设置用人工设计且排除测试重叠的任务和gold轨迹；online可从成败轨迹积累，无须真值奖励。 | WebArena、VisualWebArena。Forum的cross-template SR是“至少成功一题的模板比例”，不是严格留出新模板。stability为93%，表明总体提升与局部退化并存。真值筛成功轨迹优于混合轨迹，但此对照不单独证明所有失败经验有害。 |
| **ReasoningBank，ICLR 2026** | LLM自判轨迹成败，按不同提示提炼标题、描述和策略内容；embedding检索，追加记忆。从空库处理任务流，无测试真值反馈。MaTTS通过同题多轨迹对照或顺序修订丰富学习材料。 | WebArena、Mind2Web、SWE-bench Verified支持同机制在不同任务族运行，不等于网页经验迁移到代码修复。正式版§5的judge噪声实验：Shopping上准确率72.7%；随机翻转真值标签时，70%—90%区间表现相近、100%最好。随机标签噪声不等于经验适用范围的语义错误。 |
| **ACE，ICLR 2026** | Generator执行，Reflector诊断，Curator生成局部增量；经验条目有ID及有益/有害计数，并去重。offline在训练集优化；online先预测再更新，共用同一打乱顺序，可离线预热。 | AppWorld、FiNER、Formula分别评估，未据此证明一份经验库跨域迁移。整库重写造成上下文急剧压缩和表现下降的案例，支持检查信息丢失；局部条目更新已是成熟近邻，不能单独作为新贡献。 |
| **AWM，ICML 2025** | 从判定成功的经验归纳带变量的子工作流，包含状态、推理、动作；offline用标注轨迹，online用LM评价器筛选测试流经验。原文明确按website分组分别运行。 | WebArena、Mind2Web；online跨域成绩包含目标域内适应。原文讨论误判成功导致错误工作流、照搬不适合当前状态的动作。v1 Table 4中cross-domain完整任务SR：offline 0.7、MindAct 1.0、online 1.7；步骤指标改善不能替代完整任务改善。 |
| **Voyager，TMLR 2024** | 自动课程提出目标，生成并执行代码，结合环境状态、执行错误及LLM自验证修复；成功程序进入持久技能库，后续可检索和组合。 | Minecraft新世界清空物品后测试未见目标，并把技能库供AutoGPT使用。支持同环境体系内技能复用，未证明跨任务领域的通用更新。TMLR身份已核实，不能误标为ICLR 2024主会。 |
| **Dynamic Cheatsheet，EACL 2026主会长文** | 冻结LLM在测试时维护策略、代码和解题提示；根据自身输入输出整理，不依赖真值反馈；有累积整理、检索整理等变体。 | AIME、Game of 24、GPQA、MMLU-Pro等；主要为各任务内复用。部分收益来自发现并复用求解代码。§4.6讨论相似性与顺序，§5及附录D.2讨论错误启发式传播；checklist承认未对所有配置做多次运行。 |
| **A-Mem，NeurIPS 2025主会** | 将交互内容组织成笔记、语义属性和链接，新记忆可改写旧笔记的上下文、关键词与标签；持久检索供后续问答使用。 | LoCoMo、DialSim会话问答，主要检查事实、多跳和时间信息。部分GPT设置的单跳、不可回答问题仍弱于其他基线。没有行动成败反馈驱动的策略学习实验，不能把memory evolution直接认作RSI。 |

## 3. 原文、读取范围与版本限制

| 方法 | 正式来源与全文 | 本轮实际读取范围 |
| --- | --- | --- |
| ExpeL | [AAAI元数据](https://ojs.aaai.org/index.php/AAAI/article/view/29936)；[正式全文](https://ojs.aaai.org/index.php/AAAI/article/download/29936/31635) | 正式全文§4—§6；重点§4.2经验提炼、§5.4迁移、§5.6消融。 |
| CER | [ACL元数据](https://aclanthology.org/2025.acl-long.694/)；[正式PDF](https://aclanthology.org/2025.acl-long.694.pdf)；[arXiv v1](https://arxiv.org/html/2506.06698v1) | 核实ACL主会身份；深入阅读v1 §3—§7，并定位正式PDF首页。未逐项比较两版全部内容。 |
| ReasoningBank | [ICLR正式元数据](https://proceedings.iclr.cc/paper_files/paper/2026/hash/980ea04d23d1f6908964eba2a74afe45-Abstract-Conference.html)；[正式全文](https://proceedings.iclr.cc/paper_files/paper/2026/file/980ea04d23d1f6908964eba2a74afe45-Paper-Conference.pdf)；[arXiv v1](https://arxiv.org/html/2509.25140v1) | 先读v1方法、实验与相关附录，再核对正式版方法、§5 judge噪声实验、Appendix A及E相关段落。正式版新增证据优先于v1。 |
| ACE | [ICLR正式元数据](https://proceedings.iclr.cc/paper_files/paper/2026/hash/8a94ff6f922d995d7d3f4ebf4143e442-Abstract-Conference.html)；[正式全文](https://proceedings.iclr.cc/paper_files/paper/2026/file/8a94ff6f922d995d7d3f4ebf4143e442-Paper-Conference.pdf)；[arXiv v1](https://arxiv.org/html/2510.04618v1) | 深读v1 §2—§4；读取正式版对应方法、实验切分及相关讨论。未完成所有附录的逐段审计。 |
| AWM | [ICML正式元数据](https://proceedings.mlr.press/v267/wang25bx.html)；[正式PDF入口](https://raw.githubusercontent.com/mlresearch/v267/main/assets/wang25bx/wang25bx.pdf)；[arXiv v1](https://arxiv.org/html/2409.07429v1) | 深读v1 §2—§5及附录相关内容。正式PDF接口返回不支持的content-type，因此机制和具体数值明确来自v1，未伪装成正式版逐项核对。 |
| Voyager | [作者实验室出版页](https://research.nvidia.com/labs/gear/publications/)；[原文v2](https://arxiv.org/html/2305.16291)；[TMLR OpenReview入口](https://openreview.net/forum?id=ehfRiF0R3a) | 读v2 §2—§3、未见任务Table 2及相关附录。TMLR 2024身份由作者实验室出版页核实；OpenReview遇浏览器验证，未核对TMLR全文所有改动。 |
| Dynamic Cheatsheet | [EACL正式元数据](https://aclanthology.org/2026.eacl-long.333/)；[正式全文](https://aclanthology.org/2026.eacl-long.333.pdf) | 正式版方法、实验设置、§4.6、§5、附录D.2与checklist。 |
| A-Mem | [NeurIPS正式元数据](https://proceedings.neurips.cc/paper_files/paper/2025/hash/19909c36f51abc4856b4560aff3d36d6-Abstract-Conference.html)；[arXiv v11](https://arxiv.org/html/2502.12110v11) | 深读v11 §3—§6、Tables 1—3；主会身份由NeurIPS正式论文集核实。 |

上述范围是局部证据定位，不代表逐篇完成全部补充材料、代码和独立复现审计。未在所读章节发现某项实验，不能推出整个领域不存在相关研究。

## 4. 优先研究的可观察链

以下为综合后的研究设计建议，不是已完成实验或已证明的新颖性。

1. **材料到经验。** 固定原始轨迹，比较直接提炼、同题成败对照、加入反思。记录产生了什么建议、依据是什么、是否遗漏适用条件；不能仅凭文字合理就认为经验正确。
2. **经验到行动。** 在固定任务状态下加入或移除同一条经验，观察是否改变工具选择、验证步骤、搜索或修订动作。结果需由真实任务反馈检查，避免只依赖同一LLM自述经验有用。
3. **行动到结果。** 区分减少无效动作、复用具体答案、额外计算和可迁移策略带来的收益。必要时固定预算、轨迹及反馈，检查经验模块的独立作用。
4. **新证据到修订。** 观察错误经验被保留、覆盖、降权或撤销的过程；同时检查旧任务退化。局部更新、条件化经验和噪声干预已有近邻，需具体到失败现象及控制条件确定新增。

CER与ReasoningBank对失败经验的不同结果，提供了有价值的问题，而非直接矛盾：失败轨迹含有可用信息，不代表任意提炼方式都能生成可靠建议。候选研究应定位是标签、归因、表述、检索还是执行环节使经验有效或有害。

当前不建议同时建设多层记忆图、长期多角色、自动课程、复杂检索、可执行技能库和元更新器。先用简单且可审计的更新基线，与不更新、冻结经验、同预算重试比较。跨任务族验证放在机制明确以后。

## 5. 代码及执行边界

论文或作者项目指向的入口：[ExpeL](https://github.com/LeapLabTHU/ExpeL)、[ACE](https://github.com/ace-agent/ace)、[ReasoningBank](https://github.com/google-research/reasoning-bank)、[AWM](https://github.com/zorazrw/agent-workflow-memory)、[Voyager项目](https://voyager.minedojo.org/)、[Dynamic Cheatsheet](https://github.com/suzgunmirac/dynamic-cheatsheet)、[A-Mem评测代码](https://github.com/WujiangXu/AgenticMemory)。

CER本轮未定位作者明确提供的代码入口；不据此断言其未开源。本轮未安装或运行上述代码，未验证可复现性、当前依赖可用性或模型成本；论文报告的结果不是本项目结果。

## 6. 检索记录与覆盖边界

检索日期2026-10-15；工具为web搜索、来源网页/PDF读取，另用PowerShell只读获取ICLR 2026论文集页面以定位ACE与ReasoningBank的正式链接。未加发表时间过滤；结果排序、总命中数和未展示的分页范围未知。以下保留重要的精确query；省略重复的来源定位尝试，不声称系统综述或穷尽覆盖。

```text
ExpeL LLM Agents Are Experiential Learners AAAI 2024 paper
"ExpeL: LLM Agents Are Experiential Learners" site:ojs.aaai.org
CER cumulative experience refinement agents conference paper
"Contextual Experience Replay for Self-Improvement of Language Agents"
"Contextual Experience Replay" site:aclanthology.org
"Contextual Experience Replay" "github.com" Yitao Liu
Agentic Context Engineering ACE ICLR 2026 paper
"Agentic Context Engineering" site:iclr.cc
"Agentic Context Engineering" site:openreview.net/forum
"Agentic Context Engineering" github ace-agent ace
A-MEM Agentic Memory LLM Agents NeurIPS 2025 paper
"A-Mem: Agentic Memory for LLM Agents" site:proceedings.neurips.cc
"Agent Workflow Memory" EMNLP 2024 site:aclanthology.org
"Agent Workflow Memory" site:proceedings.mlr.press/v267
"ReasoningBank" "ICLR" 2026
"ReasoningBank: Scaling Agent Self-Evolving" site:openreview.net/forum
"Voyager" "ICLR 2024" paper lifelong agent
"Voyager: An Open-Ended Embodied Agent with Large Language Models" TMLR
"Dynamic Cheatsheet" paper ICLR 2026
"Dynamic Cheatsheet" site:aclanthology.org/2026.eacl-long.333/
"In-context Principle Learning from Mistakes" ICML 2024
```

检索中的初始venue或缩写猜测仅为检索线索，最终已纠正：CER为Contextual Experience Replay；AWM为ICML 2025；Voyager为TMLR 2024；Dynamic Cheatsheet为EACL 2026。LEAP（In-Context Principle Learning from Mistakes）已找到[ICML 2024正式入口](https://proceedings.mlr.press/v235/zhang24at.html)，本补充未将其计入八篇深入比较，也未基于摘要作额外机制结论。
