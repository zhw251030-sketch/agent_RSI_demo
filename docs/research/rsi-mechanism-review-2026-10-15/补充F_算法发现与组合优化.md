# 补充 F：算法发现与组合优化的联合选型

日期：2026-10-15。范围：固定 LLM 权重，改进启发式程序及其生成、反思、选择机制。已核查一手论文、正式出版页和部分官方代码；没有安装环境、执行任务、调用实验模型或独立复现。以下是建议，不是已冻结协议。

## 1. 推荐及研究边界

**建议以 ReEvo 为机制分析入口、EoH 为并列成熟基线，在线一维装箱为主任务，TSP 为首个扩展、排列流水车间调度 PFSP 为第二扩展。** 黑盒函数优化保留为统计学相关的另一条实质分支，以 FunBO 为入口；不必第一轮同时建设。

这组选择支持“同一改进机制在多个任务上验证”：外层保持生成—执行—反馈—修订—选择过程，内层更换任务接口和评分器。它不要求把装箱程序直接用于 TSP，也不自动证明跨任务经验迁移。在线装箱的优点是动作和反馈清楚、无需世界模拟器、程序短、可改变输入分布；弱点是它可能退化为一个窄评分函数的搜索，必须另测生成方法是否改进。

ReEvo 的短期反思比较两个程序及其表现，长期反思整合旧总结和新比较，随后指导精英程序变异；EoH 同时保存自然语言思路和代码，使用探索、修改、参数调整等固定提示算子。它们适合把“反馈是否使下次修改更可靠”变成可检查的问题，但已有方法并不弱，不能把加入反思、正负经验或条件化检索本身当新贡献。[ReEvo 正式论文](https://proceedings.neurips.cc/paper_files/paper/2024/hash/4ced59d480e07d290b6f29fc8798f195-Abstract-Conference.html)、[EoH 正式论文](https://proceedings.mlr.press/v235/liu24bs.html)。

## 2. 正式方法与直接近邻

| 方法、正式身份 | 更新对象与已验证任务范围 | 对选题的作用 |
| --- | --- | --- |
| [FunSearch，Nature，2023 在线发表](https://doi.org/10.1038/s41586-023-06924-6) | 冻结模型生成函数，执行评分后更新分岛程序库；主要是 cap set 构造和在线装箱 | 奠定可执行产物搜索；不是生成器权重训练，也没有证明改进器本身学会迁移 |
| [EoH，ICML 2024](https://proceedings.mlr.press/v235/liu24bs.html) | 思路＋代码种群；在线装箱、TSP 的 GLS 扰动、PFSP 的 GLS 扰动 | 方法和三任务配套完整；当前仓库已扩展，不能把新增示例当原论文实验 |
| [ReEvo，NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/hash/4ced59d480e07d290b6f29fc8798f195-Abstract-Conference.html) | 程序种群＋短长期语言反思；TSP、CVRP、OP、MKP、装箱、电子设计，覆盖构造、ACO、GLS 等 | 适合作为反馈机制入口；六类问题不等于同一经验库跨六任务迁移 |
| [MCTS-AHD，ICML 2025](https://proceedings.mlr.press/v267/zheng25o.html) | 保存程序演化树，按 MCTS 选择和扩展，继续探索暂时低分节点 | 排查“收益只是更好的候选保留与搜索分配”；含在线装箱、TSP/KP 构造及多类 ACO |
| [FunBO，ICML 2025](https://proceedings.mlr.press/v267/aglietti25a.html) | 演化贝叶斯优化采集函数，每个候选须执行完整 BO 回路评分 | 真正跨目标函数验证；更新的是采样规则程序，不是黑盒目标函数 |
| [MTHS，ICML 2026](https://proceedings.mlr.press/v306/liu26ge.html) | 双层演化任务无关元启发式模板与任务程序；TSP、CVRP、PFSP 联合设计，向未见装箱、连续优化、admissible set 测试 | 直接覆盖“抽象可复用方法”；装箱采用全体物品可见的离线设定。连续优化有收益，admissible set 没有一致收益，不能概括成通用迁移 |
| [RefineEvo，ICML 2026](https://proceedings.mlr.press/v306/wu26ap.html) | 规划器调度算子、修改算子提示；正负经验池按轨迹和情境检索。包含 TSP、KP、装箱及 ACO/GLS 实验 | 比 ReEvo 更直接的“改进器更新”近邻；Table 7 已隔离源经验池、关闭新增经验积累，研究跨任务使用效果 |
| [PathWise，ICML 2026](https://proceedings.mlr.press/v306/gungordu26a.html) | 程序推导图保存父代、理由和成绩；策略代理选行动，世界模型代理生成代码，两个 critic 分别给反馈；无 LLM 参数更新 | 已研究有状态规划和路由反思，覆盖 TSP、KP、CVRP、MKP、OP、在线／离线装箱；不是仅有静态交叉变异 |

还定位到作者预印本 [Back to the Beginning of Heuristic Design](https://arxiv.org/abs/2605.06123)，直接把知识作为主要搜索对象；本轮取得作者全文，但未完成相关结果定位、也未在 PMLR 卷目录核实正式身份，暂不据此作数值或录用结论。

## 3. 主任务：在线一维装箱

任务是按到达顺序把每个物品放进容量固定的箱子，放下后不重新安排，目标是少用箱子。候选函数接收当前物品大小及可容纳它的箱子剩余容量，输出优先级；执行器选择最高分箱子。它不应获得未来物品列表。

**已有数据与代码。** [FunSearch 官方 notebook](https://github.com/google-deepmind/funsearch/blob/main/bin_packing/bin_packing.ipynb) 内嵌 OR3：20 个各 500 件实例、箱容量 150；以及 Weibull 5k：5 个各 5,000 件实例，并给出骨架、发现的规则、容量检查和 L1 下界。OR 数据的原始出处是 [OR-Library](https://people.brunel.ac.uk/~mastjjb/jeb/orlib/binpackinfo.html)，文件另含最佳已知箱数；其原始数据集不是自动规定了在线测试顺序的完整协议。

[ReEvo 生成器](https://github.com/ai4co/reevo/blob/main/problems/bpp_online/gen_inst.py) 用 Weibull shape=3、scale=45，截断到 100 后取整，容量 100；分别生成训练／验证／测试各 5 条 5k 流，另有 5 条 10k 和 1 条 100k 流。[评分入口](https://github.com/ai4co/reevo/blob/main/problems/bpp_online/eval.py) 返回相对平均 L1 下界的超额箱数百分比。**L1 是下界，不能把该数一律称为真实最优差距。** 该生成器没有内部固定随机种子；未来须冻结种子和数据快照。代码注释提及 FunSearch 测试数据，不意味着重新生成的序列与原始内嵌数据相同。

EoH 原论文 §4.1 用五条 5k/C100 实例作演化评价，测试不同长度和容量；当前 [bp_online/prob.py](https://github.com/FeiLiu36/EoH/blob/main/examples/bp_online/prob.py) 与 [get_instance.py](https://github.com/FeiLiu36/EoH/blob/main/examples/bp_online/get_instance.py) 仍可读取，但后者内嵌数据注释称其为 Weibull 5k test dataset。不能直接把这一份数据同时当本项目训练和独立测试。

**建议协议。** 保留公开实例作复核；按官方分布另生成并冻结独立演化、选择、最终测试三组。先用 C100、5k 主条件，再测 1k/10k 和 C500；OR3 用作分布外测试。这些规模有先例，但本项目的具体种子、样本量尚未定。测试只用于最后报告，不反馈给演化器。报告箱数、下界差、无效程序率、候选评价数及总模型调用／token，而非只报告最佳一次结果。独立统计单位应是完整搜索运行，物品数量不能冒充独立重复数。

基础对照用 First Fit、Best Fit；强程序对照用公开 FunSearch/EoH 规则固定执行；机制对照至少含同预算独立采样、去反思的搜索及 ReEvo/EoH。若声称普遍在线竞争力，还需纳入 [Harmonic 系列的一手理论基线](https://doi.org/10.1145/585265.585269)，不能由胜过两个常用贪心规则推出全面领先。禁止把先排序的离线 FFD 与严格在线算法作同信息条件比较。

## 4. 扩展任务及强基线

**TSP 优先。** 给定城市／距离，构造一条每城一次并回到起点的短回路。低复杂度入口是 ReEvo 的下一节点选择函数：[eval.py](https://github.com/ai4co/reevo/blob/main/problems/tsp_constructive/eval.py)、[gen_inst.py](https://github.com/ai4co/reevo/blob/main/problems/tsp_constructive/gen_inst.py) 已读。生成器固定 seed=1234，训练为 64 个 TSP50；验证为 20/50/100/200 各 64 个；测试扩至 500/1000，各 64 个。坐标均匀采样于单位正方形。评分器查重复访问、计算闭合路径长度。

更强版本沿 EoH 的 TSP-GLS：在固定 2-opt/relocate 搜索器里演化距离惩罚函数；原论文训练用 64 个 TSP100，评价相对 Concorde 解的差距，另测 [TSPLIB](https://comopt.ifi.uni-heidelberg.de/software/TSPLIB95/)。构造与 GLS 是不同任务接口，不可把两者的绝对成绩直接当更新器优劣。传统基线应包括最近／最远插入、同资源 GLS，以及 LKH/Concorde 作为强求解或参考解来源；仅赢最近邻不足。TSPLIB 必须遵守文件规定的整数距离类型，不能直接用未取整欧氏距离对照其最优值。

**PFSP 第二扩展。** 输入作业×机器加工时间矩阵，所有机器采用同一作业排列，最小化最后完成时间 makespan。EoH 原论文 §4.1、Appendix D 用 64 个随机训练实例：50 作业、2–20 机器；演化 GLS 的加工时间扰动及作业优先级，在 Taillard 实例测试。官方 [fssp_gls_numba](https://github.com/FeiLiu36/EoH/tree/main/examples/fssp_gls_numba) 的 prob.py、get_instance.py 已静态读取，存在 TrainingData 和 TestingData/Taillard 的加载约定。当前默认只评价 3 个训练实例、每实例 30 秒及 1,000 次迭代上限，不能说默认值复现了论文 64 实例协议。基线用 NEH、NEHFF、相同邻域 LS/ILS；测试报告相对固定版本最佳已知上界的差距，并同时控制求解时间。Taillard 原站本轮未访问成功，已核查作者论文和 EoH 数据加载器，尚未逐文件校验数据完整性。

## 5. 黑盒优化备选与统一机制范围

FunBO 更贴近统计学：程序根据 GP 的预测均值、方差和当前最好值选择下一次实验点。其 OOD-Bench 用一维 Ackley/Levy/Schwefel 演化、一维 Rosenbrock 选择，在九种其他函数／维数测试；ID-Bench 对每种函数取 20 训练、5 验证、100 测试变体，另有 SVM/AdaBoost 超参数任务。报告归一化 simple regret 随查询次数变化，对照 EI、UCB、PI、posterior mean、随机，以及适用条件下的 MetaBO/FSAF。该分支每个程序评价都要跑完整 BO，嵌套评价负担高于装箱。[论文 §4–5、Appendix B–D](https://proceedings.mlr.press/v267/aglietti25a.html) 给出主要细节，但论文所链接的 FunSearch 仓库没有确认提供 FunBO 全套任务代码；不要称为直接开箱复现。

**必须区分三个结论。** 新物品流得分更好，只能证明装箱规则泛化；从相同候选起点出发，保留经验／算子更新能更有效地产生下一候选，才检验改进过程；将经验或改进器状态移到未见任务族才检验迁移。第三项不是“同机制多任务验证”的必需条件。RefineEvo 已有正负经验、情境检索、跨任务池消融；MTHS 已有元启发式转移。因此可优先观察小评价集的排序不稳定、错误反思是否被修正，但本轮不能把这些候选现象写成已发现空缺。

有限预算下，先选择短函数＋廉价执行器，减少内层局部搜索的嵌套，比较固定评价预算下的完整搜索曲线。缩小规模须标为新协议；模型调用数、反思调用及实际执行耗时均要算入。原论文的较低候选数并不等于在任意模型、任务上同样省资源。

可以先固定一个最小机制问题：相同两份父程序在少数实例上的比较，是否足以支持反思声称的改进理由。对同一候选池，分别提供总体均分、逐实例差分、带不确定性的比较，再检查后续候选的独立验证收益。这是实验设计建议，尚无失败现象证据，也不预定哪种反馈胜出。为排除成品缓存，应重置当前候选或使用新的起点，单独移植总结／算子状态；为排除额外搜索，应保持候选评价总量一致，同时另报全部模型计算量。重复运行比较中，应配对相同数据和随机种子，并记录每次更新产生的实际收益；仅从最后赢家反推“这条总结正确”不构成机制证据。扩到 TSP/PFSP 时冻结相同的外层更新规则，允许事先声明的函数签名和评分器适配，不为每个任务另造一套机制。

## 6. 本轮证据定位和检索边界

已读定位：FunSearch 作者公开全文“Online bin packing”、Table 1 与官方 notebook cells 1、4、8–11；EoH 正式 PDF §3–4、Appendix B–D；ReEvo 正式 PDF §4–5、Appendix C；MCTS-AHD 正式 PDF §4、任务配置附录及官方 README；FunBO 正式 PDF Fig.1、§4–5、Appendix B–D；MTHS 正式 PDF §2–3.5、Appendix C，及 bpp/evaluation.py（一次传入所有 weights，属离线）；RefineEvo 正式 PDF §3–4、Tables 5–8，并读官方 planner_interface.py、bpp_online/eval.py；PathWise 正式 PDF §3–4、Appendix B/D，及官方在线装箱评分器。以上是相关章节读取，不是每篇全文逐段精读。

检索日期均为 2026-10-15，Web Search，无日期／语言过滤；多查询批量检索、仅核查返回的一手来源，未宣称穷尽。关键精确查询包括：`ReEvo reflective evolution large language models hyper heuristics NeurIPS 2024 github`；`Evolution of Heuristics EoH ICML 2024 github`；`FunBO automated discovery Bayesian optimization algorithms ICML 2025`；`FunSearch Nature 2023 bin packing github google deepmind`；`site:proceedings.mlr.press 2025 heuristic discovery MCTS-AHD BLADE HSEvo`；`"automatic heuristic design" "ICML 2026"`；`"RefineEvo" "proceedings.mlr.press"`；`"PathWise: Planning through World Model" ICML official`；`"Hierarchical Representations for Cross-task" github`；`"FunBO" code "github.com" "Aglietti"`。返回总量／分页覆盖未知，搜索摘要只作线索。

已通过 raw 官方文件读取确认关键入口可访问；GitHub API 命中限流、git 元数据请求连接重置，故未固定仓库提交号。没有执行任何下载的研究代码。环境可运行性、依赖兼容、完整数据校验及论文数字复现仍待后续授权实验。
