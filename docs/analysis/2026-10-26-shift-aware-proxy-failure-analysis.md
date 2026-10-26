# Shift-aware v02 proxy 失败逐任务分析

日期：2026-10-26  
数据来源：`docs/environment/2026-10-26-shift-aware-proxy-outcome.json`、`docs/environment/2026-10-26-shift-aware-dev-v02.json`  
性质：开发阶段、输入 shift 工程诊断；不读取官方 test/OOD，不是正式 benchmark。

## 分析问题

上一份 proxy 结果只回答了动作计数。这里把 8 个真实 proposal 按任务拆开，区分三种情况：

1. **新增阻断**：旧 replacement action 会执行且 proxy 退化，shift-aware action 改为保留父结构；这是当前机制最直接的正向证据。
2. **已有阻断**：proxy 退化，但旧 evidence gate 已经保留父结构；不能把它归功于 shift gate。
3. **过度保守**：候选在 synthetic shift 上 proxy 变好，却因为 shift gate 被保留；这表示当前门控有潜在机会成本，不能只报告拦截收益。

proxy NMSE 使用 `fit_dev` 目标行作为标签，所有候选参数由 `fit_dev_v2` 拟合后固定到 synthetic fixture 预测。该设计能检查“输入变换下动作是否避开明显退化”，但不能证明真实分布外预测性能。

## 逐任务结果

| 任务 | shift 特征 | proposal | 父→候选 proxy NMSE | 旧动作 | shift-aware 动作 | 分类 |
|---|---|---|---:|---|---|---|
| `bactgrow` | `b,s,temp,pH`，四维范围外比例约 0.43–0.54 | supported swap | 0.910682 → 1.270783 | execute | retain | **新增阻断**，Δ=+0.360101 |
| `stressstrain` | `temp` 方差塌缩为 0 | supported swap | 1.001171 → 0.889178 | execute | retain | **过度保守候选**，Δ=-0.111993 |
| `stressstrain` | 同上 | supported swap | 1.001171 → 0.889178 | execute | retain | **过度保守候选**，Δ=-0.111993 |
| `oscillator1` | `x,v` 范围外/方差比异常 | contradicted swap | 17.108823 → 136.435469 | retain | retain | **已有阻断**，Δ=+119.326646 |
| `oscillator1` | 同上 | contradicted swap | 17.108823 → 136.435469 | retain | retain | **已有阻断**，Δ=+119.326646 |
| `bactgrow` | 同一 fixture | unknown keep | 0.910682 → 0.910682 | retain | retain | 无候选 |
| `oscillator2` | `t,x,v` 范围/方差异常 | unknown keep | 0.290723 → 0.290723 | retain | retain | 无候选 |
| `oscillator2` | 同一 fixture | unknown keep | 0.290723 → 0.290723 | retain | retain | 无候选 |

## 机制含义

- 8 个 proposal 中有 3 个 proxy 退化；旧 action 会部署其中 1 个，shift-aware action 部署 0 个。
- 相对旧 action，shift gate 新增阻断 1 个 `bactgrow` 有害替换；另外 2 个 `oscillator1` 有害替换本来就被 `contradicted` evidence 保留。
- `stressstrain` 的两个 supported proposal 在 synthetic shift 上反而改善，但 shift gate 仍然保守地保留父结构。这是当前机制的已观测机会成本：在输入 shift 下，gate 只根据输入覆盖性改变动作，没有使用 shifted outcome 进行再判断。
- 因而当前 v02 不是“shift 越大越应拒绝所有候选”的充分论证；它提供了一个安全默认策略，但需要研究如何在 shift 状态下加入小规模验证、置信度或风险上界，减少对真实改善候选的误拦截。

## 结论边界

本分析支持：在四个 train-only 开发任务和一组预定义 synthetic shift 上，shift-aware host gate 能拦截一个旧 gate 会部署的 proxy 有害替换，同时暴露两个保守误拦截案例。它不支持真实 OOD 性能提升、统计显著性、任务普适性或最终 holdout 结论。下一步应围绕“shift 下的安全验证与保守代价”设计新的开发对照，并在方案冻结后再使用未参与设计的独立 holdout。
