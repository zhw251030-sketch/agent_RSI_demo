# Shift-aware replacement gate v02 设计

日期：2026-10-26  
状态：设计冻结前草案；尚未启动模型调用，也没有读取新的封存数据。

## 研究问题

当前 `replacement_check` 能够用 `fit_dev/check_dev` 上的删除损失和替换恢复比判断局部结构证据，但最终 holdout 表明，开发域中 `supported` 的证据在 OOD 域可能失效。v02 研究的问题是：

> 在基础模型权重固定、候选结构仍由 Agent 提交的条件下，给替换证据增加显式的输入适用域判断，能否减少“开发域 supported、OOD 退化”的错误部署？

本问题专门针对本轮审查得到的 `evidence transport failure`，不把 holdout 结果重新用于调阈值。

## 机制分解

保留现有三臂作为消融基线：

1. `no_check`：swap 直接执行；
2. `replacement_check`：沿用已冻结的 `I- > 1e-8`、`I+ > 1e-5`、`R >= 1`；
3. `replacement+shift_gate`：只有 replacement evidence 为 `supported` 且输入覆盖度通过时才执行，否则保留父结构。

新增的 `shift_gate` 由可信宿主计算，不读取目标标签，也不调用模型。它只使用用于本轮决策的输入批次和此前冻结的参考输入分布。候选结构、模型解释和 holdout 目标值不能参与 shift 判定。

## 预登记的 shift 指标

在新的开发轮中，从 `fit_dev_v2` 建立每个输入维度的参考分布，并在决策批次上计算：

- **范围覆盖**：参考分布的 1%–99% 稳健区间外样本比例；
- **标准化均值偏移**：以 fit_dev_v2 的标准差加下限 `1e-12` 标准化；
- **方差比**：决策批次方差与参考方差之比；
- **条件覆盖**：对离散条件变量记录出现的 level 是否在参考批次中出现。

v02 的首个实现只负责产生结构化诊断，不直接在本轮 holdout 上选择阈值。阈值必须在新的开发数据中预先登记，并由 synthetic shift 开发切分进行校准。默认候选规则是：任一输入维度出现明显范围外比例、标准化均值偏移或条件 level 缺失时，状态记为 `shifted`；`shifted` 时 `replacement+shift_gate` 保留父结构。

## 新开发数据

从公开训练文件重新构造、只使用训练数据：

- `fit_dev_v2`：拟合参数与参考输入分布；
- `check_dev_v2`：验证 replacement evidence；
- `synthetic_shift_dev`：只模拟输入域变化，不读取官方 test/OOD 标签；
- `outcome_dev_v2`：在 gate 冻结后测量候选结果。

synthetic shift 至少包含三种可解释变化：连续变量尾部外推、条件变量 level 切换、时间窗口切换。每种变化都要记录生成规则、行索引哈希和数据源哈希，不能通过随机抽样事后挑选。

## 评价指标

每个条件和每种 shift 类型报告：

- `deployed_harmful` 与 `prevented_harm`；
- `retained_benefit`，即保留父结构而放弃潜在收益的次数；
- shift detector 的覆盖率、误报率和漏报率；
- `supported/shifted` 的混淆矩阵；
- 任务级和 shift 类型级结果，不把重复 proposal 当作独立任务样本。

重点比较的是 `replacement_check` 与 `replacement+shift_gate` 的差异。如果新增 gate 只是把所有候选都拒绝，风险下降不构成机制成功，必须同时报告收益保留代价和候选执行覆盖率。

## 防止泄漏的执行顺序

1. 先冻结 v02 代码、参考分布定义、synthetic shift 生成规则和阈值候选；
2. 只读取训练文件，生成新的 split manifest 和哈希；
3. 运行无模型的 shift 指标单元测试和 fake-agent 预演；
4. 在真实 Agent 请求前冻结父结构、三臂条件和分析脚本；
5. 完成真实开发轮后再读取 `outcome_dev_v2`；
6. 如果开发结果支持机制，再另行预注册新的官方 holdout；本轮已解封的 `test_id/test_ood` 不得参与 v02 调参。

## 预期结果与边界

若 `replacement+shift_gate` 能在 synthetic shift 和新的开发任务上减少错误部署，同时没有把所有 proposal 变成 `retain_parent`，可认为它解决了当前审查发现的一个明确窄问题：为 replacement evidence 添加适用域信息。即使成功，也只能支持“shift-aware gate 在预先登记的 shift 类型上有效”，不能直接推出普适 Agent 自我改进能力。

