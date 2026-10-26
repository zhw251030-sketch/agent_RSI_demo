# p04 独立开发轮与 v03/v04 回放结果

日期：2026-10-26  
状态：真实开发轮和两种 train-only 回放均完成；没有读取官方 `test_id/test_ood`。

## 真实开发轮

本轮使用四个经过历史审计的全新 task-specific p04 parent，每个 parent 两次一次性 MiniMax-M3 请求，共 8 个槽位。真实轮固定使用 OpenHands SDK 1.55.1、symbolic runtime lock、`shift-aware-dev-v02` split manifest 和 natural-domain v04 报告；每槽最多一次请求，禁止重试。

- 请求/接受：8/8；gate rows：24/24；真实模型调用：8；失败/重试：0/0；
- proposal：5 个 `swap_one`、3 个 `keep`；
- evidence：2 `supported`、1 `contradicted`、5 `unknown`；
- 总用量：9,396 tokens（prompt 8,604、completion 792），估算 0.0247212 元；usage unknown=0；
- 官方 `test_id`/`test_ood`：均未读取；自然域报告在真实 actor 轮中未读取；
- 四个 p04 parent 的 `(task_id, source_sha256)` 均未与14个历史 round summary 冲突。

四个 parent 的源哈希如下。stressstrain 和 oscillator1 的二维公式源码哈希相同，但任务输入映射不同，所以审计按 task_id 绑定，没有把它们误判为冲突：

| task | parent | source SHA-256 |
|---|---|---|
| bactgrow | `bactgrow-p04` | `5566e3ca1987b893de9759c8dc54bb86d36fcaefe15037c4377b4d19b7d3ff4f` |
| stressstrain | `stressstrain-p04` | `92982a64ffea987111eb600549cbe8424ccd17781587f96f5556099fe28926ae` |
| oscillator1 | `oscillator1-p04` | `92982a64ffea987111eb600549cbe8424ccd17781587f96f5556099fe28926ae` |
| oscillator2 | `oscillator2-p04` | `80684972645ca4b46d9a9629cf5f86413750fe33ebb365540b979e0de263883a` |

真实轮机器摘要保存在服务器运行目录 `runs/replacement-natural-domain-v04-p04/2026-10-26-natural-domain-v04-p04-real-v01/summary.json`，其 round summary 哈希为 `bebe24ea734202746d5cc7c841cb5433f2954eae7f9069945a0938574d77c049`。

## v03 synthetic outcome 回放

在 proposal 和 evidence 冻结后，先用已有 v03 synthetic outcome gate 回放；此步骤没有新的模型请求，26 次 sandbox。它使用输入变换后的 train proxy，并复用原训练目标，因此只是动作诊断，不能当作 OOD 结果。

- 8 个 proposal 中 4 个在 synthetic proxy 上退化；
- old replacement action 会部署 1 个 proxy harmful；
- v02 hard shift 和 v03 outcome gate 最终都部署 0 个 proxy harmful；
- v03 决策为 1 `allow_after_validation`、2 `retain`、5 `defer`；
- 相比 v02，v03 改变 1 个动作，新增阻断相对旧 action 为 1 个。

这说明 v03 的 evidence/shift/outcome 接线在 p04 proposal 上可运行，但 synthetic proxy 中的退化来自输入变换与原目标复用的组合，不能与自然域结果直接比较成“性能提升”。

## v04 natural-domain outcome 回放

随后用同一批冻结 proposal 运行 v04 natural-domain dual gate，139 次 sandbox、0 模型请求。数值来自真实 `outcome_dev_v2` 目标和预先冻结的自然域块；没有读取官方测试。

- 5 个 swap proposal 的 ordinary outcome 均改善，因此 `natural_ordinary_harmful=0`；
- v04 决策为 2 `defer`、6 `retain`，没有 `allow_after_dual_validation`；
- v03→v04 只有 1 个动作变化：`oscillator1-p04-r2` 从 execute 改为 retain；
- `oscillator1-p04-r2` 普通 ΔNMSE=-0.0003098，但只有 7/10 个自然块改善，最大块退化约 +0.002292；
- `oscillator2-p04-r1` 普通 ΔNMSE=-0.0049053，但只有 10/15 个自然块改善，最大块退化约 +0.233194；
- `bactgrow-p04-r1/r2` 因 evidence=unknown 延迟，`stressstrain-p04-r2` 因 evidence=contradicted 保留，三个 keep 不进入数值放行。

因此 v04 在这一批上表现为“局部一致性过滤器”：它拒绝整体平均改善但区域表现不一致的两个 supported candidate。由于这 8 个槽位属于同一个新开发批，且自然域块按特征分组、彼此可能重叠，不能把 10/15 或 7/10 当作独立重复样本，也不能据此估计泛化概率。

## 结论边界和后续

本轮完成了 p04 父结构的新颖性审计、真实 proposal 生成、v03 synthetic 回放和 v04 natural-domain 回放。它支持的窄结论是：在固定模型权重下，host-side gate 可以把“普通 outcome 改善”与“自然输入区域一致改善”分开，并在区域不一致时保留父结构。

本轮没有官方 holdout 结果，不能称为 OOD 收益、独立分布泛化、稳定优势或统计显著。下一步应冻结 p04 全部记录，先做任务×parent×repeat 的失败原因审查，再决定是否设计新的 p05 或正式预注册 holdout；不能根据本轮 train-only 数值回调 `1e-5`、32 行或全块通过规则。
