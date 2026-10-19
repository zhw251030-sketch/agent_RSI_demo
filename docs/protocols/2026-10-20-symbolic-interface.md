# 符号发现任务：接口与数据验收准备 v0.1

日期：2026-10-20。状态：`proposed-awaiting-data`。本稿完成官方公开源码与数据卡的静态核查，提出接入协议；没有取得受限数据、安装符号侧基线、运行公式搜索或得到实验结果。具体修订机制、方程子集、划分和正式实验参数尚未冻结。

机器可读清单见 [symbolic-phys-osc-v0.1.json](../../configs/tasks/symbolic-phys-osc-v0.1.json)。研究目标沿用[联合设计](../research/planning-symbolic-design-2026-10-17/形式规划与符号发现_联合研究设计_v0.1.md)：基础语言模型权重固定，分别记录公式产物 P 与指导后续修改的策略 S。

## 1. 实际要完成什么任务

拟从 LLM-SRBench 的 LSR-Synth 物理振荡类别 `phys_osc` 起步。输入是变量含义和一组数值观测；Agent 提出能够计算预测值的公式程序，执行器拟合常数并检查误差，再把允许使用的诊断反馈交给 Agent。产物是可执行的公式及其拟合常数，不能把自然语言描述或代码运行成功当成发现正确公式。

例如，该类别加载器给出的默认变量说明包括加速度、位置、时间、速度，但这只是官方默认说明，真实每一道题的变量和列顺序必须由获得的数据核验，不能据此编造任务或方程清单。

选择这一入口，是因为公式可以执行，误差和无效输出可以直接检查，并且存在同分布与分布外观测评价。它还能区分“训练数据上拟合更好”和“恢复了真实结构”。我们要研究的是反馈如何改善后续修订策略；当前尚未确定新机制，也没有证据证明某项策略有效。

## 2. 已核验的来源版本

| 官方来源 | 分支 | 本次核验提交 | 用途 |
|---|---|---|---|
| [LLM-SRBench](https://github.com/deep-symbolic-mathematics/llm-srbench/tree/6fdbe409b75ea749c0a93c69b6861637d804dec4) | main | `6fdbe409b75ea749c0a93c69b6861637d804dec4` | 任务加载与评价接口参照 |
| [LLM-SR](https://github.com/deep-symbolic-mathematics/LLM-SR/tree/41c212312df6c16d936c9cb395356a62774c47e3) | main | `41c212312df6c16d936c9cb395356a62774c47e3` | 公式程序和常数拟合参照 |
| [LaSR 论文实验代码](https://github.com/trishullab/LibraryAugmentedSymbolicRegression.jl/tree/de6b22d5282e7de3432b0d52758a6ec3f583527d) | lasr-experiments | `de6b22d5282e7de3432b0d52758a6ec3f583527d` | 后续概念更新基线的优先复现入口 |
| [LaSR 当前默认分支](https://github.com/trishullab/LibraryAugmentedSymbolicRegression.jl/tree/776196e339191736e20d4eb6eed7c468aa6e4472) | master | `776196e339191736e20d4eb6eed7c468aa6e4472` | 接口差异核查，不能替代上一行的论文实验版本 |

这些提交记录锁定的是“本次看过哪版源码”，不代表已经完成依赖复现或将其全部选为最终实验基线。

## 3. 数据状态与公开字段

[Hugging Face 数据卡](https://huggingface.co/datasets/nnheui/llm-srbench)目前要求登录并同意分享联系信息后才能访问数据文件。本轮没有申请访问或同意该条件，也没有下载受限数据。数据卡声明物理类别有 43 题，这一数字是官方声明，不是本项目已清点的样本数。

公开数据卡列出 `name`、`symbols`、`symbol_descs`、`symbol_properties`；[官方加载器](https://github.com/deep-symbolic-mathematics/llm-srbench/blob/6fdbe409b75ea749c0a93c69b6861637d804dec4/bench/datamodules.py#L70)还读取 `expression` 作为真值。`expression` 必须留在评价端，不能作为 Agent 的输入或反馈。

源码预期类别为 `lsr_synth_phys_osc`，数值文件为 `lsr_bench_data.hdf5`，HDF5 路径为 `/lsr_synth/phys_osc/<problem_name>`。[评价器](https://github.com/deep-symbolic-mathematics/llm-srbench/blob/6fdbe409b75ea749c0a93c69b6861637d804dec4/bench/pipelines.py#L44)按第一列输出、后续列输入的约定切分数组。上述路径和列约定均须在合法取得数据后验收；本稿没有实际文件哈希、数据版本或方程名单，因此清单中的这些值保留为空。

`lsr_synth_phys_osc` 是问题类别，不能当成机制训练集。每题的 train、ID test、OOD test 是观测点层面的划分；若研究策略跨题积累，还需要另外按方程结构或来源族划分机制开发题与最终评价题。

## 4. 接口与可见范围草案

[官方 `SEDTask`](https://github.com/deep-symbolic-mathematics/llm-srbench/blob/6fdbe409b75ea749c0a93c69b6861637d804dec4/bench/dataclasses.py#L24)包含名称、符号、符号描述、符号属性、训练观测和可选描述。`Problem.create_task()`不传递真值公式。官方搜索器入口是 `discover(task: SEDTask) -> list[SearchResult]`。

[LLM-SR 适配器](https://github.com/deep-symbolic-mathematics/llm-srbench/blob/6fdbe409b75ea749c0a93c69b6861637d804dec4/methods/llmsr/searcher.py#L113)根据题目元数据生成函数签名：

```python
def equation(<input arrays from task metadata>, params: np.ndarray) -> np.ndarray:
    ...
```

这是签名示意，不是可直接执行的 Python 代码。输入数组和返回数组都对应同一批观测点；`params` 是可拟合的公式常数，不是语言模型权重。官方模板采用 10 个参数、全 1 初值和 BFGS 最小化训练 MSE；这些是原实现设置，尚未选为本项目共同参数。

| 部分 | 保存什么 | Agent 能使用什么 | 原因 |
|---|---|---|---|
| 公开任务视图 | 任务标识、符号、描述、属性、允许算子 | 经检查的公开元数据 | 让 Agent 知道要拟合什么，不携带真值表达式 |
| 官方 train 内部拟合集 | `X_fit, y_fit` | 常数拟合、执行异常、误差、残差摘要 | 形成可用于修改的执行证据 |
| 官方 train 内部选择集 | `X_select, y_select`，由固定规则划出 | 规定范围内的选择误差和诊断 | 让候选选择不完全依赖其自身拟合误差；仍是开发信息，不能冒充最终留出 |
| 公式产物 P | 程序、拟合常数、父候选 ID、源码哈希 | 当前候选与允许的历史 | 追踪具体改动，区分产物改善与策略改善 |
| 修订策略 S | 策略内容、版本、更新来源 | 当前策略和其允许使用的证据 | 研究后续修订方式是否改善，具体更新规则待定 |
| 隐藏评价端 | 官方 ID/OOD 观测、真值公式、完整评价日志 | 不回流搜索或策略选择 | 防止利用最终答案和最终分数调参 |

公式反馈至少记录解析失败、运行异常、超时、非有限输出、拟合误差、内部选择误差、运行时间、候选数和模型调用数。复杂度和结构恢复的表示、规则及超时政策尚待制定，不能用低误差替代结构恢复。

仅分开目录或写下约定并不构成访问控制。OpenHands 若具有读取隐藏数据目录的权限，隔离仍未实现。正式实验前必须验证 Agent 可见的文件、工具返回及日志；当前本稿只定义边界，没有宣称实现了可靠隔离。

## 5. 静态审查发现的三个接入问题

### 5.1 加载器类与数据键约定不一致，须先验收数据

[`SynProblem`](https://github.com/deep-symbolic-mathematics/llm-srbench/blob/6fdbe409b75ea749c0a93c69b6861637d804dec4/bench/datamodules.py#L49)读取 `train_data / id_test_data / ood_test_data`，但 `BaseSynthDataModule.setup()`第 78 行实际构造普通 `Problem`，后者读取 `train / test / ood_test`。未取得 HDF5 前，不能确定实际文件使用哪套键，也不能断言当前数据一定报错。数据验收时应检查所有目标题的键、形状、数值类型及列映射，再决定适配；不能靠猜测悄悄改键。

### 5.2 官方 stdout 和结果文件包含真值

[`evaluate_problems()`](https://github.com/deep-symbolic-mathematics/llm-srbench/blob/6fdbe409b75ea749c0a93c69b6861637d804dec4/bench/pipelines.py#L85)第 87、90 行打印真值表达式，第 95–115 行还将真值写入结果 JSONL。直接把该脚本输出交给 Agent，或者让 Agent 读取这些文件，会破坏上述边界。后续适配应分开搜索日志和隐藏评价日志，只返回经定义的可见反馈。

### 5.3 官方数值评分丢弃 NaN 点，也不包含结构恢复

[`compute_output_base_metrics()`](https://github.com/deep-symbolic-mathematics/llm-srbench/blob/6fdbe409b75ea749c0a93c69b6861637d804dec4/bench/pipelines.py#L12)计算 MSE、NMSE、R²、Kendall tau、MAPE 和有效点数，NMSE 为 MSE 除以被评价输出的方差。它先删除 NaN 预测对应的点；此路径也没有统一处理 Inf 或零方差分母。部分定义失败的公式可能因此得到看似良好的剩余点误差。

建议项目协议要求完整观测点上的预测均有限，才报告合格的完整数值成绩；覆盖率单独记录，不通过删点把失败候选变成低误差候选。零方差样本应显式标记 NMSE 不可定义，不能无说明地加常数改变指标。若为复现保留原评分，应另列“原实现评分”，说明差异。当前 pipeline 没有结构恢复评分，后续不能把运行它称为完成全部论文评价。

## 6. 独立依赖环境

[LLM-SR 的依赖文件](https://github.com/deep-symbolic-mathematics/LLM-SR/blob/41c212312df6c16d936c9cb395356a62774c47e3/requirements.txt)包含旧版 CUDA PyTorch、transformers、NumPy、SciPy 等；本地模型服务依赖不等于 API 路径必需依赖。LLM-SRBench 自身依赖文件又只有三项，不能覆盖实际导入。后续应分别锁定任务执行环境，不能把所有旧依赖直接装进 OpenHands 环境后就宣称复现完成。

LaSR 论文实验分支使用修改过的 PySR 和 SymbolicRegression.jl；其 [`pysr/juliapkg.json`](https://github.com/trishullab/LibraryAugmentedSymbolicRegression.jl/blob/de6b22d5282e7de3432b0d52758a6ec3f583527d/pysr/juliapkg.json)还包含作者本地绝对路径，安装时必须改成实际检出路径。当前 master 则是不同接口的 Julia 包，不能混用。建议 LaSR 使用独立 Python/Julia 环境，通过明确输入输出与主编排层连接。本轮没有安装这两套符号基线。

## 7. 可以确定与尚待完成的事项

现在可确定本次源码提交、数据集入口、拟采用的类别、接口草案和反馈隔离原则。具体方程 ID、数据 revision、文件 SHA-256、每题观测数、数据键、列映射、结构族及最终划分必须等待取得数据后验收。

验收顺序为：核对实际数据版本与许可范围；只在受控评价端清点元数据和数值结构；检查重复、结构族、缺失值与非有限值；确认官方划分；制定题内选择与题间留出清单；再冻结清单、实现适配并进行不调用模型的评分器检查。数据访问需用户完成或授权相应条件；本稿不代替该步骤。

这项准备的作用是让后续实验能回答“哪些执行证据帮助策略改进”，而不是因数据泄漏、漏算失败点或依赖版本不同产生难以解释的分数。它仍不构成新机制、复现结果或简历中的性能成果。
