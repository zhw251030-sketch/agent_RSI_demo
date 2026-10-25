# 替换充分性 holdout 解封协议

状态：已完成两轮 train-only 开发实验，协议待解封；当前未读取任何 `test_id` 或 `test_ood` 文件。

## 解封前固定证据

解封前必须把下面内容固定为只读引用：

1. `2026-10-25-real-v04` 的 `bactgrow/stressstrain` 真实开发轮报告与 gate freeze hash。
2. `2026-10-25-cross-real-v01` 的 `oscillator1/oscillator2` 跨任务开发轮报告与 gate freeze hash。
3. 门阈值 `I^- > 1e-8`、`I^+ > 1e-5`、`R ≥ 1`，以及 `no_check`、`sham_check`、`replacement_check` 三臂定义。
4. 两轮的模型、父结构、split manifest、代码提交和 symbolic runtime lock 哈希。

解封后不再发送新的模型请求，不修改提示词、父结构、阈值、候选、gate 决策或长期策略。holdout 只验证已经冻结的 proposal 在未参与决策的数据上的结果。

## 数据范围

只读取四个任务的官方 `test_id.csv` 和 `test_ood.csv`：`bactgrow`、`stressstrain`、`oscillator1`、`oscillator2`。读取前记录每个文件的路径、字节数、SHA-256、行数和列名；禁止读取其他封存文件或把 test/OOD 样本写入模型请求。

对每个冻结 proposal，parent 和 candidate 的参数都只在该任务对应的 `fit_dev` 上拟合一次；然后用固定参数分别在 `test_id` 和 `test_ood` 上预测。test/OOD 的目标值只进入可信主机评分，不进入拟合、证据门或模型输入。

## 固定的三臂回放

对每个已冻结的 proposal：

- `no_check`：swap proposal 执行 candidate；keep proposal 保留 parent。
- `sham_check`：按相同结构执行流程，但忽略 replacement evidence，作为检查格式对照。
- `replacement_check`：严格复用已冻结 gate 的 `final_action`；supported 才执行 candidate，contradicted/unknown 保留 parent。

三臂使用同一个 proposal、同一组 parent/candidate 源码和同一套 fit 参数。holdout 分数不能回写 gate，也不能产生新的候选。

## 预先登记指标

分别在 `test_id` 和 `test_ood` 报告：

- parent/candidate 的 NMSE 及其差值；
- 每个条件的 candidate 执行数、parent 保留数和部署有害数；
- `prevented_harm`：candidate 在该 holdout 上退化，但 replacement gate 事前保留 parent；
- `retained_benefit`：candidate 在 holdout 上改善，但 replacement gate 保留 parent；
- 任务级计数和四任务合并计数。

“有害”沿用 shadow 层固定容差 `candidate_nmse > parent_nmse + 1e-5`；“改善”对应 `candidate_nmse < parent_nmse - 1e-5`；其余记为持平。所有失败、非有限值和零方差显式报告，不删除分母。

## 结果解释规则

holdout 只能支持描述性结论。若 replacement 条件的部署有害数不高于 no-check，且至少出现一次由事前证据造成的 holdout 有害拦截，则可报告“冻结机制在本次四任务 holdout 上保持安全方向”；若同时出现明显 `retained_benefit`，必须把安全—收益权衡一起报告。无论结果如何，都不能把 24 个 proposal 当作 24 个独立任务、不能据此声称统计显著性，也不能把一次 holdout 结果写成普适性定理。

如果解封前完整性检查失败、任何 test/OOD 文件哈希变化、fit 参数重新优化到 holdout、或 evaluator 读取了目标值后再改变动作，则本轮 holdout 作废，保留两轮开发结果，不补跑。

## 运行顺序

1. 解封前只读检查两个真实轮报告、提交祖先关系和 runtime lock。
2. 生成 holdout 输入清单并冻结文件哈希；此步骤才首次触碰 test/OOD。
3. 用锁定 sandbox 完成 parent/candidate 的 fit_dev 拟合和 test/OOD fixed prediction。
4. 可信主机计算指标，生成机器核验 JSON 和人工解释报告。
5. 只提交安全统计、哈希和报告；原始请求及样本仍留在服务器 ignored 运行目录。
