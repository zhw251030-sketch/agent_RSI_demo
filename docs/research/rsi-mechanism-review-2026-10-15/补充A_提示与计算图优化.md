# 补充 A：提示与计算图优化方法

日期：2026-10-15。性质：机制导向的文献核查与候选研究建议；不包含实现、模型调用或独立复现实验。

## 1. 本轮判断

当前目标是先深入研究 Agent 改进及其机制，再检验机制能否用于多类任务；基础 LLM 权重固定。按更新对象清晰、过程可审计、便于干预归因的标准，优先深入 **GEPA 与 Promptbreeder**：前者适合拆解反馈、修改提案和搜索选择，后者直接涉及产生修改的 mutation prompt 是否能变好。TextGrad、MIPRO 和 Trace 是不能省略的近邻。

本文件区分三类证据：同一算法在不同领域分别优化；优化产物直接迁移到另一数据集或模型；学到的更新器在新问题上改进其他策略。三者不互相替代，也不把跨任务迁移预设为第一阶段必选目标。

## 2. 八种方法比较

| 方法与正式发表 | 更新对象、反馈与机制 | 实验与复用证据 | 更新器边界、实施要求及用途 |
| --- | --- | --- | --- |
| **GEPA，ICLR 2026 主会** | 多模块提示；利用执行轨迹、分数和环境评价文本反思修改，以样本层面的 Pareto 候选选择保留多样性，可合并模块 | AIME-2025、LiveBench-Math、HotpotQA、IFBench、HoVer、PUPA；主要各基准重优化；另有同任务跨模型提示迁移 | 原论文固定反思 meta-prompt 与搜索框架。需提示接口、数据划分、度量和轨迹；官方代码公开。适合拆分研究反馈、提案、选择和验收 |
| **Promptbreeder，ICML 2024 主会** | 成对演化 task prompts 与 mutation prompt，可带成功推理示例；用任务正确率、固定操作族和锦标赛选择 | 数学推理、常识推理、ETHOS、instruction induction；各域分别演化，另换模型重新演化 | 更新 mutation prompt，超变异提示与流程拓扑固定。原实验使用较多群体评估；未定位原实验完整官方仓库，有极简实现。适合研究更新规则文本自修改 |
| **TextGrad，Nature 2025 正式期刊** | 计算图中的提示、代码、答案等文本变量；沿图生成变量级文本批评，再由 TGD 修改 | 提示实验含 GSM8K、BBH Object Counting/Word Sorting；另有代码、科学问答、分子和治疗方案实例优化；同一框架分别应用 | 默认不学习 TGD 或反馈规则。需计算图与损失；官方代码公开。适合研究反馈归因；语言梯度是类比，不具备数值梯度的自动保证 |
| **MIPRO，EMNLP 2024 主会；MIPROv2 为后续 DSPy 实现** | 模块指令与示例组合；成功轨迹自举、程序/数据条件化提案、TPE 贝叶斯搜索，主要使用任务级分数 | HotpotQA及条件版、Iris及拼写变体、Heart Disease、ScoNe、HoVer；七组任务分别优化 | 主算法不自改更新器；MIPRO++另优化提案超参数，结果并非全面占优。需程序、评分器和例子；实现公开。适合作为无文本错误反思的强对照 |
| **OPRO，ICLR 2024 主会** | 指令；依据历史指令及分数、少量例子生成新候选 | GSM8K、23项BBH；确有 GSM8K 指令直接用于 MultiArith/AQuA，限数学推理域；另演示线性回归和TSP | 历史变化，优化器 meta-prompt 固定；论文链接官方代码。接口简单，适合作为分数历史驱动的基线 |
| **ProTeGi，EMNLP 2023 主会** | 提示；错误样本形成文本批评，再改写，配 beam search 与 bandit 筛选 | ETHOS、LIAR、Arabic Sarcasm、作者构建的 jailbreak detection；逐任务优化，本轮未定位跨域提示迁移实验 | 更新规则固定；需标签、API及候选评估，官方工件公开。原文已报告优化数步后可能过拟合，以及批评未被正确使用的例子 |
| **EvoPrompt，ICLR 2024 主会** | 离散提示群体；LLM执行进化操作，以开发集分数选择 | 正式摘要报告31数据集，覆盖理解、生成和BBH；本轮未深读迁移设计 | 不能由“进化”推断更新器也被优化；官方代码公开。可作为一般群体搜索近邻，精细机制结论需继续核查正文 |
| **Trace / OptoPrime，NeurIPS 2024 主会** | 提示、函数代码和数值参数；记录相关计算子图，以轨迹和反馈构成伪代码问题，由固定LM提出变化 | BBH、UXSim交通控制、LLF-Bench/Meta-World机器人、数值计算图等；相同优化器分别优化，机器人另测新初始状态 | 默认不自改优化器；需追踪包装与较长图日志，官方实现公开。遮蔽轨迹和移除历史的干预尤其值得参考 |

DSPy 是编程及优化框架，不能当作一个单独优化器；其 ICLR 2024 论文、MIPRO论文与当前 MIPROv2 实现也不能视为完全相同的实验对象。跨论文模型、反馈和预算不同，本文件不以裸分数给方法排名。

## 3. 两项关键机制证据

**GEPA 已经检验过候选选择的作用。** 正文表3保持演化框架固定，比较 Pareto、贪心最佳候选和 beam search。因此，加入多样性或不只修改当前最佳提示已有直接近邻。研究时应分别观察反馈提供了什么信息、如何生成修改、选哪个父候选继续探索、怎样验收；最终收益不能全部归为反思能力。正式全文的§3、§4表3及附录C/D/G支持这一拆分。

**Promptbreeder 的递归性有明确范围。** 它以 `P′ = LLM(M + P)` 修改任务提示，以 `M′ = LLM(H + M)` 修改变异提示；超变异提示 H 与外部搜索结构固定。附录B的超变异消融测量整个搜索期间的群体平均适应度，表7/8测量搜索中生成更好后代的比例；这些结果未独立证明冻结后的更新器能改善另一批父提示。父提示质量、样本和搜索阶段仍可能影响观察。§6明确提示流程拓扑不变。

上述定位不意味着其他论文完全没有更强的更新器验证，也不构成尚无人研究的空缺证明。

## 4. 候选研究建议

以下是本轮综合提出的评价与研究切口，尚未验证新颖性，也未启动实验。

1. **先测修改质量。** 从相同父策略与轨迹出发，仅改变反馈或更新规则，比较修改在独立样本上的增益、退化率和修改类型，排除候选数量及起点难度的影响。
2. **分离搜索贡献。** 固定提案过程比较选择、保留和验收；或对固定候选集比较选择器。最终性能、单次修改质量与选择收益分别记录。设计消融本身并不自动构成论文贡献。
3. **学习更新器时再冻结验证。** 将学得的 mutation prompt 固定，在另一批父策略状态上比较更新效果。先确认其作用，再决定是否扩展到不同任务族。
4. **明确优化单位。** 改好一个答案或程序实例，与改好可重复使用的 Agent 策略分别评价。保持最终标签、任务定义和评价标准固定，避免把评价标准变化混作策略改进。

若实际问题是多模块责任归因，应重点对照 TextGrad/Trace；若主要依赖分数筛选组合，应对照 MIPRO；若依赖历史分数形成候选，应保留 OPRO。不是把这些模块重新组合就足以声称新增。

## 5. 正式来源、全文定位与读取边界

| 文献 | 正式 sourceURL / 全文及定位 | 本轮实际读取范围 |
| --- | --- | --- |
| GEPA | [ICLR正式记录](https://proceedings.iclr.cc/paper_files/paper/2026/hash/0e9e708b6f48e14fd0ac29e167413f76-Abstract-Conference.html)；[正式全文](https://proceedings.iclr.cc/paper_files/paper/2026/file/0e9e708b6f48e14fd0ac29e167413f76-Paper-Conference.pdf)：§3、§4表3、附录C/D、G.1/G.4、H观察6 | 正式全文的机制、选择消融、实验条件、跨模型迁移等相关部分；未逐页审核全部提示示例 |
| Promptbreeder | [ICML/PMLR正式记录](https://proceedings.mlr.press/v235/fernando24a.html)；[最终会议PDF](https://raw.githubusercontent.com/mlresearch/v235/main/assets/fernando24a/fernando24a.pdf)：§3.2.3、§4–6、附录B图4、K.3/K.4表7–8 | 最终PDF相关正文及消融经Python内存解析；先前arXiv稿与最终版分开，最终版优先 |
| TextGrad | [Nature正式记录](https://www.nature.com/articles/s41586-025-08661-4)；[预印本全文](https://arxiv.org/pdf/2406.07496)：§2、Instance vs Prompt Optimization、§3.3、附录E | 期刊元数据与摘要已核验；期刊全文受站点重定向限制，方法和提示实验定位来自2024预印本v1，未审核期刊新增实验 |
| MIPRO | [EMNLP主会记录](https://aclanthology.org/2024.emnlp-main.525/)；[全文](https://aclanthology.org/2024.emnlp-main.525.pdf)：§3.1–3.2、§4.3–4.4、表1–2 | 正式全文相关方法、任务及变体实验；另外核查了当前DSPy文档，不把v2与论文版本等同 |
| OPRO | [ICLR正式记录](https://proceedings.iclr.cc/paper_files/paper/2024/hash/3339f19c5fcee3ad74502947a32be9e6-Abstract-Conference.html)；[全文](https://proceedings.iclr.cc/paper_files/paper/2024/file/3339f19c5fcee3ad74502947a32be9e6-Paper-Conference.pdf)：§2、§5.1、§5.2.3表4、§5.3 | 正式全文定点阅读，主要核查接口、实验和同域数据集迁移 |
| ProTeGi | [EMNLP主会记录](https://aclanthology.org/2023.emnlp-main.494/)；[全文](https://aclanthology.org/2023.emnlp-main.494.pdf)：§2方法、实验部分图4及定性分析 | 摘要和实验/局限定点阅读，未把完整实现细节标为已深读 |
| EvoPrompt | [ICLR正式记录](https://proceedings.iclr.cc/paper_files/paper/2024/hash/9156b0f6dfa9bbd18c79cc459ef5d61c-Abstract-Conference.html) | 本轮仅正式元数据、摘要和作者仓库；不支持更细的迁移或消融结论 |
| Trace | [NeurIPS主会记录](https://proceedings.neurips.cc/paper_files/paper/2024/hash/83ba7056bce2c3c3c27e17397cf3e1f0-Abstract-Conference.html)；[全文](https://papers.neurips.cc/paper_files/paper/2024/file/83ba7056bce2c3c3c27e17397cf3e1f0-Paper-Conference.pdf)：§3–4、§5.1/5.2/5.4、§5.3 | 正式全文方法与实验定点阅读，尤其追踪表示、遮蔽轨迹和移除记忆对照 |

框架背景：[DSPy，ICLR 2024正式记录](https://proceedings.iclr.cc/paper_files/paper/2024/hash/f1cf02ce09757f57c3b93c0db83181e0-Abstract-Conference.html)。

工件入口：[GEPA](https://github.com/gepa-ai/gepa)、[TextGrad](https://github.com/zou-group/textgrad)、[DSPy优化器文档](https://dspy.ai/3.1.0/learn/optimization/optimizers/)、[OPRO](https://github.com/google-deepmind/opro)、[ProTeGi](https://github.com/microsoft/LMOps/tree/main/prompt_optimization)、[EvoPrompt](https://github.com/beeevita/EvoPrompt)、[Trace](https://github.com/microsoft/Trace)。OPRO、ProTeGi工件由论文给出，本轮直接仓库页抓取失败；其余已读取仓库或文档页面。存在链接不等于验证可复现；本轮均未运行。Promptbreeder的[极简实现](https://github.com/dylski/promptbreeder)明确是概念实现，不能代替原论文完整工件。

## 6. 检索记录与覆盖限制

检索日期：2026-10-15。使用通用Web Search发现来源，随后核查ICLR、PMLR、ACL Anthology、NeurIPS、Nature及作者工件。未设发表日期过滤。搜索工具未暴露稳定排序、结果总量、可遍历页数或完整截断边界；结果范围未知。本轮是八类近邻的定向审查，不是穷尽性系统综述。读取某一方法或实验段落不等于全文所有主张均已核实。

精确主要queries如下（保留原始拼写与待核实年份）：

```text
GEPA Reflective Prompt Evolution Outperforms Reinforcement Learning ICLR 2026
TextGrad Automatic Differentiation via Text Nature 2025
Optimizing Instructions Demonstrations Multi Stage Language Model Programs MIPRO EMNLP 2024
Promptbreeder Self Referiential Self Improvement Language Models ICLR 2024
site.proceedings.iclr.cc 2026 GEPA Reflective
site.nature.com Optimizing generative AI backpropagating language model feedback TextGrad
site.aclanthology.org ProTeGi Automatic Prompt Optimization Gradient Descent Beam Search 2023
site.openreview.net Large Language Models as Optimizers ICLR 2024
site.dspy.ai MIPROv2 optimizing instructions demonstrations three stages
TextGrad Nature full text PMC 2025 feedback
Promptbreeder official code github google deepmind
DSPy compiling declarative language model calls self improving pipelines ICLR 2024
"Optimizing generative AI by backpropagating language model feedback" "PMC"
"Promptbreeder" "github.com" "code"
site.proceedings.iclr.cc "DSPy" "State-of-the-Art"
site.arxiv.org "prompt optimization" "cross-task" "2026"
Trace End to End Generative Optimization AI Agents OptoPrime ICLR 2025
site.nature.com/articles/s41586-025-08661-4 BBH BIG Bench Hard prompt
site.github.com/zou-group/textgrad TextGrad
site.github.com/beeevita/EvoPrompt official
```

Promptbreeder、Trace查询中的会议猜测最终分别以ICML 2024和NeurIPS 2024主会记录纠正，没有沿用查询猜测。跨任务扩展检索得到的预印本线索未继续纳入本次八方法机制审查，不据此宣称该方向已被充分覆盖。
