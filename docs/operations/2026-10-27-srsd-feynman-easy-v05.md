# SRSD-Feynman Easy 外部开发包与 Fake 预演

## 目的

p04 冻结后，现有四个 LLM-SR 任务的官方 `test_id/test_ood` 已经做过一次只读回放，不能再用同一批 holdout 调整机制。这个阶段引入一个来源独立、可公开下载、带真值方程的外部开发包，先检查现有“候选结构—fit/check 证据—门控—outcome”链路是否能迁移。

## 数据来源

数据来自 SRSD-Feynman Easy 数据卡：

`https://huggingface.co/datasets/yoshitomo-matsubara/srsd-feynman_easy`

数据卡标记为 CC-BY-4.0，并提供 `train/val/test` 和 `supp_info.json`。本轮选择三道方程：

| task_id | 原始题号 | 真值方程 | 选择理由 |
| --- | --- | --- | --- |
| `srsd-feynman-i12-1` | `feynman-i.12.1` | `x0*x1` | 二输入乘积，属于现有字典 |
| `srsd-feynman-i14-4` | `feynman-i.14.4` | `0.5*x0*x1**2` | 三阶单项式，检验结构替换 |
| `srsd-feynman-ii8-31` | `feynman-ii.8.31` | `4.427e-12*x0**2` | 单输入二次项，检验低维情况 |

所有题目均能由当前 `symbolic-basis-v0.1` 的 1–4 输入、总次数不超过 3 的单项式字典表示。这样第一轮只改变数据域，不同时改变执行语言。

## 下载与冻结

`scripts/fetch_srsd_easy.py` 下载 `supp_info.json`、三题的 train/val 数值文件，并将空格分隔数据转换为带 `x0,...,y` 表头的 CSV。默认只读取 train/val；test 只登记 URL，必须显式传入 `--include-test` 才能读取。

`scripts/build_srsd_easy_dev_v05.py` 对 train CSV 调用通用切分器，按目标分位数确定性地划分为 60% fit、20% check、20% outcome。每份清单同时绑定原始 CSV SHA-256、行索引 SHA-256、切分数据 SHA-256 和 manifest SHA-256，并写入 `official_test_read=false`。

## Fake 预演

`scripts/run_srsd_external_v05_preflight.py` 使用真实 OpenHands SDK 1.55.1、真实 Linux sandbox 和固定 FakeProvider：

1. 从清单重载三题并重新核对 CSV 哈希；
2. 为每题的一个新 parent 发送两次一次性 actor 请求（一次 keep，一次单项替换）；
3. 运行 fit/check、三条件 gate 和 outcome 访问顺序；
4. 将请求数、接受数、gate 数、代码提交、runtime lock 和数据清单哈希写入证书。

服务器结果为 6/6 接受、18/18 gate、0 个真实模型调用。该证书只证明协议和数据接线，不能当作机制收益。

## 下一步

先在不读取 test 的前提下，为 val 建立自然域块规则并完成 model-free replay；然后固定规则和代码提交，才允许启动一次性 MiniMax 真实轮。真实轮之后再冻结 gate action，最后一次性读取 SRSD test 作为外部描述性评估。
