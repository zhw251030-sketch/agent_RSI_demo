# 基函数策略开发轮 v0.2 操作说明

日期：2026-10-22。本文说明实施入口、前置条件和预期输出；编写时不宣称新真实轮已经完成。科学问题、完整设计及边界见[协议](../experiments/2026-10-22-basis-trial-v02-design.md)。实际执行结果以本轮原始记录、离线审计和另行结果报告为准。

v0.1 首请求因必填辅助解释 4,223 字符超过 2,000 上限停止。v0.2 的策略工具只收 `rule_ids`，公式工具只收 `feature_ids`；可选 assistant content 只归档。旧编译器所需说明由宿主附固定标记，显式记录转换，不能伪称为模型提交。旧响应不追认，旧 `runs/basis-trial/measured-v01` 不恢复。

## 代码和数据边界

- 新调度入口：[run.py](../../extensions/basis_trial_v02/run.py)。保留 13 请求、两个人工 K=4 父结构和既定位置顺序，S1 冻结前不读训练数据。
- 新 SDK 接收与转换：[sdk_controller.py](../../extensions/basis_trial_v02/sdk_controller.py)。两入口都采用 ID-only，固定宿主元数据仅用于兼容旧编译器，不使用自由文字。
- 原任务装载、反馈、隔离及拟合继续使用已冻结的 `extensions/basis_trial_v01/feedback.py` 和 `extensions/symbolic_basis_v01`。新运行文件清单包含原依赖和 v0.2 namespace 的并集。
- 只允许原 `oscillator1/train` 的学习角色；本轮不下载、打开或评分封存 test_id/test_ood，不启动其他任务。

以下命令在服务器 `/home/hanwen/Project/project/agent_RSI_demo` 执行。不要在已有输出目录上重跑 prepare、simulate 或 run；目录存在会拒绝，禁止删除旧原档以绕过此规则。模型凭据继续使用已授权服务器配置，只在内存读取，不出现在命令、日志或仓库文件中。

## 准备、测试和冻结

先完成本轮新增测试和审查，确认旧代码、旧档案及工作树状态。测试本身不请求真实模型；其中 SDK 测试使用假 provider。

```bash
.venv/bin/python -m unittest extensions.basis_trial_v02.test_run extensions.basis_trial_v02.test_sdk_controller -q
.venv/bin/python -m extensions.basis_trial_v02.run prepare --output docs/experiments/basis-trial-v02-preparation
```

准备包包含 `design.json`、完整的 `learning-package.json`、替换过时接口说明后的 `update-packet.json` 及 `freeze.json`。历史 24 条转移、原策略目录和源码不得删减。准备只读取旧研究证据与角色元数据，不调用模型或读取真实 CSV 数值。

准备包与运行代码需按项目同步流程提交，并在服务器和本机核对。冻结后若改变任何依赖、提示或准备输入，必须重新建立匹配版本的冻结和新预演，不能沿用旧 readiness。

## 完整 SDK 预演

```bash
.venv/bin/python -m extensions.basis_trial_v02.run simulate --preparation docs/experiments/basis-trial-v02-preparation --output runs/basis-trial-v02/sdk-preflight-v01
.venv/bin/python -m extensions.basis_trial_v02.run verify --preparation docs/experiments/basis-trial-v02-preparation --output runs/basis-trial-v02/sdk-preflight-v01
```

预期是实际 OpenHands SDK 完成 13 个假 provider 请求、13 个合法接受、14 次人工测量占位，包含两次 swap 和十次 keep。每父六份完整请求除策略之外相同。最终 `audit.json` 通过且实验状态完整，才会写出 `readiness.json`。人工预测、模拟 usage 和伪测量次数都不是研究成绩、模型消费或实际 sandbox 执行次数。

预演失败时保留该目录及失败原因。没有通过的 readiness 不得启动真实轮；不能跳过失败位置、手写通过标记或在原目录补跑。

## 独立真实轮

仅在同一冻结版本完整预演、额外审计测试和旧档案核验通过，且本机、服务器与 GitHub 提交同步、服务器工作树干净后执行：

```bash
.venv/bin/python -m extensions.basis_trial_v02.run run --preparation docs/experiments/basis-trial-v02-preparation --certificate runs/basis-trial-v02/sdk-preflight-v01/readiness.json --output runs/basis-trial-v02/measured-v01
```

新轮至多 13 请求、保守预留 4 元，单请求 180 秒、零重试、最多 8,192 输出 tokens。唯一新提案若合法且 usage 已知，则先冻结 S1；之后才读取允许的训练表、拟合两父结构并顺序执行 12 actor。S1 与 S0 相同照实记录，不重新抽取。

每位置至多一次接受；每个合法结构一次拟合加一次独立预测。非法字段、结构越界、异常、未知 usage 或数值执行失败会停止后续位置。停止不等于模型或策略无效；需要据原始记录区分传输、接收、执行与研究结果。旧轮失败响应和规则不会被移入新轮替补位置。

## 终态核验、归档与报告

```bash
.venv/bin/python -m extensions.basis_trial_v02.run verify --preparation docs/experiments/basis-trial-v02-preparation --output runs/basis-trial-v02/measured-v01
```

核验只读已保存材料，不发模型请求或重新拟合。完整运行应报告通过；中止运行应报告记录一致但不完整，不能把后者说成对照完成。真实执行结束时的自动审计还须从已保存预测重算分数，计数中清楚区分拟合、预测、实际 sandbox、warmup 和模拟活动。

检查重点包括：`sessions/*` 中实际 SDK 请求/响应/派发/接受，actor 的 `host-conversion.json`，`experiment/policy-freeze.json`，固定 `context-A/B.json`，各父/子源码、参数、预测与测量回执，事件顺序、预算账本和最终汇总。请求及上下文引用保留原 `runs/...` 相对路径；归档到 `artifacts/...` 时用完整文件清单逐字节核对，不改原始引用来迁就归档路径。

报告所有预定位置，包括未开始和失败位置，给出每个父状态下 S0/S1 三次结果和父基线；不只报最佳结构。新模型用量加入累计账本，历史两笔未知 usage 保留，模拟用量排除。旧运行、旧数值诊断、旧校准及 v0.1 原档不改写。方法效果、独立泛化和后续规模扩展均依据实际结果另行判断。
