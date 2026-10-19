# 规划任务接口与静态清单：2026-10-20

状态：**pilot-preparation / draft**。本稿明确准备阶段的任务身份、输入输出和反馈边界，不是已冻结的正式实验协议。本轮下载、读取并校验官方文本；没有运行规划程序、VAL、模型或任务依赖，没有安装软件。

配套清单：[planning-spanner-v0.1.json](../../configs/tasks/planning-spanner-v0.1.json)。已有研究动机见[联合设计](../research/planning-symbolic-design-2026-10-17/形式规划与符号发现_联合研究设计_v0.1.md)。

## 1. 为什么选这个确切任务

规划侧暂以 llm-genplan 的 `pg3-spannerlearning` 为准备入口。产物是能处理同域不同实例的完整 Python 规划程序；执行器根据 PDDL 规则检查程序生成的动作序列。它保留了资源获取、动作顺序和目标完成的明确约束，便于研究一次修订究竟修复了什么、是否破坏已有能力。

学术来源是 Silver 等的 *Generalized Planning in PDDL Domains with Pretrained Large Language Models*，正式发表于 [AAAI 2024](https://ojs.aaai.org/index.php/AAAI/article/view/30006)，DOI `10.1609/aaai.v38i18.30006`。本轮核查正式条目的身份、摘要和发表信息；接口结论来自以下固定版本源码，而不是从摘要推断。会议身份支持来源可追溯，不能代替本项目的运行验证，也不能保证当前模型在这些实例上有研究价值。

上游仓库：[tomsilver/llm-genplan](https://github.com/tomsilver/llm-genplan)。2026-10-20 通过 `git ls-remote` 核实默认分支为 **master**，HEAD 为 **`a2b8baa7153d5a8f2df51fbc72c51def80ddc169`**。本稿所有源码链接固定到此提交。

## 2. 文件与划分：明确到编号，保留原测试边界

域文件为 `llm_genplan/envs/assets/pddl/pg3/spannerlearning.pddl`；训练与测试目录分别为 `spannerlearning/seedN/` 和 `spannerlearning_test/seedN/`。完整 Git 树 API 返回 `truncated=false`。实查 seed0–9 各有 10 个训练、30 个测试文件；Spanner 合计 100 个训练、300 个测试文件。三个候选域中的 Miconic、Ferry 树目录也各有相同数量，但本清单只准备 Spanner。

[官方运行脚本，第 3–9 行](https://github.com/tomsilver/llm-genplan/blob/a2b8baa7153d5a8f2df51fbc72c51def80ddc169/scripts/run_all.sh#L3)设置每个种子 2 个提示实例、8 个额外训练实例、30 个测试实例。**PG3 加载器没有对 `Path.glob` 排序**：[envs/__init__.py 的 `_get_pg3_tasks`，第 122–158 行](https://github.com/tomsilver/llm-genplan/blob/a2b8baa7153d5a8f2df51fbc72c51def80ddc169/llm_genplan/envs/__init__.py#L122)。它先从训练目录取前 2 个作为提示，再取后 8 个；不能据此断言不同文件系统都得到 `problem0/1` 这两个提示实例。

本项目准备清单因而显式指定下表，保留官方训练/测试目录边界，同时消除文件枚举顺序的歧义。这是本项目的明确化适配，**不声称已经复原作者缓存中完全相同的 2/8 具体成员或运行顺序**。

| seed0 文件 | 准备角色 | 允许用途 |
|---|---|---|
| 训练目录 `problem0.pddl`、`problem1.pddl` | prompt | 初始化时可见的域内例子 |
| 训练目录 `problem2.pddl`–`problem9.pddl` | development_feedback | 未来单步修订可用的开发执行反馈 |
| 测试目录 `problem0.pddl`–`problem29.pddl` | sealed_evaluation | 独立评价，不能用于修订、策略选择或候选挑选 |
| seed1–9 全部文件 | inventory_not_selected | 只记录来源与重复审计，尚未启用 |

清单收录全部 400 个任务的原始路径、SHA-256、Git blob SHA-1、官方 split 和本项目角色；域文件另列。下载的 401 个 PDDL 文件逐一与官方 Git 树中的 blob SHA-1 核对一致；原始任务内容只保存在上级工作区的临时审查目录，**没有复制进项目仓库**。下载并计算哈希不等于执行测试。这里的 sealed 指对未来候选提出器、更新器和选择过程封存内容与结果，不是声称公开数据从未被任何人访问。

当前没有配置独立的策略选择集。首个准备单元对应“共同父程序、相同可见反馈、一次修订后独立评价”；若随后引入多候选或多策略选择，必须先另定选择集/选择规则，不能悄悄调用上述 30 个测试实例来筛选。

## 3. 重复审计发现及其限制

静态重复检查先将 `(problem <name>)` 的问题名称替换成统一占位符，再比较其余文本。seed0 的 10 个训练、30 个测试文件没有发现这种重复；提示/开发、训练/测试之间也无此重叠。所有种子的训练/测试两侧没有发现这种交叉重复。

但 100 个官方训练文件只有 **92 个去掉问题名后的不同文本**，共 7 个重复组。例子：seed0/problem0 与 seed1/problem4 相同；seed6/problem2 与 seed6/problem5 相同；seed3/problem6、seed5/problem4、seed7/problem9 属于同一组。全部成员和规范化哈希见 JSON 的 `static_audit.all_seed_train_duplicate_groups`。

因此，不能把不同 seed 自动解释为结构独立的任务，也不能仅按 seed 切分后就声称没有任务泄漏。当前 seed0 准备清单未发现这一级别的冲突；后续多种子协议应先处理重复组及相关性。**本轮未完成对象改名、图同构或语义等价去重**；没有文本重复不等于没有相同规划结构。保留官方数据，不在本轮自行删题、补题或改变难度。

## 4. 候选程序的精确接口

上游的 [GeneralizedPlan.run，第 47–61 行](https://github.com/tomsilver/llm-genplan/blob/a2b8baa7153d5a8f2df51fbc72c51def80ddc169/llm_genplan/genplan.py#L47)导入候选 Python 文件并调用：

```python
get_plan(objects, init, goal) -> list[str]
```

| 字段 | Spanner 的实际表示 | 边界 |
|---|---|---|
| `objects` | `set[tuple[str, str]]`，元素为对象名、类型名 | 本域为 typed；不把域文件作为每次函数参数 |
| `init` | `set[tuple[str, ...]]`，元素是谓词名及对象参数 | 当前任务的初始 ground atoms |
| `goal` | 同上 | 当前任务的目标 ground atoms |
| 返回值 | `list[str]`，每项为括号包围的 grounded operator 字符串 | 例如动作名和对象参数；最终以合法性和目标达成为准，不要求匹配某条参考计划 |

解析由 [structs.py 的 Task.objects/init/goal，第 60–75 行](https://github.com/tomsilver/llm-genplan/blob/a2b8baa7153d5a8f2df51fbc72c51def80ddc169/llm_genplan/structs.py#L60)提供。域的动作规则在程序生成提示中可见；实例对象、初始状态和目标在每次执行时作为函数参数可见。

本项目应把**产物 P**（完整程序文件及内容哈希）和**策略 S**（指导后续诊断与修订的文本及版本）分别记录。候选接口不接收测试目录、上游仓库路径、验证器对象、参考解或累计测试分数。测试时给冻结候选当前测试任务的 `objects/init/goal` 是求解所需输入，不代表允许把测试结果回传给更新器。

## 5. 上游实际提供的反馈与拟议适配边界

[genplan.py 的错误枚举及任务执行函数](https://github.com/tomsilver/llm-genplan/blob/a2b8baa7153d5a8f2df51fbc72c51def80ddc169/llm_genplan/genplan.py#L26)记录 `timeout`、`python-exception`、`output-not-plan`、`operator-syntax-invalid`、`operator-semantics-invalid` 五类。成功时返回简短成功信息；调试循环逐个执行训练任务，在首个失败处停止并把错误文本用于下一次修订。

| 情况 | 官方实现中实际可见的信息 | 本项目应保留的区分 |
|---|---|---|
| Python 异常 | 异常和经过部分路径清理的 traceback | 类型与候选代码定位；基础设施异常单独归类 |
| 返回格式错误 | 非列表返回值，或非法动作名/参数个数及提示 | `action_has_valid_syntax` 实际只检查字符串括号、动作名和参数个数，不能仅凭其 docstring 声称已检查对象存在与类型 |
| 计划语义错误 | 返回的动作序列，加 VAL 的 repair advice 或“未达目标”提示 | 非法动作与未达目标可进一步区分，但需新适配器实际解析后验证 |
| 超时 | 执行被中断的说明 | 不应自行猜测为某类规划逻辑错误 |
| 成功 | 成功标记；计划长度、时长等记录 | 成功不证明程序对所有实例都正确 |

默认情况下，错误文本还附带失败任务的 PDDL；开启 `abbreviate_problem_strs` 时会截断对象/事实，开启 `exclude_inputs_in_feedback` 才排除输入。[反馈构建函数，第 265–272 行](https://github.com/tomsilver/llm-genplan/blob/a2b8baa7153d5a8f2df51fbc72c51def80ddc169/llm_genplan/genplan.py#L265)。因此，比较不同反馈丰富度时必须固定任务可见内容、候选数和验证预算；不能将多获得任务信息造成的收益都归于更新机制。

拟议的结构化反馈字段为 `task_id`、`candidate_hash`、`success`、`error_kind`、`plan_length`、`elapsed_seconds`、`public_diagnostic`；`first_invalid_action` 和 `missing_preconditions` 仅在验证器实际产出且适配器已校验时填写，否则为 null。完整执行轨迹并不是已核实的上游默认输出。策略更新器只接收开发任务反馈；选择/最终评价结果由外围评估程序保留。日志中的确定事实与模型给出的原因解释分字段保存，避免把解释当成验证器证据。

## 6. 验证器依赖与执行隔离

上游 [utils.validate_plan，第 67–94 行](https://github.com/tomsilver/llm-genplan/blob/a2b8baa7153d5a8f2df51fbc72c51def80ddc169/llm_genplan/utils.py#L67)调用仓库内 `third_party/val/linux64/Validate`（Linux）或 `darwin/Validate`。官方 Git 树中包含 Linux 的 Validate 与 libVAL.so；本轮只核对路径，没有运行或验证二进制兼容性。PDDL 解析依赖作者的 [PDDLGym fork，pyproject.toml 第 12–22 行](https://github.com/tomsilver/llm-genplan/blob/a2b8baa7153d5a8f2df51fbc72c51def80ddc169/pyproject.toml#L12)。源码依赖没有固定该 fork 的 commit，后续部署需要另外锁版本。

有一个会影响研究判断的实现细节：`validate_plan` 用文本中是否出现 `Plan valid` 判断成功；若没有 repair advice，则统一给出未达目标。若 VAL 无法启动或发生基础设施错误，这样的包装可能将其错误归入规划失败。新适配器必须先检查验证器启动、退出/输出状态，再将真实语义失败交给更新器。

上游候选通过动态 import 执行；`run_genplan_on_task` 使用 `multiprocessing` 和超时中断，**这不构成文件、网络或进程权限的隔离**。未来部署需要让候选执行进程仅获得当次输入和临时可写输出，不能访问凭据、训练/测试数据目录及宿主研究文件；验证器与候选的文件权限也应分开。当前服务器 Docker daemon 权限问题仍未解决，因此本稿不将 OpenHands 的普通本地进程工作区视作上述隔离已成立的证据。

## 7. 下一阶段能据此做什么

这次准备消除了任务版本、数量、文件顺序和反馈来源的主要歧义，形成可检查的接口约定。下一阶段可据此准备执行器，但应先验证 PDDL 解析、VAL 成功/失败/基础设施错误及候选隔离；再开展小规模生成与单步修订，确认是否存在稳定且有意义的失败。模型、预算参数、重复次数、独立选择集以及正式评估协议仍需在运行前确定。当前没有性能、失败率、机制增益或简历实验结果。
