# SRSD-Feynman Easy-Dummy i.14.4 v02 真实轮结果

## 目的

本轮把固定权重 Agent 的“候选结构编辑—证据检查—数值执行—保守部署”机制扩展到五输入任务。任务来自公开的 [SRSD-Feynman Easy-Dummy 数据卡](https://huggingface.co/datasets/yoshitomo-matsubara/srsd-feynman_easy_dummy)；SRSD-Feynman 数据集及其基准设计见 [DMLR 论文](https://mlanthology.org/dmlr/2024/matsubara2024dmlr-rethinking/)。本轮关注机制链路和失败处理，不是官方 leaderboard 结果。

## 为什么单独做 v02

v01 只允许已有的一至四输入基函数协议。本轮 i.14.4 使用五个输入，因此新增独立的 `symbolic_basis_v02` 契约：三阶以内五变量单项式目录、规范排序、最多 16 项、宿主注入解释字段。v01 的编译器、提示和历史运行没有改写；这样可以把“输入维度扩展”与“机制效果”分开审计。

任务冻结为 8000 条 train、1000 条 val 和公开 test；开发集继续按 fit/check/outcome 固定切分，验证域为 25 个有效自然分块。父模型含 6 个特征，两个真实重复槽位各给 Agent 一次候选编辑机会。FakeProvider 先完成 2/2 请求、6/6 gate、0 次真实调用，之后才发送真实请求。

## 真实执行

真实 MiniMax-M3 请求为 2/2 接受、2 次真实调用、6/6 gate，未发生重试。两个候选都保持 6 项结构，但分别把父模型的 `m_1_0_0_0_0` 换成 `m_0_0_0_0_2` 或 `m_0_0_0_1_1`。候选经过 v02 编译器和宿主生成解释后才进入执行器；模型解释只归档，不参与业务协议。

## 验证集结果

父模型两次拟合均成功，父模型普通验证 NMSE 为 `0.8898143297`。两个候选都结构合法，但没有形成可用的数值参数：第一个在第 6 行触发 `ValueError`，第二个在 100 次函数评估后达到优化器上限。回放器将这类失败记录为 `candidate_fit_failed`，而不是把整个实验标成接口错误。

| 槽位 | 候选拟合 | 证据状态 | 验证动作 |
| --- | --- | --- | --- |
| `p01-r1` | `ValueError`，8 次候选调用 | unknown | `retain_parent` |
| `p01-r2` | 优化器达到上限，472 次候选调用 | unknown | `retain_parent` |

因此候选 NMSE 和普通验证增量均不可用，允许部署数为 `0/2`。这一结果说明结构契约通过并不等于候选可数值拟合；失败候选会在验证阶段被安全拒绝。

## 一次性 test 留出复核

验证动作冻结后才读取官方 test。父模型 test NMSE 为 `0.8387557647`；两个候选仍无法拟合，因此没有候选 test NMSE。两次部署都使用父模型，部署有害数为 `0/2`，候选有害计数为 `0`（表示候选没有可评分参数，不表示候选优于父模型）。

## 结论边界

本轮完成了五输入 v02 协议从真实请求、候选编译、数值拟合、验证拒绝到留出复核的闭环，并捕获了两种不同的数值失败模式。它支持“对不可拟合候选保持父模型”的安全行为，不支持 v02 相比 v01 的性能优势、跨任务泛化或统计显著性结论。下一步应在不改变本轮冻结结果的前提下，先做无模型数值缩放/条件数诊断，再选择经过校准的新五输入候选，避免直接把优化器失败误写成机制收益。

## 证据文件

- `docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-source.json`
- `docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-dev-v05.json`
- `docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-v05-preflight.json`
- `docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-val-replay-real-v03.json`
- `docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-test-holdout-real-v01.json`
