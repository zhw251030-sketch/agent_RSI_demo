# 替换充分性最终 holdout 结果

日期：2026-10-26  
服务器运行目录：`/home/hanwen/Project/project/agent_RSI_demo`  
运行目录：`runs/replacement-holdout/2026-10-25-final-v01`  
评估器：`scripts/run_replacement_holdout.py --release-holdout`  
模型调用：0；基础模型权重固定。

## 轮次定位

本轮是开发阶段冻结后的只读 holdout 回放。两轮开发实验的 24 个 proposal、父结构、候选结构、gate action、阈值和 fit 参数来源在读取官方测试文件前已经固定；评估器没有重新询问模型，也没有改写 gate、候选或权重。`--release-holdout` 是本次第一次打开官方 `test_id.csv` 与 `test_ood.csv` 的显式开关，因此本轮结束了项目的盲测待解封阶段。

评估器只在每个任务的 `fit_dev` 上拟合父结构和候选结构的参数，再以固定参数预测官方 `test_id`/`test_ood`。三种条件重放同一批冻结 proposal：

- `no_check`：直接执行模型候选；
- `sham_check`：执行不包含替换证据的对照检查；
- `replacement_check`：仅在事前替换充分性证据支持时执行候选，否则保留父结构。

有害结果定义为候选 NMSE 比父结构高出至少 `1e-5`；有利结果定义为候选 NMSE 比父结构降低至少 `1e-5`。所有数值均来自 holdout 预测，决策动作来自解封前冻结的 gate 记录。

## 完整性与数据指纹

- `status=passed_holdout_read`，24/24 proposal 进入回放，144 条记录（24 proposal × 3 条件 × 2 个 split）。
- 没有模型请求、重试、候选重新生成、阈值调整、权重更新或策略更新。
- 结果文件 `summary.json` SHA-256：`3df7b6dc424f022af0b611f79c306f654f46ca2733d1df142bc15dea8ee4a160`。
- holdout 文件共 8 个；`test_id` 总计 23,942 行，`test_ood` 总计 35,738 行，合计 59,680 行。文件字节数和 SHA-256 已写入机器核验 JSON。

| 任务 | test_id 行数 | test_ood 行数 | 输入列 | 备注 |
|---|---:|---:|---|---|
| `bactgrow` | 2,500 | 15,000 | `b,s,temp,pH,db` | 生长动力学数值回归 |
| `stressstrain` | 1,442 | 738 | `strain,temp,stress` | 应力应变数值回归 |
| `oscillator1` | 10,000 | 10,000 | `x,v,a` | 二状态振子 |
| `oscillator2` | 10,000 | 10,000 | `t,x,v,a` | 三输入振子 |

## 汇总结果

| 条件 / split | proposals | 候选执行 | 保留父结构 | 部署有害 | 拦截有害 | 保守拒绝潜在有利 |
|---|---:|---:|---:|---:|---:|---:|
| `no_check / test_id` | 24 | 18 | 6 | 7 | 0 | 0 |
| `sham_check / test_id` | 24 | 18 | 6 | 7 | 0 | 0 |
| `replacement_check / test_id` | 24 | 8 | 16 | 0 | 7 | 3 |
| `no_check / test_ood` | 24 | 18 | 6 | 9 | 0 | 0 |
| `sham_check / test_ood` | 24 | 18 | 6 | 9 | 0 | 0 |
| `replacement_check / test_ood` | 24 | 8 | 16 | 4 | 5 | 5 |

`no_check` 与 `sham_check` 在两套 split 上完全一致，说明本轮的差异主要来自是否绑定具体替换证据，而不是增加一个没有替换语义的检查步骤。

在 ID holdout 上，绑定替换证据的条件把部署有害数从 7 降到 0，拦截 7 个有害候选；同时有 3 个在 holdout 上本可带来收益的候选被保守地拒绝，系统保留了父结构，说明风险控制有明确代价，不能只报告风险下降。在 OOD holdout 上，部署有害数从 9 降到 4，拦截 5 个，但仍有 4 个有害候选被允许执行；另有 5 个潜在有利候选被保守拒绝。这个结果显示机制有跨分布保护信号，但证据并不充分支持完全可靠的 OOD 泛化。

## 按任务的结果

| 任务 / split | `no_check` 部署有害 | `replacement_check` 部署有害 | 拦截有害 | 保守拒绝潜在有利 |
|---|---:|---:|---:|---:|
| `bactgrow / test_id` | 4 | 0 | 4 | 0 |
| `bactgrow / test_ood` | 2 | 1 | 1 | 3 |
| `stressstrain / test_id` | 1 | 0 | 1 | 0 |
| `stressstrain / test_ood` | 2 | 2 | 0 | 1 |
| `oscillator1 / test_id` | 1 | 0 | 1 | 0 |
| `oscillator1 / test_ood` | 1 | 0 | 1 | 0 |
| `oscillator2 / test_id` | 1 | 0 | 1 | 3 |
| `oscillator2 / test_ood` | 4 | 1 | 3 | 1 |

其中 `stressstrain / test_ood` 的 2 个有害候选均未被拦截，`oscillator2 / test_ood` 仍有 1 个有害候选部署；这两处是后续机制改进应优先分析的失败案例。它们不能被隐藏在总平均中，因为本项目关心的是“证据何时足以阻止错误修订”。

## 结论边界

本轮支持以下较窄的结论：在四个公开数值任务的冻结 proposal 回放中，把替换证据绑定到具体结构并在证据不足时保留父结构，能够减少部署有害候选；在本次 ID holdout 上为 7/7，在 OOD holdout 上为 5/9 的有害候选被阻止。`sham_check` 与 `no_check` 的一致结果进一步支持差异来自替换相关证据，而不是任意检查文本。

本轮不支持以下更强结论：不能称为统计显著、稳定普适、对所有 OOD 有效、完全避免退化或已经形成可部署 Agent。24 个 proposal 来自项目既有的四个任务，重复 proposal 不是独立任务样本；候选仍由同一个 MiniMax-M3 生成；holdout 只是一次冻结回放，没有重新抽取任务或做多模型复现；结果也没有经过正式置信区间或功效分析。因此简历或面试中应描述为“完成冻结机制的 ID/OOD holdout 验证，观察到风险拦截信号并定位 OOD 失败模式”，不要写成“泛化性能提升 X%”。

## 后续工作

1. 对 `stressstrain/test_ood` 和 `oscillator2/test_ood` 的未拦截失败逐条回溯：比较 fit/check 与 OOD 的删除损失、替换恢复比、系数规模和特征分布漂移。
2. 在不读取更多官方测试标签的前提下，设计下一版证据门：例如增加分布漂移/不确定性状态，或将 unknown 与 contradicted 分开处理；先在新的开发切分上验证，再预注册下一轮 holdout。
3. 若要把结果升级为论文级结论，需要增加未参与设计的新任务、新模型或多次独立重复，并预先登记统计分析，而不是用本轮 24 个 proposal 的结果替代独立样本。

