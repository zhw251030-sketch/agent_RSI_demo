# 替换充分性协议：数据切分与固定参数预测预演

日期：2026-10-24。状态：协议预演完成，尚未调用模型，尚未启动真实机制轮。

## 已完成的工作

服务器上的公开 LLM-SR 训练文件已做只读审计。`bactgrow/train.csv` 有 7,500 行，列为
`b,s,temp,pH,db`，文件 SHA-256 为
`e3c0cc688b4543652360bda708302f1134091fe18c119a2033f204a5826a49da`；`stressstrain/train.csv`
有 2,161 行，列为 `strain,temp,stress`，文件 SHA-256 为
`6b850acb3567b10ccadb0d57cda3d7926297846f30be35ca1bc258b1c135fa73`。两者没有时间列，行序与
输入几乎不相关，因此没有使用连续时间块切分。两个任务的官方 `test_id`、`test_ood` 和封存
文件没有被读取。

切分版本固定为 `replacement-dev-splits-v0.1`。每个任务的训练行按任务、版本和原始 0-based
行号构造 SHA-256 键，在分层内排序后分配。`bactgrow` 按 `db` 十分位分层；`stressstrain`
按 `temp` 水平和 `stress` 十分位分层。比例为 60%/20%/20%，全局计数固定为：

| 任务 | `fit_dev` | `check_dev` | `outcome_dev` | 总行数 |
|---|---:|---:|---:|---:|
| `bactgrow` | 4,500 | 1,500 | 1,500 | 7,500 |
| `stressstrain` | 1,296 | 432 | 433 | 2,161 |

报告中的两个任务都满足全覆盖、零交集；报告 SHA-256 为
`a5f7d994361581fef559c237ee6de993aa3a0c3d33f13f267b070b5cb0797ee8`。每个 split 的 `data_sha256`
同时绑定源文件哈希和行索引。完整行索引和分布审计见
[2026-10-24-replacement-dev-splits.json](../environment/2026-10-24-replacement-dev-splits.json)。

替换证据模块固定使用

\[
I^- = \mathrm{NMSE}(common)-\mathrm{NMSE}(parent),\quad
I^+ = \mathrm{NMSE}(common)-\mathrm{NMSE}(common+added),\quad
R=I^+/I^-.
\]

三种结构都必须只在同一 `fit_dev` 上拟合一次，再把固定参数用于 `check_dev` 目标自由预测。
`I^-` 不足、拟合失败或检查目标方差不可用时返回 `unknown`；替换收益不足或 `R<1` 返回
`contradicted`；只有 `I^->1e-8`、`I^+>1e-5` 且 `R≥1` 才返回 `supported`。父子源码哈希、
删除/加入的 feature ID、检查集哈希、拟合协议和 metric scope 都是必需绑定字段。标准化贡献
只用于诊断，不单独放行。

新增固定参数预测预演只公布 `phase=predict`、输入、任务、参数和 `check_dev` 哈希，不发送
目标值；宿主重新计算 population-variance NMSE。假 runner 测试确认目标字段被删除、失败不被
伪装成分数、非 `check_dev` 在调用前拒绝。

## 验证与边界

本机针对切分、证据判定、固定参数预测和三结构 runner 的 19 项测试全部通过；服务器用同一版本脚本重新生成
报告，任务源文件哈希、切分计数、split data 哈希和 manifest 哈希逐项相同。随后服务器使用
锁定的 Linux sandbox 完成了两个任务的研究者固定三结构预演：每个任务 3 次 fit 和 3 次
fixed-parameter predict 全部成功，阶段顺序和目标隔离通过，预演状态为 `passed`。详细证书见
[三结构 sandbox 预演](../environment/2026-10-24-replacement-triplet-preflight.json)。服务器实验 `.venv` 未安装
`pytest`，因此服务器本轮只执行了标准库切分生成和哈希核验；本机测试结果不冒充服务器测试。

预演中 `bactgrow` 的 `R=1.6170707×10⁻⁵`，`stressstrain` 的 `R=0.9814562`，两者均按
`R≥1` 规则返回 `contradicted`。这些结构、删除项和加入项都是研究者预先固定的执行夹具，
没有模型生成或候选选择，因此这些数值只说明 fit/predict/host-score 链路工作，不是 Agent
机制结果，也不说明某个方程的真实替换规律。

这一步只证明数据边界、数值判定和请求形状可复核。它没有证明 replacement check 能降低
有害编辑率，也没有产生任何模型调用或任务成绩。

## 下一步

下一步把固定参数预测接入新增的三结构 runner：父结构、公共结构和替换结构共用 `fit_dev`
与初始化/优化器设置，随后只在 `check_dev` 产生事前证据。先用假 provider 完整预演三条件
门控、冻结哈希和 `outcome_dev` shadow 顺序，再由独立审查确认协议后启动两个任务的真实
MiniMax-M3 小轮。任何真实结果都单独建档，不能回写本次切分或阈值。
