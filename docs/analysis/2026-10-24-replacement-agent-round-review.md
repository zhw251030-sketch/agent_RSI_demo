# 替换充分性真实小轮独立审查

日期：2026-10-24  
审查对象：`docs/experiments/2026-10-24-replacement-agent-round-protocol.md`  
审查状态：协议内容通过；真实请求仍被 runner 接线和服务器预检阻止。

## 审查结论

协议的研究单位和数据边界是明确的：两个公开符号任务、每个任务三个固定父结构、每个父结构两个一次性请求，共 12 个请求；每个候选复制到 `no_check`、`sham_check` 和 `replacement_check` 三个配对条件。`fit_dev` 负责拟合，`check_dev` 负责事前删除—替换证据，`outcome_dev` 只在门冻结后做 shadow 评分。这个顺序能够把“证据是否影响执行”与“候选最终是否有害”分开记录。

协议还明确禁止补抽、重试、权重更新、长期策略更新、封存集读取和把两个重复槽位当成独立任务样本。预算、最大输出、单 session 一次请求以及未知 usage 即停止的规则也足够具体，可以由现有 `BudgetLedger` 和 `sdk_controller.run_session` 执行。

## 已有证据

| 要求 | 现有证据 | 状态 |
| --- | --- | --- |
| 训练数据源与行索引切分 | `docs/environment/2026-10-24-replacement-dev-splits.json` | 已冻结 |
| `I^-`、`I^+`、`R` 定义与状态分类 | `analysis/basis_edit_comparison/replacement_evidence.py` | 已测试 |
| 固定参数 `check_dev` 预测 | `analysis/replacement_evidence/fixed_prediction.py` | 已测试 |
| 三结构 fit 后再 check 的顺序 | `analysis/replacement_evidence/triplet_runner.py` | 已测试 |
| Linux 锁定沙箱 | `docs/environment/2026-10-24-replacement-triplet-preflight.json` | 无模型预演通过 |
| OpenHands 单工具与 gate/freeze 顺序 | `docs/environment/2026-10-24-replacement-agent-preflight.json` | 4 槽合成预演通过 |
| 完整 12 槽真实任务 runner | 尚不存在 | 待完成 |

## 必须在真实请求前补齐的接口

1. runner 必须读取 split report 中的 `source_data_sha256` 和 `row_indices`，重新核对 CSV 哈希后才生成数组。不能把整份 CSV 或官方 test/OOD 目录交给 actor。
2. runner 必须把三个固定父结构编译为 `submit_basis` 的确切 `feature_ids`，并在 actor 提交后验证候选是 keep 或恰好一次 feature swap。结构无效应记录并停止该轮槽位，不能自动重试。
3. 对合法 swap，runner 必须在同一个 fit protocol 和同一个锁定 runtime 下完成 parent/common/added 的 `fit_dev` 拟合，再把参数冻结后向 `check_dev` 发起不含 `y` 的 predict 请求。不能把拟合参数重新优化到 check 或 outcome 数据上。
4. gate 记录必须包含候选和证据绑定字段；所有 36 条 gate row 完成后才能生成 freeze hash。`outcome_dev` 的任何读取必须发生在 freeze 成功之后，并且 shadow 结果不能改写 gate 状态。
5. 真实模式必须先验证 fake-provider 12 槽证书、代码版本、SDK 版本、runtime lock 和新的空运行目录，再从既有 auth 文件读入内存中的 key。任何 usage unknown、网络失败、协议错误或 runtime hash 不一致都要立即停止，不得恢复本轮。

## 当前不支持的结论

即使真实 12 槽完成，也只能报告两个公开方程上的机制开发证据、候选执行率、事前证据覆盖和 `prevented_harm`。12 个槽位不是跨任务统计样本，不能据此宣称普适性、显著性或封存泛化；后续仍需独立任务复制和封存评价。

