# 补充 G：程序归纳与形式证明的任务—方法配对

日期：2026-10-15。性质：定向文献核查与选型建议。未安装环境、未运行候选方法、未调用实验模型；论文结果不是本项目结果。本补充扩展抽象任务池，不把原 ALFWorld 推荐视为已定方案。

## 1. 推荐次序与配对状态

| 次序 | 具体配对 | 已有证据与本项目需要新增的工作 |
|---|---|---|
| 1，最贴近当前兴趣 | **CodeARC 匿名函数归纳＋固定权重的提示／工作流更新器**；优先考虑将 GEPA 或 ADAS 接在查询—合成—反例修正执行器之外 | CodeARC 的交互任务与评分已公开；**GEPA／ADAS＋CodeARC 是建议适配，不是这几篇论文已经验证的组合**。先保持执行器不变，只改可复用的查询、假设或修正策略 |
| 2，现成配对最明确 | **ADAS / Meta Agent Search＋ARC-AGI-1 小网格子集** | 已有 ICLR 2025 方法—任务实验，更新的是跨题复用的 Agent 代码；但原论文只测特定子集，不能写成完整官方 ARC 测试结果 |
| 3，条件性数学分支 | **LEGO-Prover＋miniF2F 的 Isabelle 版本** | 固定 LLM、增长可验证引理库，符合持久更新形式；但已有针对库复用和预算的反面复核，工程成本较高，暂不优先于前两项 |

这是适配性判断，不是性能排名。若希望最小化新增适配，第二项应先于第一项；若希望研究“不完全反馈如何促成可复用规则修订”，第一项更贴近问题。Hypothesis Refinement／Hypothesis Search 适合作为第一项的执行器和诊断参照；它们原本主要改当前题的假设，不能直接充当已证明跨题进化的主方法。

## 2. CodeARC：更接近黑盒规则学习，但持续更新尚待适配

[CodeARC 作者官网](https://anjiang-wei.github.io/CodeARC-Website/)明确标注 **COLM 2025**，提供正式 OpenReview 身份、代码和数据；[全文 v2](https://arxiv.org/html/2503.23145v2)已定位 §3–5、§6.1。任务给出若干输入输出例子，Agent 可查询隐藏 Python 函数、提交候选程序，并由差分测试返回反例。主设置先给 10 个例子，总额度 30 个输入输出对、2 次 oracle 调用；这很适合区分观察不足、错误归纳和修正失败。

公开任务来自 HumanEval+、MBPP+、APPS，共 **1114 个函数**。Annotated 与 Anonymized 是同一函数的两种表示；[官方数据页](https://huggingface.co/datasets/anjiangwei/CodeARC-Problems)显示 2228 行、一个名为 `train` 的 split。因此不能把两种表示拆成独立训练和测试，也不能把该标签当成论文给出的更新训练集。需按原始函数身份分组划分优化／验证／最终测试，防止同题异名跨集合。官网与[代码库](https://github.com/Anjiang-Wei/CodeARC)已读，未逐文件审计执行器。

论文还做了轨迹监督微调；这部分不属于本项目固定权重路线。可借任务协议，以已有固定模型作为执行器，另研究跨题持久提示或工作流更新。差分测试仍是有限检验，不能宣称程序语义等价；实验必须区分更新器可见反例与最终独立检查。公开来源的预训练泄漏仍可能存在，函数匿名化不能消除算法记忆。工程重点是 Python 执行隔离、超时和差分 oracle 的稳定性。

CodeARC 各来源、两个名称版本，以及扩展的 BigCodeBench 函数，主要仍是程序归纳族内扩展；不能数成四五类完全不同任务。论文 BigCodeBench 结果也应区分“从自然语言写代码”和“把函数改成黑盒查询任务”两种协议。

## 3. 两类 Hypothesis 方法：可解释的内循环，尚无跨题更新证明

**Hypothesis Refinement** 的正式题名为 *Phenomenal Yet Puzzling: Testing Inductive Reasoning Capabilities of Language Models with Hypothesis Refinement*，**ICLR 2024**。[正式全文](https://proceedings.iclr.cc/paper_files/paper/2024/file/05d2175de7ee637588d1b5ced8b15b32-Paper-Conference.pdf)及[HTML v2](https://arxiv.org/html/2310.08559v2)已读方法、结果和附录 A。固定 LLM 提出规则，由任务专用解释器检验、选择，再依失败样例修订。测试包括 ACRE 因果规则、MiniSCAN 组合语法、List Functions 列表变换、MiniARC 网格变换。

这套具体数据较适合小规模机制分析：List Functions 为 250 个任务，每题 8 个已见例子、8 个未见例子；MiniARC 原有 149 题，作者过滤后用 130 题，每题 3＋3 个例子。后者是 5×5 变体，不是完整 ARC。论文没有证明所有任务获益，MiniARC 原始正确率甚至落后于部分直接输出基线。其循环是**逐题假设修正**，没有由前题学习持久规则库再迁移后题的评测。

**Hypothesis Search: Inductive Reasoning with Language Models** 同为 **ICLR 2024**。[正式全文](https://proceedings.iclr.cc/paper_files/paper/2024/file/a934282496e7b907f5d48d49bb4c9d7d-Paper-Conference.pdf)已定位 §2、§3、附录 A/B：先采样自然语言假设，再实现成 Python，执行例子并修复。任务包括 ARC、1D-ARC、SyGuS 字符串变换和 List Functions；[官方代码](https://github.com/Relento/hypothesis_search)可用。正式 PDF 的主要 ARC 实验为 100 题，官网摘要仍可见早期 40 题结果，引用应注明版本。

其 SyGuS 设置把全部给定例子都用于检验，以“通过所有例子”为成功，并无独立未见输入检验；不能拿这个分数代表规则泛化。该论文同样主要支持同一搜索算法在多种归纳任务上分别运行，不能推出搜索器或经验跨题学习。ARC、1D-ARC、MiniARC 是近邻；ACRE 与 MiniSCAN 扩大了规则类型，仍主要共享少样本规则归纳范式。

## 4. ARC＋ADAS：明确的跨题更新，但须保留子集边界

[ADAS 正式身份](https://proceedings.iclr.cc/paper_files/paper/2025/hash/36b7acf6f6010652b3f2a433774a66fe-Abstract-Conference.html)为 **ICLR 2025**；[全文](https://proceedings.iclr.cc/paper_files/paper/2025/file/36b7acf6f6010652b3f2a433774a66fe-Paper-Conference.pdf)已定位 §3、§4.1–4.3、附录 E。Meta Agent Search 根据旧 Agent 及其成绩档案编写新 Agent，持续改变可复用提示和控制代码，基础 LLM 不在搜索中微调。ARC 执行器输出变换程序，用示范对检验，再预测新网格，最终按整格精确匹配评分。

原实验从 ARC 公共训练集中选 **≤5×5** 的题，抽 **20 题作搜索验证、60 题作 held-out test**，搜索 25 轮。不能将其简称为 ARC-AGI-1 官方 400 题评测，更不是 ARC-AGI-2。论文也把同一搜索算法用于数学、科学问答和阅读理解；跨域产物迁移证据主要来自 **MGSM→其他数学／非数学任务**，ARC 部分明确的是跨模型迁移。

[ARC-AGI 官方仓库](https://github.com/fchollet/ARC-AGI)公开 400 training、400 evaluation 题，每题内部又有 `train` 示范和 `test` 输入；这两个层次不可混淆。原库是静态题集，不自带覆盖全部题目语义的生成器。开发阶段若反复使用公开 evaluation 成绩改更新规则，会形成评价适配；颜色或旋转增强也不能自动视作新独立任务。相较 CodeARC，ARC 解释更依赖空间表示，示范更少，容易把感知／表示瓶颈混入更新机制。

## 5. DreamCoder、SOAR、LILO 的固定权重边界

用户当前约束是**基础 LLM 权重固定**，不自动禁止训练辅助神经模块。“首版完全免训练”若被采用，应明确是我们为减少工程与归因复杂度提出的设计选择，不能写成用户已经给出的限制。

**DreamCoder** 的 *Bootstrapping Inductive Program Synthesis with Wake-Sleep Library Learning* 是 **PLDI 2021**，由 [MIT 正式版本记录](https://dspace.mit.edu/entities/publication/86d768ab-558f-4fb1-b92e-9288de643ccb)核实。已读[相关 arXiv 全文](https://arxiv.org/pdf/2006.08381)的 wake/sleep 与 dreaming 方法段：既提炼函数库，也训练 neural recognition model 引导程序搜索。它本身是非 LLM 的机制先驱，适合作库学习与搜索协同的参照；不能把它的完整设定直接等同于固定基础 LLM 的 Agent 基线。此处不混同其后续题名与版本。

**SOAR** 的 *Self-Improving Language Models for Evolutionary Program Synthesis: A Case Study on ARC-AGI* 为 **ICML 2025**，[正式记录](https://proceedings.mlr.press/v267/pourcel25a.html)、[全文 §3–4](https://arxiv.org/html/2507.14172v1)已核。搜索与 hindsight 重标记后微调 LLM 的采样／修正能力交替进行，故核心自改进明确不满足当前固定基础 LLM 权重的条件。仅取其无微调 Sample&Refine 可以作题内搜索对照，不能继承完整 SOAR 的学习结论。

**LILO** 为 **ICLR 2024**。[正式全文](https://proceedings.iclr.cc/paper_files/paper/2024/file/819cebb05f993840e8a52d7564c5c282-Paper-Conference.pdf)已定位 §3–4、Table 1、附录 A.5/B.1/B.3：固定权重的 LLM 合成程序、Stitch 压缩并重构库、AutoDoc 命名和写文档；完整版另训练辅助识别网络，每轮 10K 训练步。**若只约束基础 LLM 权重，LILO 并不直接违反当前要求**，但应把辅助识别器学习列为独立改进来源。若首版选择完全免训练，可考虑去枚举搜索的官方消融；它保留库更新，但在线三域成绩未超过纯 LLM Solver，不能继承完整版的效果结论。LOGO 中去搜索还撤去了 CNN 对绘图的条件输入，亦非纯粹“训练开关”比较。

其 REGEX／CLEVR／LOGO 三域支持算法分别复用，不等于一个库跨域通用。LILO 的库压缩、文档误导、重构后退化值得借鉴；[官方仓库](https://github.com/gabegrand/lilo)依赖 DreamCoder、OCaml 与旧 API 模型，移植成本也高于简洁 Python 归纳执行器。

## 6. 形式证明：严格验证并不自动保证经验有用

**LEGO-Prover，ICLR 2024**，[正式全文](https://proceedings.iclr.cc/paper_files/paper/2024/file/85dca46374dc0f27b4bb5f265b3d17f0-Paper-Conference.pdf)已定位 §3、§4、Table 2、附录成本分析。模型通过提示产生、演化和检索已由 Isabelle 验证的引理，论文明确无需模型训练。miniF2F 有 488 题，valid/test 各 244；论文将两者都作在线求解池，并非先在 valid 学库再冻结到 test。另有人工非形式证明与模型生成非形式证明两种条件，不能混报为“只给命题”的证明能力。此实现是 **Isabelle，不是 Lean**。

[2025 年反面复核全文](https://arxiv.org/html/2504.03048v1)已读 §2–5：更换若干模型后，作者发现跨题引理复用很弱，匹配计算预算后没有稳定优于简单 Draft-Sketch-Prove。其原始预印本身份已核，另有改名的 OpenReview 稿，但本轮未确认正式录用；结论只约束所测版本与设置。原 LEGO-Prover 也有成本消融，不能概括为原文完全没控制成本，两者比较对象和计价方式不同。

[官方实现](https://github.com/wiio12/LEGO-Prover)需要 Isabelle2022、PISA、Scala/Java，README 明确仅在 Ubuntu 环境测试。若选择证明方向，应先研究“被验证的引理是否真正可复用”，并冻结库检验后题收益。miniF2F 的不同证明语言版本共享题目，不算不同任务族。与算法发现相比，证明给出更强正确性约束却增加专门工具与库知识；与形式规划相比，程序归纳更直接暴露未知规则与有限反例的矛盾。以上取舍是本项目推断，非跨基准胜负证据。

## 7. 如何把任务选择落实为机制问题

下面是拟议设计，不是已经确认的研究空缺。若采用 CodeARC，第一轮应固定可见信息：输入输出示范、主动查询返回值、候选执行结果和有限反例；不让更新器读取隐藏函数源码或最终审计结果。可持久修改的对象先选一种，例如“下一题怎样提出候选规则、怎样选择诊断输入”的文字策略，而非同时开放提示、工具函数、库、检索器和流程。这样才能判断改进来自何种反馈和更新动作。

必须区分三层成效：当前函数经反例修复后通过测试；从一组函数中形成策略后，对独立函数更有效；从经历中改变更新器后，更新器自身更会提议修改。前两层并不自动证明第三层。对原有研究主线，第二层已经是合理起点，无需先承诺最强递归自改进。若最后只得到更强的逐题搜索器，应按搜索改进报告，而非把多次尝试称为持续学习。

一个可检验的候选问题是：**反馈足以推翻当前程序，却不足以指明应形成什么通用经验时，更新器是否把局部例外写成错误的一般策略？** 可保留同一批经历，比较不同反馈表述产生的候选更新；在未参与选择的函数上检查更新是否改善、是否破坏先前能力。须保留未被采用的候选，否则“保留下来的策略越来越好”无法说明提议质量提高。反例数量、查询次数、候选程序数以及策略产生阶段的计算都应计入比较。

扩展任务也应现在明确，而不是以后再找。建议先以列表／字符串程序归纳作为容易审计的子域，再把网格规则归纳作为邻近扩展，最后从正式规划或数学推理中选一个真正不同任务族。前两项能检查规则表示变化，却不能独自承担“通用 Agent”的结论。若另一路的算法发现任务已具备成熟生成器和明确目标，也可以反过来把它作主任务、CodeARC 作归纳扩展；选择依据应是可复现的更新对象和反馈条件，不是排行榜知名度。

## 8. 检索与读取边界

检索日期 2026-10-15，使用 Web 搜索与原始论文／作者仓库；未设日期筛选，默认相关性排序；搜索接口未给完整总数和可核分页，故不声称穷尽。主要精确查询如下，随后沿正式会议页、论文引文和官网链接核查：

```text
LILO learning interpretable libraries by compressing and documenting code ICLR 2024
SOAR self improving language model agents program synthesis ARC library 2024 2025
ARC program synthesis refinement fixed language model weights ICLR 2025 CodeIt
site.openreview.net "LILO" "Learning Interpretable"
site.proceedings.mlr.press "Self-Improving Language Models for Evolutionary Program Synthesis"
DreamCoder PLDI 2021 recognition model training programs library learning official
CodeARC COLM 2025 official github benchmark
"Automated Design of Agentic Systems" ARC 2025 ICLR
"Phenomenal Yet Puzzling" "Hypothesis Refinement" ICLR 2024
"Hypothesis Search: Inductive Reasoning with Language Models" ICLR 2024
site.iclr.cc "LEGO-Prover"
"LEGO-Prover" "arxiv"
"Disassembling the LEGO-Prover"
"Disassembling the LEGO-Prover" "ICLR 2026"
"LLM Library Learning Fails" conference
"CodeARC" site:openreview.net
"miniF2F" site:openreview.net ICLR 2022
```

以上为定向范围扩展，不是系统综述。全文可访问不代表逐页精读；已读定位写在各条目。部分 OpenReview 页面被浏览器验证阻挡，优先改读正式 proceedings 或 arXiv；DreamCoder 的 MIT 作者 PDF 抓取失败，改读相关 arXiv 方法段并用 MIT 元数据确认 PLDI 身份。未完成 Lean 生态的全面检索、CodeARC 执行器逐文件审计或任何环境复现。
