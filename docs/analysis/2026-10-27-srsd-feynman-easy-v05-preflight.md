# SRSD-Feynman Easy 外部接入阶段结果

## 已完成的可验证事实

- 公开数据源可访问，许可证、题目元数据和真值方程保存于 `docs/environment/2026-10-27-srsd-feynman-easy-source.json`。
- 三题各有 8000 行 train、1000 行 val；test 文件只记录公开下载 URL，清单和运行证书均为 `official_test_read=false`。
- 本地和服务器生成的 train CSV SHA-256 相同：
  - `srsd-feynman-i12-1`: `889bb909e8a7...`
  - `srsd-feynman-i14-4`: `f084fdadb809...`
  - `srsd-feynman-ii8-31`: `20b90401a6e5...`
- 三题的 train-only split 均为 4800/1600/1600（fit/check/outcome），`load_frozen_tasks` 在服务器成功重载。
- FakeProvider 预演使用 6 个 SDK 请求，全部接受；18 条 gate 记录生成；没有真实 MiniMax 调用。

## 为什么此阶段不报告“模型效果”

FakeProvider 的候选是预先写入的结构 ID，不能代表模型提出了什么；sandbox 分数只验证输入、编译、拟合和哈希绑定。预演也没有读取 val/test 来选择阈值，因此不能声称外部任务上的准确率、机制收益或泛化。

## 当前证据边界

这一步解决的是 p04 冻结后缺少新公开任务的问题，以及外部 CSV 是否能无歧义进入现有证据门控的问题。它尚未解决三件事：

1. MiniMax 在新任务上是否会提出可执行且有意义的结构修改；
2. val/natural-domain 结果能否预测独立 test 上的有害修订；
3. 固定权重的证据门是否在新任务上减少有害部署。

后续真实轮必须按“先冻结规则，再发送请求，再冻结动作，最后一次性 test 回放”执行，不能把 test 结果用于回溯调阈值。
