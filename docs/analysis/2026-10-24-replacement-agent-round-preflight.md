# 替换充分性 12 槽 Agent runner 预演报告

日期：2026-10-24  
运行目录：服务器 `runs/replacement-agent-round/2026-10-24-v03/`  
代码提交：`6949f868aa4099f53bd0eaaf53c2cfd0b1f31f55`  
状态：fake-provider + Linux sandbox 预演通过；新的真实 MiniMax 轮尚未启动。

## 这一步做什么

本预演验证的是“正式 12 槽实验能否按照协议完整执行”，不是验证 replacement evidence 是否已经改善模型行为。FakeProvider 为每个槽位返回预先构造的 feature ID，OpenHands SDK、请求账本、候选编译、Linux bubblewrap sandbox、三结构拟合、固定参数预测、三条件 gate 和 `outcome_dev` shadow 都使用正式路径。

这样拆开有两个目的：模型因素不会掩盖工程错误；即使 synthetic 候选产生了有害或有益分数，也不会被误写成 MiniMax 的机制结果。

## 执行顺序与证据

1. runner 读取冻结的 `bactgrow/train.csv` 和 `stressstrain/train.csv`，重新核对源文件哈希、manifest 哈希、每个 split 的行索引哈希和数据哈希，并确认三个 split 是不重叠的完整分区。
2. 对每个固定父结构，先在 `fit_dev` 拟合父结构并生成只含 `fit_dev` 指标的 actor packet。packet 不含 `check_dev` 或 `outcome_dev` 的原始行和目标。
3. 每个父结构发送两个一次性 actor session。SDK 只公布 `submit_basis(feature_ids)`，每个 session 最多一次模型请求，FakeProvider 的 12 个响应全部 usage known。
4. 合法候选被规范化为编译器的 canonical feature order，然后只允许 keep 或恰好一次 feature swap。规范化修复了 v01 暴露的顺序问题：actor 的原始列表顺序不再把同一 keep 误判为结构编辑。
5. 对 swap 候选，parent/common/added 在同一 `fit_dev` 和同一锁定 sandbox 中拟合；三个参数向量冻结后，`check_dev` prediction 请求不含 `y`，宿主再计算 `I^-`、`I^+`、`R`。事前证据绑定三份源码哈希、两个 split hash 和拟合协议 hash。
6. 每个候选复制到 `no_check`、`sham_check`、`replacement_check`。36 条 gate row 全部写入后生成 freeze hash；只有这一步成功后，runner 才调用 `outcome_dev` fixed prediction adapter。
7. shadow outcome 只附加到冻结 gate，不能反向改变执行决定。fake 运行的候选和 outcome 是合成 provider/研究者固定的工程夹具，不计作真实研究调用。

## 机器结果

| 检查项 | 结果 |
| --- | ---: |
| OpenHands SDK | 1.55.1 |
| actor 请求 | 12/12 |
| gate rows | 36/36 |
| usage unknown | 0 |
| sandbox runtime | 通过 runtime lock 和 Linux bubblewrap |
| `outcome_dev` 读取 | gate freeze 后执行 |
| 真实 MiniMax 请求 | 0 |
| 实际 synthetic tokens | 1,440 |
| 实际估算费用 | 0.004536 元 |
| 最大保守预留 | 1.0864896 元 |

冻结条件顺序为 `no_check`、`sham_check`、`replacement_check`，freeze hash 为
`fae3beab238314e52dfcea3dc2c3800298929f6f81b34fa917129b5f59b61890`。

合成 shadow 的配对结果如下：

| 条件 | 执行候选 | 保留父结构 | 合成有害候选 | 阻止有害候选 |
| --- | ---: | ---: | ---: | ---: |
| `no_check` | 6 | 6 | 3 | 0 |
| `sham_check` | 6 | 6 | 3 | 0 |
| `replacement_check` | 2 | 10 | 3 | 3 |

这组数字验证了三条件 gate 能在同一候选上产生不同执行决策，并验证 `prevented_harm` 的计算和报告字段；因为候选是 synthetic，不能据此推断 MiniMax 真实候选会被同样阻止。

## 中途失败及修复

v01 在第一个 slot 停止：SDK action 已接受，账本也已结算，但 actor 返回的 feature ID 顺序与 compiler canonical order 不同，宿主的 keep edit binding 因列表顺序差异拒绝。v01 没有重试或补抽，完整保留在服务器，未被覆盖。

修复后 v02 完成 12 槽；随后又增加了源哈希、行索引哈希、runtime lock 和代码提交绑定，v03 重新从空目录执行并通过。因代码和证书发生变化，v02 不被用作 real-mode 授权证书，v03 才是当前证书。

## 结论边界

当前完成的是可重复的实验基础设施验收：数据边界、SDK 单步约束、三结构证据、门冻结和 outcome shadow 的顺序都能在服务器真实运行。它没有产生真实 MiniMax 候选，也没有证明 replacement evidence 在两个任务上减少有害编辑。

v03 证书与当前服务器工作树/运行时的一致性检查已通过。下一步是在用户已授权的预算内启动 12 个真实 MiniMax-M3 请求。真实轮仍须按首个未知 usage、传输失败、协议错误或 runtime hash 变化立即停止；无效候选不补抽，结果只解释为两个公开方程上的机制开发小轮。

