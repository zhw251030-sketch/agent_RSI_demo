# Natural domain outcome v04 coverage 结果

日期：2026-10-26  
机器记录：[2026-10-26-natural-domain-v04.json](../environment/2026-10-26-natural-domain-v04.json)  
性质：train-only 数据覆盖报告；没有模型调用，没有官方 test/test_ood 访问。

本轮从四个训练文件的 `fit_dev_v2` 建立固定输入分组规则，在 `outcome_dev_v2` 的真实训练行上生成自然 domain blocks。低基数输入按精确 level 分组，连续输入按 fit 数据五分位分箱。目标值直接来自对应训练行，避免 synthetic 输入变换后复用原目标造成响应关系错配。

## 覆盖情况

| task | ordinary rows | block 数 | 有效 block | block 行数范围 | 备注 |
|---|---:|---:|---:|---:|---|
| `bactgrow` | 1500 | 20 | 20 | 264–341 | 4 个连续输入各 5 箱 |
| `stressstrain` | 433 | 10 | 10 | 72–113 | strain 五箱、temp 五个自然 level |
| `oscillator1` | 2000 | 10 | 10 | 374–418 | x/v 各 5 箱 |
| `oscillator2` | 2000 | 15 | 15 | 371–431 | t/x/v 各 5 箱 |

所有 block 均超过 32 行，目标方差均为正。stressstrain 的温度 level 被保留为 `0.066666667、0.333333333、0.5、0.833333333、1.0` 五个自然条件层；这为下一轮检验“温度条件变化时替换证据是否稳定”提供了真实训练目标。

## 为什么这比 v03 synthetic fixture 更适合下一轮

v03 的 stressstrain fixture 把温度输入改成均值，但目标仍来自变换前样本，能够检查 gate 是否改变动作，却不能保证输入和目标仍符合任务关系。v04 block 使用训练文件中原本存在的输入—目标配对，每个区域都保留真实目标，因此可以直接比较父/候选结构在普通 outcome 和自然 domain block 上的 paired NMSE。

## 使用边界

该报告只证明数据覆盖和审计条件满足：所有任务都有足够大的自然 blocks，分组规则来自 train-only 输入。它没有运行候选程序，没有比较任何 proposal 的 outcome，也不证明 v04 gate 有效。下一步是用这份报告对 v03 真实 proposal 做双重 outcome replay：普通 outcome 改善且至少 80% 有效 blocks 改善，同时没有 block 发生超过预注册 harm 阈值的退化，才允许恢复执行。
