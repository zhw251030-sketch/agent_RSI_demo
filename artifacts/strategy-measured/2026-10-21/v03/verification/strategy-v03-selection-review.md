# measured-v03 选择阶段独立只读核对

2026-10-21。只读取已经冻结的四份策略提案、选择阶段已完成会话、对应源码/上下文和两份选择决定。没有运行模型、候选、拟合或额外任务，也没有读取当时仍在执行的后续评价槽。本文件不代表最终后续评价结论。

所有下列路径相对于项目根目录；运行前缀为 `runs/strategy-pair/measured-v03/experiment/`。

## 1. 选择结果与证据范围

依据 `selection/r1-decision.json`、`selection/r2-decision.json` 中 `replay.paired_results`、`replay.decision` 和 `selected_policy`：

| 重复 | 起点 | fixed 终稿 | updated 终稿 | 配对接受结果 |
|---|---|---|---|---|
| r1 | P-select-1 | 0/19，空计划 | 0/19，NameError | retain |
| r1 | S-select-1 | 15 参数，NMSE 0.1533855701895147 | 15 参数，optimization_failed，无 NMSE | unknown |
| r1 | P-select-2 | 19/19 | 19/19 | retain |
| r1 | S-select-2 | 8 参数，NMSE 0.1906789858240599 | 14 参数，NMSE 0.14318745181009088 | promote / meaningful_accuracy_gain |
| r2 | P-select-1 | 0/19，计划语义失败 | 0/19，计划语义失败 | retain |
| r2 | S-select-1 | 15 参数，NMSE 0.1533855701895147 | 16 参数，NMSE 0.14774482274486497 | promote / meaningful_accuracy_gain |
| r2 | P-select-2 | 19/19 | 19/19 | retain |
| r2 | S-select-2 | 8 参数，NMSE 0.1906789858240599 | 8 参数，NMSE 0.1906789858240599 | retain |

- r1 的 S-select-2 精度改善为 `-0.04749153401396902`，增加六参数；但 S-select-1 缺少完整数值结果，整体 `unknown / uncertain_or_unmeasured_pair`，S* 保留 S0（R03/R04/R06/R08）。不能忽略拟合失败，只报告有利配对。
- r2 的唯一收益来自 S-select-1，NMSE 差为 `-0.005640747444649735`，增加一参数；其余三对 retain，整体 `promote / paired_benefit_without_regression`，S* 选择 R02/R01/R05/R08。
- 以上符号数值是 oscillator2 的训练数据拟合；两项 promote 都是精度改善，不是参数简化、独立测试预测泛化或已知物理公式恢复。
- 两次策略提案使用同一旧学习包；两次选择使用相同选择起点与数据，不能当作独立任务重复。
- 后续 r1 fixed 与 updated 都应使用 S0，必须核对实际策略哈希；若相同，后续成绩差只能视为同策略随机重复差异，不能归因策略改进。r2 才是 S0 与被选新策略的比较。

## 2. 策略解释不能由合法接收自动认证

四提案顺序分别为：r1-updated R02/R05/R01/R08；r1-shadow R02/R01/R05/R08；r2-shadow R01/R05/R02/R07；r2-updated R02/R01/R05/R08。四次接受形成三种不同顺序。

**r1-updated 将删除误读为扩展。** `sessions/r1-update-updated/requests/request-0001.response.json` 的解释写：`“rejected 6-term expansion (delta 0.0015)”`。然而 `update-packet.json` 的 `learning_material.states` 中 S-v3 的诊断记录为 `symbolic_term_removal`：原始六参数 NMSE 0.09224903410100932，删除 param5 后五参数 NMSE 0.09376229967010528，差 0.0015132655690959645。该数值来自临时删项诊断，不是六项扩展失败。此提案还以残差偏差较小推导格式检查优先，给出的记录没有证明这条因果联系。

**r2-shadow 的文字顺序与提交顺序不一致。** `sessions/r2-update-shadow/requests/request-0003.response.json` 写格式检查 R01 先于 R02，R02 又先于 R05；实际 `proposals/r2-update-shadow.json` 为 R01/R05/R02/R07。其他解释中的“未选规则仍保留为约束”也不符合实际四条规则的 actor 表示。任务契约中的约束仍在，但不能据此说所有未选策略规则依然被发送。

## 3. 实际源码与解释的核对

**r1/P-select-1 updated：未导入 deque，另有旧源码误读。**

- `sessions/r1-selection-P-select-1-updated/source.py:135` 为 `queue = deque([start])`；全源码没有 import 或 deque 定义。对应 `bound-sessions/r1-selection-P-select-1-updated.json` 引用的 19 条结果均为 NameError，候选行 135。
- `sessions/r1-selection-P-select-1-updated/requests/request-0006.response.json` 声称旧 `_typed` 对普通字符串类型 `“registered nothing”`。`contexts/P-select-1.json` 中源码第 40 行实际有 `tuple(typ) if isinstance(typ, (list, tuple)) else (typ,)`，随后用 `('man',)` 等键查询；字符串类型并未被忽略。
- 同一解释称不同地点取来的扳手不能用于目标螺母。公开域允许 pickup 产生 carrying，再经 walk 移动；拧紧时同地不要求扳手初始位置与螺母相同。这里是任务规则推理错误，不是额外实验诊断。

**r1/S-select-2 updated：有实测精度收益，但“严格线性”不成立。**

- `sessions/r1-selection-S-select-2-updated/requests/request-0011.response.json` 的解释称新增项为 `“strictly linear-in-parameter basis terms”`；对应 `source.py` 的 docstring 更将整个表达式称为 `“strictly linear in params”`。实际 `out = core * s0 * s1 * s2`，其中 s0/s1/s2 均含拟合参数，会形成参数乘积；整体不是对全部参数的线性模型。这里区分新增系数在其他参数固定时的线性，与对全部拟合参数的整体线性。
- 旧表达式乘开后已包含若干交叉项，不能仅看 core 缺项就证明目标残差来自相应结构缺失。
- 新增六参数与训练 NMSE 降低是有效的记录事实；未做控制参数量、拟合器或具体特征消融，不能将收益全部归因其解释的机制。

**r2/S-select-1 updated：主要编辑与源码一致，欠拟合解释未被单独证明。**

- `sessions/r2-selection-S-select-1-updated/requests/request-0016.response.json` 提出将可拟合 tanh 内部增益替换为固定特征的线性系数；对应源码确实使用 16 个固定输入特征 `feats` 与参数系数相乘求和。这一主要编辑声明得到静态源码支持。
- 单个训练 NMSE 不能诊断“欠拟合”或排除有限拟合预算、优化与参数表示的影响。该模型同时改变了特征与参数数，实测下降不单独认证理由。
- 解释/注释称有 quartic 项，实际 q*s、s*s*s、u1*u1*u1 都是三次；源码没有所称四次多项式项。

**r2/S-select-2 updated：声称改变结构，实际只改 docstring。**

- `sessions/r2-selection-S-select-2-updated/requests/request-0020.response.json` 写 `“replace the multiplicative cubic scaling”` 并称新增交叉项。
- 将对应 `source.py` 与 `contexts/S-select-2.json` 中基线源码逐行比较，唯一变化是 equation 的 docstring；参数索引、s0/s1/s2、输出乘积及 nan_to_num 完全相同。源码原字节并非相同，但计算正文相同。
- 两者八参数及 NMSE 0.1906789858240599 相同，符合该静态核对。不能把“描述了修改”记为实际完成结构修订。

**P-select-2：真实修补成功，但两臂均成功。** `sessions/r1-selection-P-select-2-updated/requests/request-0010.response.json` 对 `_actions` 两参数声明、三参数调用的定位有旧源码支持；新版本修正签名及链接传入并得到 19/19。fixed 也得到 19/19，因此不能把该成功当作 updated 独有收益。源码还含其他改动，未做单独干预来证明每一改动的因果作用。

## 4. 使用边界

上述短引文来自本项目的原始模型响应。解释的错误不能自动证明整套规则无效；训练收益也不能反向证明解释可信。正式结论以完整选择/后续评价、实际请求绑定和任务范围为准。本核查没有改变学习包、提示、策略、候选、评分或运行进程。
