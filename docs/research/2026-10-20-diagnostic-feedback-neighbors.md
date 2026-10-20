# 诊断反馈与修订：直接近邻核查

核查日期：2026-10-20。服务于[本轮开发对照协议](../protocols/2026-10-20-diagnostic-comparison.md)，不是全面系统综述。本轮查阅正式论文、相关方法与消融位置，以及能够确认来源的官方代码；没有复现这些论文，也没有据此确认新颖性。

## 研究定位

**工具验证、解释失败、保留反思、根据反馈修改程序或公式，都已有正式会议先例。** 当前问题应收窄为：在同一诊断来源与计算规则下，明确要求模型区分观测、解释与未验证预测，是否改变修订行为。

本轮 C 条件是固定的**证据约束提示**，不是自动因果验证门控。观测 ID 存在或被正确引用，不足以证明解释成立。规划执行轨迹帮助定位程序行为；符号残差统计描述拟合误差，不能直接确认物理机制。

## 已定位的直接证据

| 工作与正式身份 | 实际读取位置和机制 | 对当前设计的含义 |
|---|---|---|
| CRITIC，ICLR 2024 | 正文 §3、Algorithm 1、§4 的无工具消融：工具验证后生成 critique，再据此修订。 | “验证后修订”本身已有直接先例；删去工具信息的消融与保持信息相同而改变提示规则，是不同问题。 |
| Generalized Planning in PDDL Domains with Pretrained Large Language Models，AAAI 2024 | 方法中的自动调试流程；官方 `genplan.py` 的候选循环与错误反馈。 | 规划程序执行失败后回传具体错误并重写，是该任务已有的成熟参照。 |
| Teaching Large Language Models to Self-Debug，ICLR 2024 | 正文 §3、Figure 2、§5.2.2 / Table 3：区分简单反馈、单元测试反馈、解释和执行推演，并分析代码执行的作用。 | 提示方式与外部执行信息需要分开考察；不能把新增真实轨迹和新增修订规则同时只给一个条件。 |
| Reflexion，NeurIPS 2023 | 正文关于 Actor / Evaluator / Self-Reflection 的方法说明，以及官方编程循环。 | 将任务反馈总结为自然语言反思再用于后续尝试，已是现成机制；反思文字不自动具有事实或因果正确性。 |
| LLM-SR，ICLR 2025 | 正文 §2、§5.1；官方 evaluator 和经验池的候选评分、存储与提示生成。 | 公式结构生成、参数优化、数据评分和历史候选迭代已有直接先例。训练误差下降不能单独证明新的修订机制有效。 |

### CRITIC：工具信息与修订循环

正式论文的 Algorithm 1 将验证与修订分开。官方数学程序实现先产生 critique，再请求新代码；`use_tool` 控制是否向模型提供执行报告与输出。本次代码核查限于这一程序循环，未运行工具，也未核查所有任务分支。

- [ICLR 正式论文](https://proceedings.iclr.cc/paper_files/paper/2024/file/fef126561bbf9d4467dbb8d27334b8fe-Paper-Conference.pdf)
- [官方 `CRITIC/src/program/critic.py`](https://github.com/microsoft/ProphetNet/blob/master/CRITIC/src/program/critic.py)：`critic`、`use_tool`、两次生成与候选执行。

### llm-genplan：任务本身已有错误反馈修订

AAAI 正式记录确认其发表身份。官方 `get_genplan_from_llm` 对训练任务执行候选，遇到首个失败便将错误信息用于下一次修订；`_run_genplan_on_task_no_timeout` 检查异常、输出类型、动作语法和计划语义，外层另处理超时。当前仓库代码使用人工复制模型回答的入口，不能把静态代码检查写成已复现原论文流程。

- [AAAI 正式论文记录与 DOI](https://ojs.aaai.org/index.php/AAAI/article/view/30006)
- [论文全文](https://arxiv.org/pdf/2305.11014)
- [官方 `llm_genplan/genplan.py`](https://github.com/tomsilver/llm-genplan/blob/master/llm_genplan/genplan.py)

### Self-Debugging：Trace 的关键边界

论文 §3 明确区分 Simple、Unit Test、Explanation 和 Trace。**其中 Trace 是语言模型生成的逐步执行推演，不是程序执行器记录的真实中间状态**；论文因此说明它不需要比代码解释更多的外部信息。Figure 2 给出提示形式，Table 3 检查不执行单元测试的条件。

本项目若额外提供真实行命中次数或返回摘要，已经改变了信息条件，必须让 B/C 共享相同诊断规则。另一方面，候选进程中的行轨迹可受候选干扰，也不能当作抗恶意的可信证明。当前仅核实论文内容，未确认可引用的作者官方实现仓库。

- [ICLR 正式论文，§3、Figure 2、Table 3](https://proceedings.iclr.cc/paper_files/paper/2024/file/2460396f2d0d421885997dd1612ac56b-Paper-Conference.pdf)

### Reflexion：反馈、反思和下一次尝试

NeurIPS 正式记录与正文确认固定权重、基于语言反馈和记忆的框架。官方编程实现调用测试执行器，生成 self-reflection，再将代码、反馈和反思交给后续程序生成。本次只读该编程循环，不将其细节推广到仓库内所有任务。

- [NeurIPS 正式记录](https://papers.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract-Conference.html)
- [正式论文](https://proceedings.nips.cc/paper_files/paper/2023/file/1b44b878bb782e6954cd888628510e90-Paper-Conference.pdf)
- [官方 `programming_runs/reflexion.py`](https://github.com/noahshinn/reflexion/blob/main/programming_runs/reflexion.py)：`run_reflexion` 的执行、反思和再生成步骤。

### LLM-SR：分数引导的公式搜索

正式会议页面核实 ICLR 2025 身份；本次方法阅读使用 arXiv v2 的 §2、§5.1。官方 evaluator 评价公式程序；buffer 根据得分管理候选并构造改进版本提示。这支持将其作为符号侧的重要参照，不能据此断言所有版本都没有诊断机制，也不代表我们已复现其搜索规模或测试结果。

- [ICLR 正式记录](https://proceedings.iclr.cc/paper_files/paper/2025/hash/28df8e730c054c5331855fd4d5403ba9-Abstract-Conference.html)
- [方法与消融正文 v2](https://arxiv.org/html/2404.18400v2)
- [官方 `llmsr/evaluator.py`](https://github.com/deep-symbolic-mathematics/LLM-SR/blob/main/llmsr/evaluator.py)
- [官方 `llmsr/buffer.py`](https://github.com/deep-symbolic-mathematics/LLM-SR/blob/main/llmsr/buffer.py)：`register_program`、`get_prompt`、`_generate_prompt`。

## 为什么采用三组对照

| 条件 | 模型看到的内容 | 新增因素 |
|---|---|---|
| A | 原有执行状态、异常位置和分数 | 参照条件 |
| B | A 加固定诊断观测 | 新增信息 |
| C | 与 B 相同的诊断生成规则，另要求证据引用、可证伪预测及不确定性区分 | 新增提示规则 |

因此，B−A 描述增加诊断信息后的变化，C−B 描述证据约束提示的增量。所有组都计算诊断，A 仅隐藏其模型可见内容；三组使用相同起点、任务、候选上限和模型调用约束。B/C 的初始诊断可完全一致；后续程序不同，观测值自然不同，不应声称完整轨迹逐字相同。

这不是严格因果效应的充分识别：本轮每条件每任务仅一个会话，未做随机重复，实际输出长度和服务时间也可能不同。结果用于核对流程、检查失败模式及判断是否值得扩展。应同时保留全部候选、失败与成本，不能只报告最佳条件。

旧任务、空计划和常数公式均已参与开发；前轮错误也用于形成当前提示。**本轮只属于开发对照，不能作为独立最终验证。** 正式实验需要冻结策略后另设未参与设计的搜索状态、独立选择与评价划分及重复；十道规划题是同一程序的一批评价，不能算十次独立机制重复。

## 新颖性与后续检查

本轮不主张“工具验证后修订”“反思再尝试”或“经验池迭代”为新方法。进一步检索发现 ProCo（EMNLP 2024）也用关键条件验证推动答案修订；本次核实其正式页面和方法概述，未进行完整源码审计。它提示后续新颖性审查还需覆盖不同形式的验证机制。[正式来源](https://aclanthology.org/2024.emnlp-main.714/)

眼下可检验的是具体提示规则在明确的信息条件下是否改善行为。即使观察到正结果，也需先排除信息量、额外计算、单个初始程序及人工调参的解释，再讨论可推广机制。
