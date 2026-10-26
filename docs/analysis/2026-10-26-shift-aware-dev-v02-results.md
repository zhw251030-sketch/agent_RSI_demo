# Shift-aware v02 train-only split与诊断预演结果

日期：2026-10-26  
服务器：`13695090`  
运行脚本：`scripts/build_shift_aware_dev_v02.py`  
报告：`docs/environment/2026-10-26-shift-aware-dev-v02.json`  
报告 SHA-256：`4155a7fc7d24207844d7b579241f60e801720ba59ee8a7efcd8bd03852c4ff75`

## 目的

本轮把 holdout 失败审查转成一个新的、只使用训练数据的开发环境。它的作用是验证两件工程前提：

1. 四个任务能否在不触碰官方 `test_id/test_ood` 的情况下重新生成 v02 开发切分；
2. 宿主侧 shift profile 能否把正常检查批次和预先登记的输入域变化区分开。

本轮只产生输入覆盖诊断，不评估候选结构的任务分数，也不发送模型请求。

## 数据与防泄漏检查

- 使用四个公开训练文件：`bactgrow` 7,500 行、`stressstrain` 2,161 行、`oscillator1` 10,000 行、`oscillator2` 10,000 行。
- 每个任务生成 `fit_dev_v2`、`check_dev_v2`、`outcome_dev_v2` 的确定性 60/20/20 manifest，记录源文件哈希、行索引哈希和 manifest 哈希。
- `synthetic_shift_dev` 从 `fit_dev_v2` 选取最多 256 个行索引，只变换输入列；目标列从未进入 shift profile 或 synthetic fixture。
- 生成报告明确记录 `official_test_read=false`、`official_test_ood_read=false`、`target_values_read_for_shift=false`。

## 四类 shift fixture

| 任务 | fixture | 变换 | 基础 check 状态 | synthetic 状态 |
|---|---|---|---|---|
| `bactgrow` | `bactgrow-range-expand-v01` | 围绕 fit 均值将输入范围放大 1.8 倍 | `covered` | `shifted` |
| `stressstrain` | `stressstrain-condition-collapse-v01` | 将 `temp` 塌缩为单一参考条件 | `covered` | `shifted` |
| `oscillator1` | `oscillator1-range-expand-v01` | 围绕 fit 均值将状态输入放大 1.8 倍 | `covered` | `shifted` |
| `oscillator2` | `oscillator2-time-shift-v01` | 将 `t` 平移 -30，模拟时间窗口切换 | `covered` | `shifted` |

四个任务的 manifest 哈希分别为：

- `bactgrow`: `a681be7ec38ec65d08415f22fe890e48b03ca887fc930a4d90f17b5b17821000`
- `stressstrain`: `1a87fc0f4d41376ac385a8af7edaadf878d33600867b2064753e8e5329ad08d8`
- `oscillator1`: `6ed3b0a2c103ce057dad52369de9806d52ccda692ce8d595f4cfee3ea473ef8e`
- `oscillator2`: `a39220cc05694934ba2878398cbb3e5ae39a6984d0409f831650db52a523aca4`

## 结果解释

“基础 check 为 `covered`、synthetic fixture 为 `shifted`”只证明 shift profile 的输入诊断和预先登记的变换规则一致。它没有证明 shift gate 已经改善候选任务结果，也没有证明阈值适用于真实 OOD。下一步必须把 shift 状态绑定到 fake-agent 的 `final_action`，检查 `supported + shifted` 是否稳定转为 `retain_parent`，并核对所有 gate 行、哈希和审计字段。

## 下一步

1. 增加 shift-aware gate 的 fake-agent 预演，比较 `replacement_check` 与 `replacement+shift_gate`；
2. 在预演中加入 supported/covered、supported/shifted、contradicted/covered 和 unknown/shifted 四类边界；
3. 预演通过后，才考虑在新的 v02 开发切分上启动真实 Agent 请求；本轮已解封 holdout 不参与阈值选择。

