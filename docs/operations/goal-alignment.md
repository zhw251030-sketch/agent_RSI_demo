# 任务收益接受规则与后续任务划分

本轮把“什么改进值得接受”实现为可执行的规则，并用全部历史终稿校准；同时固定下一阶段的任务角色。没有新增模型调用、程序执行、公式拟合或持久策略 S 更新。历史首次 S 更新仍保留，本轮只为下一次更新补齐接受接口。

## 为什么做这一步

上一轮的 P-format 检查组把错误的“已修复格式”改成正确的“保持原样”，但程序仍然是 0/10。这说明声明准确与任务改善是两个指标。另一方面，要求 Agent 一定兑现旧编辑承诺也不合理：旧承诺可能是错误或有害的，应允许撤回。

因此，下一次策略学习需要明确四层：任务目标是什么、检查实际支持哪个命题、最终产物是否改善、产生这些产物的新策略是否优于旧策略。仅检查文字或代码改没改，不能替代最后两层。本轮的规则是研究者制定的首版实验约定，不能仅凭这个模块声称研究创新。

## 文件与职责

| 文件 | 做了什么 | 为什么需要 |
|---|---|---|
| [冻结协议](../protocols/2026-10-21-goal-alignment-v0.1.md) | 规定目标、阈值、回放范围和评价边界 | 避免看到结果后临时更换成功定义 |
| [goal_alignment.py](../../rsi_eval/goal_alignment.py) | 实现规划收益、符号收益、删项命题与策略选择四个纯函数 | 把接受规则变成可测试、可重复的判断 |
| [回放配置](../../configs/analysis/goal-alignment-v0.1.json)与[回放脚本](../../scripts/analyze_goal_alignment.py) | 绑定两个完整旧档，逐条读取真实评价并分类 | 不只挑成功例，也不把声明当成绩 |
| [任务角色清单](../../configs/tasks/strategy-partition-v0.1.json) | 逐项保存角色、来源、哈希、重复关系和暴露史 | 预先隔开学习、选策略与最终评价 |
| [strategy_partition.py](../../rsi_eval/strategy_partition.py)与[核验入口](../../scripts/check_strategy_partition.py) | 校验覆盖、互斥、去重与封存；可在服务器核对训练文件 | 避免清单与真实下载文件不一致 |
| [逐例结果](../analysis/2026-10-21-goal-alignment-results.md)与[机器报告](../analysis/2026-10-21-goal-alignment-report.json) | 保存全部24条判断及来源 | 区分旧成绩、新判断和未做的实验 |
| [验收记录](../environment/2026-10-21-goal-alignment-verification.json) | 保存双端测试、报告一致性、原档与代码哈希 | 让本轮工作可以复核 |

## 四个函数如何工作

`assess_planning` 按任务 ID 比较原程序与候选。必须新增至少一个开发成功，同时保持所有原开发/公开成功，才能接受。比如从 5/8 变成 6/8，但丢失原来已解决的一题，也不能通过这一首版保守规则。缺测量与基础设施错误保持未知。此规则是在本轮定义的，不能倒过来改变旧实验的成功数。

`assess_symbolic` 区分精度与简化。NMSE 降低超过 1e-5 可视作精度收益；参数减少且 NMSE 损失小于 1e-5 可视作可接受简化。离阈值不超过 1e-10 时返回未知，避免边界浮点数制造确定结论。参数数目只是复杂度代理；减少参数不等于表达式一定更短，也不证明预测性能提高。

`symbolic_opportunity` 显式写出被检查的命题：`删项NMSE - 原式NMSE > 1e-5`。S-x5 的损失约为 7.18e-7，所以这个命题为假，含义是“没有超过容忍损失”，支持尝试简化；不能把它读作“不能简化”。S-v3 的损失约 0.001513，命题为真，提示避免这次有害删项。probe 只提供尝试依据，最终候选仍需要独立评价。

`select_strategy` 接收原策略、新策略和完整配对终稿。策略内容、共同起点、反馈、任务、模型设置、预算、评价器与重复编号都有绑定。直接比较两个策略的终稿，而非比较各自对起点的“改善”标签。当前约定要求所有配对无退化且确定，并至少一对有收益；两类任务不混成一个总分。没有候选或没有评价时保持未知。同一策略的随机输出变化不算策略更新。

这个函数只检查传入记录的结构与关系，哈希本身不能证明记录真实，也不能证明分配确实事前冻结。未来运行器仍需审计实际请求、评价和冻结时间。本轮对它的测试使用构造数据，尚未把它接入新的真实 S 学习/选择。

## 后续任务如何分开

| 角色 | Spanner 官方训练题 | LLM-SR 方程的 train 数据 |
|---|---|---|
| 学习/组件开发 | seed0，共10题 | oscillator1 |
| 策略选择 | seed1–2 去重后19题 | oscillator2 |
| 后续任务评价 | seed3–9 去重后63题 | bactgrow、stressstrain |
| 排除重复 | 8份后出现的规范化文本副本 | 不适用 |
| 继续封存 | 全部300道 official_test | 四方程的8份 test_id/test_ood |

100份训练题中有92种去除 problem 名称后的文本；按数值 seed/problem 顺序保留首次出现者，因此不会让已知文本副本跨角色。这里只做文本去重，不能排除不同变量名或结构同构等更深重复，也不能声称换实例就是跨规划领域泛化。

oscillator2 在安装验收时已被手写公式评分6次，不能标成完全未见任务。本轮据实把它用于选择，并保存暴露标记。bactgrow 与 stressstrain 没有发现历史候选评分，但曾做数据完整性审计。方程的 train 数据可以用来拟合；在新方程上比较 train 拟合表现，不等于在该方程的独立预测样本上验证泛化。

清单的 `execution_authorized: false` 表示它没有改动旧执行器权限、也不是新的运行协议；它不是重新要求用户授权。本轮仅冻结任务角色，没有生成新程序/公式起点，也没有完整冻结重复次数、请求预算和独立统计单位。

## 如何复核

服务器工作目录：`/home/hanwen/Project/project/agent_RSI_demo`。这几个命令仅离线读取档案或核对文件；输出文件存在且内容不同时会拒绝覆盖。

```bash
python3 -m unittest tests.test_goal_alignment tests.test_goal_alignment_replay tests.test_strategy_partition
python3 scripts/analyze_goal_alignment.py --output tmp/goal-alignment-recheck.json
python3 scripts/check_strategy_partition.py --output tmp/strategy-partition-recheck.json
python3 scripts/check_strategy_partition.py --verify-data --output tmp/strategy-partition-data-recheck.json
```

最后一条仅在有下载数据的服务器运行，读取100份训练 PDDL 和4份训练 CSV 的文件字节；只解析训练 PDDL 名称用于去重，不解码 CSV 数值、不读取封存文件。

## 接下来的研究工作

下一单元应先固定新程序/公式状态的生成方式、来源谱系、模型/工具预算、重复和统计单位；在看评价结果前冻结全部状态。随后接入同预算的固定策略与候选更新策略，在学习任务上产生 S，在选择任务上按本轮接口决定是否接受，最后仅对冻结策略做后续评价。当前四个状态继续作为组件开发反例，不能靠继续增加它们的抽样证明普适性。
