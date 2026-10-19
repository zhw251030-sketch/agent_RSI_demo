# 补充 D：新增近邻、评价边界与主检索记录

日期：2026-10-15。与[主报告](固定权重RSI改进机制比较与研究建议_v0.1.md)配套。记录访问范围与证据边界，不代表独立复现。A–C 三份补充另保存各自精确查询。

## 新增方法与邻近证据的读取范围

| 来源 | 身份与实际读取范围 | 可支持的用途／限制 |
|---|---|---|
| [AgentOptimizer 正式记录](https://proceedings.mlr.press/v235/zhang24cd.html)；[最终 PDF](https://raw.githubusercontent.com/mlresearch/v235/main/assets/zhang24cd/zhang24cd.pdf) | ICML 2024。最终 PDF 经 Python 在内存提取，重点读 §2–3；另查看旧题名预印本 | 支持函数库更新、回退／早停、测试退化及 MATH 子领域迁移的讨论。文中样本划分叙述与表格步进值得复现前复核，本报告未采用精确样本数 |
| [Agent-Pro](https://aclanthology.org/2024.acl-long.292.pdf) | ACL 2024。摘要、方法相关段落及附录评测设置定位阅读，未逐段精读全文 | 用作固定权重序贯策略更新近邻；不据其较少任务声称通用性 |
| [EvoTool 正式记录](https://aclanthology.org/2026.acl-long.2016/)；[PDF](https://aclanthology.org/2026.acl-long.2016.pdf) | ACL 2026。§3–4 方法、§5 任务、§6 消融、§7 迁移和局限定位阅读 | 支持归因后定向修改与选择机制已有先例。错误类型变化来自 Blamer 的诊断，不等同经过独立干预验证的因果责任 |
| [CHIME](https://arxiv.org/html/2609.02074) | 2026 预印本；未核实主会录用。读 §3 方法与 §4 实验／协议相关段落 | 规划／执行经验分库、归因后更新、冻结记忆留出评价已被提出。论文用 τ²-bench、VitaBench、BrowseComp-ZH、BFCL-v4；具体运行和评测改动尚未核代码 |
| [On the Fragility of Self-Improving Agents](https://arxiv.org/html/2608.18066v2) | 2026 预印本 v2；读方法、重复运行／顺序与 §4.2 反馈干预 | 可提醒检验方差与经验适用性。添加详细反馈会改变可用信息，不能把这种条件下的增益都归给算法 |
| [Agent Plasticity](https://arxiv.org/html/2610.08902) | 2026-10 预印本；读协议 §2.1、讨论局限及环境附录 | 固定权重，跨回合保存外部工具／技能／记忆，检查独立情境表现。作者承认产物被复用的观察不能单独证明因果，需要移除／替换等干预。适合作评价参考，非已确立的通用改进算法 |
| [Recursive self-improvement of AI research agents](https://arxiv.org/html/2609.26457) | 2026-09 预印本；读 §2 算法和 §3 留出评价 | AIDE² 的外层改内层研究 Agent；外层选择框架固定。“recursive”标题不证明全部元更新逻辑都被学习。反复用于外层选优的成绩应视为选择信号 |
| [Reflective Prompt Optimization of a Deep-Research Agent](https://arxiv.org/html/2610.12601) | 2026-10 预印本；读 §3.3–3.5 协议、§5–6 分析／局限，非逐项复核所有结果 | 已做主题隔离、多种子、反馈形式干预。作者主要用 LLM judge，人工核验较小；其 winner’s curse 解释包含推断，不能当已被彻底隔离的因果事实 |
| [LLMs Cannot Self-Correct Reasoning Yet](https://proceedings.iclr.cc/paper_files/paper/2024/hash/8b4add8b0aa8749d80a34ca5d941c355-Abstract-Conference.html) | ICLR 2024；本轮正式元数据／摘要及 PDF 定位，未深入重审全部实验 | 限定内在自纠错、特定任务与模型条件；不能推成所有反馈驱动改进都不可能 |
| [SCoRe](https://proceedings.iclr.cc/paper_files/paper/2025/hash/871ac99fdc5282d0301934d23945ebaa-Abstract-Conference.html) | ICLR 2025；本轮正式摘要 | 更新模型权重，排除出当前主方法矩阵；不据此评价固定权重路线的效果 |
| [Self-Refine](https://proceedings.neurips.cc/paper_files/paper/2023/file/91edff07232fb1b55a505a9e9f6c0ff3-Paper-Conference.pdf) | NeurIPS 2023；本轮元数据／搜索定位，未重新精读 | 仅作当前答案修正的背景，不纳入已深入比较的 26 方法计数 |

## 评测来源的访问范围

| 来源 | 已检查内容 | 当前使用边界 |
|---|---|---|
| [AgentBoard](https://proceedings.neurips.cc/paper_files/paper/2024/file/877b40688e330a0e2a3fc24084208dfa-Paper-Datasets_and_Benchmarks_Track.pdf) | NeurIPS 2024 Datasets & Benchmarks；§2–3 与任务／指标相关表格 | 九类环境、细粒度进度评价可作后续多任务组织参照；评分器可见的子目标不自动是 Agent 的可用反馈 |
| [AgentBench](https://proceedings.iclr.cc/paper_files/paper/2024/hash/e9df36b21ff4ee211a8b71ee8b7e9f57-Abstract-Conference.html)；[仓库](https://github.com/THUDM/AgentBench) | ICLR 2024；正式摘要与官方 README | 多环境评测入口；本轮没有部署或核查所有子环境 |
| [AppWorld](https://aclanthology.org/2024.acl-long.850/) | ACL 2024；正式元数据、摘要及 PDF 中环境介绍 | 模拟应用、任务与状态测试适合作候选；本轮没有完成完整任务清单和部署审核 |
| [BFCL](https://proceedings.mlr.press/v267/patil25a.html)、[τ-bench](https://proceedings.iclr.cc/paper_files/paper/2025/hash/1b126cc38b8638e07bef37e7b2bb72bf-Abstract-Conference.html)、[ALFWorld](https://alfworld.github.io/) | 延续本次讨论此前核查的正式来源和方法论文任务使用证据 | 保留候选地位；本轮不重新决定项目必须用它们 |

## 查询记录与覆盖边界

使用通用 web search 发现，再优先查看会议／期刊、作者论文与官方仓库。检索日期均为 2026-10-15；未使用发布日期过滤。下列 `site:` 仅作用于相应查询。搜索服务未提供稳定排序、可审计总命中数和完整分页，因此只能声称检查了实际返回、随后访问的相关来源。

第一组：机制、反面证据和任务入口。

```text
recursive self improvement agents self modification evaluator generalization ICLR 2026
"On the Fragility of Self-Improving Agents"
"Large Language Models Cannot Self-Correct Reasoning Yet"
"AgentBoard" "benchmark" "NeurIPS"
"AgentBench" ICLR 2024 benchmark
"AppWorld" ACL 2024 benchmark
"self improving agents" benchmark evaluation generalization 2026
"Self-Refine" NeurIPS 2023 "SCoRe" ICLR 2025
```

第二组：扩展可修改对象、核对正式身份。

```text
"Training Language Model Agents without Modifying Language Models"
"Agent-Pro" "Learning to Evolve"
"AgentSquare" "ICLR"
"Training Language Models to Self-Correct" "ICLR 2025"
site:proceedings.mlr.press "Training Language Model Agents without Modifying Language Models"
site:proceedings.iclr.cc "Large Language Models Cannot Self-Correct Reasoning Yet"
"Agent Plasticity" "Measuring" "2026"
```

第三组：检验归因、自改和过拟合相关近邻。

```text
"MetaGEPA"
"EvoTool" agent attribution
"CHIME" agent memory attribution
"GEPA" "overfitting" "validation"
```

结果处理：本轮未确认“MetaGEPA”的准确论文身份，不据此断言不存在；同名 CHIME 硬件论文排除；第三方博客仅可用于发现线索，未作为核心方法结论依据。使用论文中的引用进行定向追查不等于对全部引文做穷尽筛查。

## 未完成事项

- 尚未独立复现任何方法或近邻文中的失效现象。
- 未审计全部代码、数据许可、任务版本和官方测试执行器；“存在仓库”不等于“在本机可复现”。
- 未确定最接近的最终基线；它依赖于最终选择提示、记忆还是工作流作为更新对象。
- 暂无证据说明所有候选机制需要组合，也无证据支持持续单调改善。

以上限制不阻止当前文献比较，但约束之后的项目命名、创新声明与简历表述。
