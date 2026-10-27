# SRSD-Feynman Easy-Dummy v05 真实轮结果

## 研究问题

这一轮把 Easy 任务中的输入变量扩展为三个，其中一个变量对真值方程是干扰变量。目标是检查固定模型权重下，外层“绑定证据 + 验证域结果”的替换机制，能否在变量混淆时拒绝有害结构替换。Dummy 轮沿用 Easy 轮的候选协议、三阶单项式执行器、fit/check/outcome 切分、自然域块和 `1e-5` NMSE 容差；只替换公开数据和任务定义。

## 数据与冻结边界

数据来自公开的 [SRSD-Feynman Easy-Dummy 数据集](https://huggingface.co/datasets/yoshitomo-matsubara/srsd-feynman_easy_dummy)。本轮使用 `feynman-i.12.1` 与 `feynman-ii.8.31` 两题，各 8000 行 train、1000 行 val；test 在验证规则冻结前保持未读。`feynman-i.14.4` 的 Dummy 版本有 5 个输入，超出现有三阶单项式执行契约，因此只记录为后续维度扩展，未混入本轮。

train manifest 将每题固定为 4800/1600/1600 的 fit/check/outcome；自然域报告由 fit 子集学习规则，再在 val 上形成 15 个有效域块/题。来源、CSV、行索引、manifest 和 runtime lock 均写入哈希字段。

## 执行与结果

- FakeProvider 预演：4/4 请求接受，12/12 gate 记录，0 次真实模型调用；预演只证明 Dummy 接口与 sandbox 可运行。
- MiniMax-M3 真实轮：4/4 请求接受、4 次真实模型调用、12/12 gate 记录、无重试、usage unknown=0；提示 4390、完成 308、合计 4698 tokens，估算成本 0.0118062 元。
- 候选结构：1 个 `keep`、3 个 `swap_one`；三次 swap 的证据状态均为 `contradicted`，keep 为 `unknown`。
- val 回放：三次 swap 的普通验证 delta 分别为 `+0.330274`、`+0.900709`、`+0.000102129`，15 个域块中只改善 3、1、2 个；四个槽均 `retain_parent`，没有 allow 部署。
- 一次性 test 描述性复核：三次 swap 在 test 上的候选 delta 分别为 `+0.287902`、`+0.911059`、`+0.0000451`；候选有害 3/3 个，实际部署有害 0/4 个，因为验证门没有允许任何替换。

## 能支持的结论

在这两个带干扰变量的外部任务、一次 4 槽真实轮和固定阈值下，证据状态与 val 双门槛共同拒绝了本轮三个有害 swap；这为“机制可以在变量混淆时保持保守”提供了跨任务重复证据。它不支持模型整体变聪明、稳定收益、统计显著性或普适 OOD 泛化；样本只有两题、四个槽，且没有学习模型权重。

## 后续边界

Easy 与 Easy-Dummy 两轮现在都已经有真实外部数据、冻结切分、真实模型轮、验证回放和一次性 test 复核。下一步应增加独立任务族和重复种子，优先处理 5 输入 Dummy 契约扩展；同时保持旧 p04 holdout 不再调参，避免把 test 结果变成训练信号。
