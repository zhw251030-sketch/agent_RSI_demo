# 替换充分性 Agent 真实小轮协议

状态：待独立审查；尚未发送真实 MiniMax-M3 请求。

## 研究问题

在固定 MiniMax-M3 权重和一次性候选生成预算下，把编辑证据绑定到“删除损失—替换恢复”
是否能减少有害结构替换的部署次数。证据门只影响是否执行候选，不改变模型权重。

## 数据和任务角色

只读取已经冻结的公开 `train.csv`，不读取 `test_id`、`test_ood` 或封存数据。每个任务使用
此前冻结的 `fit_dev/check_dev/outcome_dev`：

| 任务 | 输入 | 父结构数 | 重复数 | 模型请求 |
|---|---|---:|---:|---:|
| `bactgrow` | `b,s,temp,pH` | 3 | 2 | 6 |
| `stressstrain` | `strain,temp` | 3 | 2 | 6 |

父结构在请求前固定：

- `bactgrow`：`{1,b,s,temp}`、`{1,b,s,pH}`、`{1,b,temp,pH}`；
- `stressstrain`：`{1,strain,temp,strain·temp}`、`{1,strain,temp,strain²}`、
  `{1,strain,temp,temp²}`。

每个父结构发送两个独立的一次性 actor 请求。重复 1 和重复 2 只表示不同请求槽位，不能
事后合并为独立任务样本。模型输入只含父结构、`fit_dev` 反馈和固定编辑契约；模型只能
提交 `feature_ids`，解释文本不进入接受或门控判断。

## 候选、证据和三臂对照

宿主接受候选后只允许两种结构变化：保持父结构，或恰好替换一个 feature。其它变化记录为
结构无效并停止本轮，不补抽、不重试。

对每个单项替换，parent、common 和 added 三个结构使用同一 `fit_dev`、同一初值、同一
优化器和同一 sandbox runtime 拟合；固定参数后只在 `check_dev` 目标自由预测。宿主计算：

\[
I^- = NMSE(common)-NMSE(parent),\quad
I^+ = NMSE(common)-NMSE(added),\quad
R=I^+/I^-.
\]

`I^-≤1e-8`、拟合失败、预测失败或检查目标方差不可用时返回 `unknown` 并保留父结构。
`I^+≤1e-5` 或 `R<1` 返回 `contradicted`；`I^+>1e-5` 且 `R≥1` 返回 `supported`。证据必须
绑定任务、fit/check split data hash、三份源码 hash、删除/加入 feature ID 和拟合协议 hash。

同一候选复制到三个条件：

1. `no_check`：固定认为 supported；
2. `sham_check`：执行相同门控流程，但不读取替换证据；
3. `replacement_check`：读取上述事前证据。

三个条件共享同一模型候选。所有 gate rows 先冻结并哈希，之后才允许在 `outcome_dev` 对
候选做一次 shadow 预测。shadow 结果不能改写 gate 决策或证据状态。

## 预算和停止

- 最多 12 个模型请求，每个 SDK session 最多 1 个请求；`num_retries=0`；
- 每个任务 6 个槽位，每个父结构 2 个重复；不因超时、拒绝或无效候选补抽；
- 真实账本上限为 12 请求、8 元保守预留、最大输出 8192 tokens；
- 第一个 usage unknown、传输失败、协议字段错误或 runtime integrity failure 立即停止，
  保留已完成记录，不恢复同一轮；
- 不更新模型权重、不更新长期策略、不读取 Spanner 和官方封存集。

## 统计单位和报告

主要分析单位是 `task × parent × repeat`；条件行是同一候选的配对记录。报告候选接受率、
结构无效率、父结构保留率、三条件候选执行率、`outcome_dev` 有害率、`prevented_harm`、
漏检数量，以及每个替换的 `I^-`、`I^+`、`R`。这轮最多 12 个槽位，只是两个公开方程上的
机制开发小轮，不能据此宣称跨任务普适性或统计显著性。

真实运行必须使用新的运行目录和新账本；旧 measured-v01/v02、旧基函数轮和本次所有
preflight 记录均不可恢复、补抽或改分。
