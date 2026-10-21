# measured-v03：r2 已完成评价的只读核对

本报告按完成检查点增补：初稿仅核查 P-eval-1 两臂，第 6 节在 bactgrow 两臂完成后追加，第 7–9 节在全部请求结束后补齐 P-eval-2 与 stressstrain。现覆盖 r2 全部八个已完成评价槽。每次只读已完成记录，不执行候选、拟合、重评分或调用模型，不改写原档或重新选择 S*。以下路径相对项目根目录，除特别注明外省略前缀 `runs/strategy-pair/measured-v03/experiment/`。

## 1. P-eval-1：实际请求只差 repair_policy

| 项目 | fixed | updated |
|---|---|---|
| 请求 | `sessions/r2-evaluation-P-eval-1-fixed/requests/request-0030.request.json` | `sessions/r2-evaluation-P-eval-1-updated/requests/request-0029.request.json` |
| 请求 SHA256 | `5a0cdb2876a3ae00dd64711d894e3aa420cec36af5569365735b433cb3d20337` | `a93fdc7a56a6c76fcbafde1bbe7a99a924be1b60dfcfa080411b997c30b72e56` |
| 实际规则 | R03 / R04 / R06 / R08 | R02 / R01 / R05 / R08 |
| 测量中的策略 SHA256 | `9937882539c30e7e519bf5251c14b35b29b84b23bb6f506077bdad39d3438445` | `453797a8ef00b2a2fb529f9301b3bedef10679ffa4bfccd0757ae72c78879b92` |
| 接受源码 SHA256 | `e65805c29ff431e6e100d6906f62eed313aa5615f429276cefcb7d6678a00a45` | `36228e93c43e1dac95ce11da4f558a7314f049f84c15ea6e450e1d17ff1349fb` |
| 同一 63 道评价题 | 0/63；63 次 IndexError | 63/63；63 次 VAL valid |

依据两份 `bound-sessions/r2-evaluation-P-eval-1-*.json`，两份源码提交均为 accepted；126 个结果文件逐一核对引用 SHA256。63 对 task_id、数据/域/分区/评价器哈希、评价门哈希和资源限制均相同。

把真实请求中 user JSON 的 `repair_policy` 去掉后，两份**完整请求对象**相同，包括模型、全部 system 内容、其余 user 内容、tools、tool_choice 和 max_output_tokens。规范化规则为 `json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=False)`；两份共同请求 SHA256 均为 `8c0b45c11eb45185b8b25ae40cb79dd7d108d78cb416be62a0dc4f7da48e50bb`。因此这是实际策略有差异、共同输入一致的一对；与 r1 选回 S0 的同策略情况不同。

## 2. fixed 的失败来自新增启发式读取了不存在的第三项

`sessions/r2-evaluation-P-eval-1-fixed/source.py:101` 建立 seed；第 106 行添加的是二元组 `("useable", s)`。新增 `priority` 函数第 156 行却对每一个 seed 元素直接访问 `f[2]`，没有先检查长度。第 186 行搜索展开时调用该函数。63 条记录均为 `candidate_error / python_exception`、`exception_type: IndexError`、`candidate_line: 156`，与上述静态缺陷直接相符；全部未进入 VAL。

这是 fixed 从共同起点出发新增的错误，不是模型在 context 中看见的原有失败。`contexts/P-eval-1.json` 的起点在十道 learning 任务上均成功；原源码没有 seed/priority。fixed 的解释说 `“adds ... a per-state successor ordering key”`，源码确实增加了这个排序，但实现异常使其“只改变层内探索顺序”的行为保证不成立。本次没有修正该行后再运行，不能据此证明修正后就能解决 63 题。

首题原始结果为项目根目录下 `runs/role_executor_feedback/3a8af422def948f7b5261df4f9c8b6a9/result.json`。全部 63 条同样定位于第 156 行。

## 3. updated 保留 BFS 主体，但不是对 fixed 错误的后续修复

`sessions/r2-evaluation-P-eval-1-updated/source.py` 没有上述 seed/priority。它从共同起点独立生成，保留 BFS 及三个合法动作，增加输入归一化防护、整合 state 事实扫描、收紧 link 端点类型检查，并移除未用导入。第 148 行起的 BFS 主体仍逐步生成后继并检查 goal。

updated 在 `sessions/r2-evaluation-P-eval-1-updated/requests/request-0029.response.json` 开头正确指出：`“No observed failure exists in the baseline feedback”`，即起点十题都成功。源码保留有效解的主要结构，真实后续 63 题全部通过 VAL；首题为项目根目录下 `runs/role_executor_feedback/c62f5e61a7be432b82f4681b689176a2/result.json`。

不能把这个结果写成“updated 发现并修复 fixed 的 IndexError”：两臂是共同起点的独立生成，updated 请求号 29 还早于 fixed 的 30，模型也未接收 fixed 的错误记录。可以描述为该次 updated 产物避免了 fixed 新增的缺陷。

## 4. 两臂解释都不能直接作源码行为保证

对比 `contexts/P-eval-1.json` 中完整起点源码，原 `MAX_STATES = 300000`。

- fixed 第 29 行改为 400000，但 `request-0030.response.json` 明确称 `“the cap behavior is unchanged from the baseline”`，与实际修改矛盾。其“保持正确性”也被实际异常否定；并未测量新增启发式是否更快。
- updated 第 26 行改为 200000，却把修改概括为 `“a small, behavior-preserving cleanup”`，并称 `“Search semantics ... are unchanged”`。减少搜索展开上限可能改变需要更多状态时是否找到解，所以全局行为保持没有依据；这 63 题成功不消除该源码层面差异。
- updated 还说预计算集合用来索引 goals/nuts，但第 84 行的 `nut_set` 建立后没有使用。`loc_set` 实际用于 link 类型过滤，不能据此宣称目标/螺母查找获得了所述优化。它提到空目标提前返回只是冗余保护，原来的 subset 检查已覆盖；这点解释自己也承认。

这些解释缺陷不撤销已记录的 63/63 成绩；它们限制的是能否把自然语言解释当作完整、准确的修改说明或收益机制证据。

## 5. 当前可支持的研究结论

r2 这一个起点配对的实际策略不同，updated 终稿在同一 63 题上成功、fixed 终稿全部因新引入的实现错误失败。因此这是有策略差异的单次产物优势记录。一次生成、一个起点不足以证明规则组合稳定有效，更不能把 63 道题视为 63 次独立策略学习重复；共同产生它们的是同一份程序。

起点的 10/10 是 learning 集，终稿的 63/63 是另一 evaluation 集，不能报成同题精度改进。本次没有执行官方封存测试，也未验证大规模效率或最优性。完整 r2 四状态结论见后补的第 9 节。

## 6. bactgrow：updated 训练误差更低，增加一参数并更换基函数族

两个完成记录为 `bound-sessions/r2-evaluation-S-bact-eval-1-fixed.json` 与 `...-updated.json`；其中全部 request/result 引用的 SHA256 均经只读核验。去掉 user JSON 中的 repair_policy 后，完整模型请求对象相同，沿用第 1 节规范化方式的共同 SHA256 为 `d6483ef4b433c5b44d68268cdee48a08ca21b20e379352989fda98a0813ae411`。fixed 实际使用 S0、updated 使用 R02/R01/R05/R08，两臂策略哈希同第 1 节；不是 r1 那种同策略采样。

| 对象 | 参数数 | train MSE | train NMSE |
|---|---:|---:|---:|
| context 中冻结起点 | 7 | 0.016493488944562467 | 0.8503733599018976 |
| r2 fixed | 14 | 0.01638541847283465 | 0.844801449043118 |
| r2 updated | 15 | 0.01412110614269868 | 0.7280577515442443 |

fixed 请求为 `sessions/r2-evaluation-S-bact-eval-1-fixed/requests/request-0031.request.json`，源码 SHA256 `9c045f8b32a4dd4941a362b187cf49780a14a7b7c6b38c70bf1f5d59ed7c5c0e`；updated 请求为 `sessions/r2-evaluation-S-bact-eval-1-updated/requests/request-0032.request.json`，源码 SHA256 `9604a6385064ef2aa3ae49128d4e2293c9ec10b8a81a0798eb86e063388f371b`。

两臂均拟合收敛（nfev=4），metric_scope/metric_split 都为 train，并明确记录 `“Within-task training fit; not held-out prediction.”`。updated 相对 fixed 的 NMSE 降低约 0.1167436975、增加一个参数；这是本次同任务训练拟合的精度收益，不是简化或封存预测泛化。

**源码差异是两种基函数族。** fixed 有常数、四个一次项、六个两两乘积、三个三重乘积，共 14 个系数；updated 有常数、四个一次项、六个两两乘积、四个平方项，共 15 个系数。两者通常数值范围内都线性依赖待拟合系数，但并非只添加一项的嵌套配对：updated 用四个平方项替换了 fixed 的三个三重项。不能把收益直接分配给“多一个参数”、单一平方项或某条策略规则。

**解释中的可核实与未验证部分：**

- fixed 的 `request-0031.response.json` 对 14 项计数、线性参数化和旧 clip/scale 恒等关系描述基本符合源码；它将表达能力不足明确作为假设，并承认生成时尚未测量。源码 docstring 第 8–9 行却写 `“one triple term”`，实际第 42–44 行有三个三重项；应以源码计算式及提交数为准。
- updated 的 `request-0032.response.json` 对旧七项、缺少独立 u3 一次项、新十五项的结构计数准确。但 `“the shortfall is expressive power”` 把高训练误差直接归因于表达能力，单个 NMSE 与 success 只支持执行成功及当前拟合误差，不能排除优化或数据等解释。它没有在生成时宣称已取得新 NMSE。
- updated 源码第 45 行称会规范化极端幅度，实际第 46–47 行 `out / (1 + abs(out)) * (1 + abs(out))` 在有限实数、忽略浮点误差时是恒等式。没有额外测量支持该段提供数值稳定化；这不影响本次记录的拟合成绩。

项目根目录下的完整测量为 fixed `runs/role_executor_feedback/73dc11fea9214056bb7281d0b2b30353/result.json`、updated `runs/role_executor_feedback/74f9fac472b44601b893e60e048cb0e8/result.json`。两份终稿的 task_id、数据哈希、评价器、分区和 gate 一致。此节只确认两臂直接比较；context 起点分数单列为模型所见的历史信息，不另行重跑来验证。

本节写成时，r2 前两个已完成配对均显示 updated 产物的任务指标更好；仍只有一次选出的策略及每起点一次生成，不足以概括稳定跨任务机制优势。剩余两对完成后的结果见下文，不能只选前两对报告。

## 7. P-eval-2：错误类型不同，两臂都没有成功任务

依据两份 `bound-sessions/r2-evaluation-P-eval-2-*.json` 及其 126 份结果，fixed 为 49 次 `invalid_output / operator_syntax`、14 次 `task_failure / plan_semantics`；updated 为 63 次 `task_failure / plan_semantics`。两臂均 0/63，参数计数均 0，提交均 accepted。两份源码、request、submission 和结果引用均经 SHA256 检查；63 对任务及数据/评价器/分区/gate/限制相同。

fixed 请求为 `sessions/r2-evaluation-P-eval-2-fixed/requests/request-0034.request.json`，源码 SHA256 `6be510b70ad0f3ac7eefc99923005ebc168346c4afce5904ecacbeb76ed4635f`；updated 请求为 `sessions/r2-evaluation-P-eval-2-updated/requests/request-0033.request.json`，源码 SHA256 `3fcb80ffecc15d82d3115af9d9275a27256b59dc5bc7c4319f0d48874a3d6630`。实际策略分别为第 1 节 S0 与 r2 S*；去掉 repair_policy 后完整请求相同，规范化共同 SHA256 为 `d2a53ef1d231c0602d690a5563d7e73d9c945d49da1310a304711c125a6ca00e`。

**fixed 把已有格式问题留在了新程序里。** `sessions/r2-evaluation-P-eval-2-fixed/source.py:18` 的 `_fmt` 为 `"(" + " " + ...`，在左括号后额外插入空格。49 个非空输出均在第一动作（索引 0）被判 operator_syntax；另外 14 个输出为空，经过 VAL 判 plan_semantics。因而没有成功结果。fixed 的 `request-0034.response.json` 声称恢复了目标检查、计划能达到目标，属于尚未执行时的过强保证，不能以新源码较长或包含 fallback 代替成绩。

该解释还把 `get_plan(objects, init, goal) = 3` 称为 parameter count，混淆函数输入个数与本实验的拟合系数计数；实际 submission 的 n_params 是 0，未被写成 3。静态另可见第 231 行先返回 nut 位置、第 233 行随后要求仍在 spanner 位置拾取，位置不同时条件冲突；但本轮没有逐步干预定位 14 个空计划的唯一原因，也没有移除格式空格后重测。

**updated 的格式符合要求，但 63 次都返回空计划。** 其 `_fmt` 第 17 行没有上述空格；`restore()` 第 137 行原位还原状态与清空 plan，第 212 行先复制 plan 再 restore 的保存逻辑确实存在。结果仍全部为 plan_length=0、VAL invalid，所以“从格式失败变为语义失败”不能计为任务收益。

updated 的 `request-0033.response.json` 对旧程序返回值的解释不准确：它说 search 返回未填充 trial，且 `_restore` 把最终 plan 清空，从而导致空输出。旧 `contexts/P-eval-2.json` 源码第 328–330 行实际上先 `final = list(plan)`，再 `_restore(snap)`，最后返回 `final[:1000]`；成功分支不会因清空原列表而清空这个副本。trial 未使用是真实问题，但不能直接以此证明外层必然返回空计划。新源码中 `acquire` 只返回 bool，可能拾取与 preferred 不同的扳手，而第 152 行固定 `holding = spanner`；还先走到 nut 再寻找扳手，在有向链上未必能返回。它们是静态可见的潜在缺陷，不是本轮已做消融证实的全部失败原因。

首题完整记录（项目根目录相对路径）：fixed `runs/role_executor_feedback/6044daa8a5494c86a4e2581ab3b83846/result.json`，updated `runs/role_executor_feedback/7ae83c10dd2640c594e79a5062cb3d2d/result.json`。

## 8. stressstrain：一臂字节保持，一臂仅提取中间变量，成绩完全相同

两份 `bound-sessions/r2-evaluation-S-stress-eval-1-*.json` 均已完成，分别对应 request-0035（fixed）与 request-0036（updated）。共同请求在去掉 repair_policy 后完全相同，规范化 SHA256 为 `ad54df241ceafcd29411c52b96515c877d92d09878bff8cb6ed82ad9c4ecb966`；实际策略仍分别是 S0 与 r2 S*。

两臂均 accepted、7 参数、train MSE `0.02645932925116995`、train NMSE `0.34361657358684433`，与 context 中起点分数相同；拟合参数数组逐值一致，nfev=21、candidate_calls=106、converged=true。只有运行耗时不同，不能据此作稳定速度比较。

fixed 源码与 context 起点逐字节相同，SHA256 为 `58e37aa5ec329ef8a47b136ed1cc4d5e33215fda0aacb81ea091aee261f07474`。updated 源码 SHA256 为 `7648b20250d4dce1efa09743864ae39b08f883e71d6ee748ead88bc27c33465b`；差别只有 docstring 与提取 `x0 = l0*u0`、`x1 = l1*u1`，再在原式里使用 x0/x1。平方仍分别计算一次、没有剪裁或新幅度约束；公式和声明参数数都未简化。

fixed 的 `sessions/r2-evaluation-S-stress-eval-1-fixed/requests/request-0035.response.json` 对“原样保留”的声明有字节比较支持，但 `“residual is large relative to a linear model”` 没有配套线性基线结果。updated 的 `...-updated/requests/request-0036.response.json` 正确说明代数等价、尚未运行，但以下额外说法没有依据：

- `“linear-in-params least squares fit”` 不符合七个声明参数的表达式：例如交叉项系数为 `g*c01*l0*l1`，平方项系数为 `g*q0*l0**2`、`g*q1*l1**2`，它对全部七个参数并非线性。可以代数组合成较少有效系数，不等于本次已改变参数化、保持全部系数边界或实际完成简化。
- `“removes duplicated power evaluations”` 不符合逐行差异：两份源码都计算两个平方，提取的是重复的缩放乘法。
- `“keeps intermediate magnitudes bounded”` 与避免溢出/改善条件数没有新增操作或数值诊断支持；相同公式、相同参数与相同成绩也没有显示训练收益。此处不声称一般浮点计算在所有可能输入上严格逐位等价。

完整结果（项目根目录相对路径）为 fixed `runs/role_executor_feedback/e8258b81dfc44a5e9bbea8b36d16b89e/result.json`、updated `runs/role_executor_feedback/98e0ed12085c4bcd8215d18692faf84a/result.json`，数据/评价器/分区/gate/限制均相同。

## 9. 完整 r2 四状态的只读汇总：2 beneficial + 2 retain

| 后续评价起点 | fixed | updated | 按冻结目标规则解释保存指标 |
|---|---|---|---|
| P-eval-1 | 0/63，IndexError | 63/63，VAL valid | beneficial：新增成功且没有丢失成功 |
| bactgrow | 14 参数，NMSE 0.844801449043118 | 15 参数，NMSE 0.7280577515442443 | beneficial：训练精度收益，非简化 |
| P-eval-2 | 0/63，49 格式失败 + 14 空计划 | 0/63，63 空计划 | retain：没有成功数收益 |
| stressstrain | 7 参数，NMSE 0.34361657358684433 | 7 参数，同 NMSE | retain：没有精度或参数数收益 |

“2 beneficial + 2 retain”与这四对保存指标吻合。这里是冻结 S* 后的评价结果描述，没有调用 selector、没有重新优化或选择 S*，也不能把后续四对替换为当时的选择证据。真实保存的 `selection/r2-decision.json` 在选择阶段依据 **1 beneficial + 3 retain** 选出 R02/R01/R05/R08；文件 SHA256 为 `3790b58dd88ec99ca6877b13241e02fe9f83f9d28318175a4fff90ef4baf6fa5`。

本轮可以报告一次策略学习/选择后，在两个新规划起点和两个后续符号任务上的四对有界结果，其中两对有任务指标收益、两对没有收益。不能把 63 题当作独立策略重复、把同一历史包上的提案当作独立训练数据重复，或把符号 train NMSE 当作留出预测成绩。源码与解释多次不一致，故本轮还不能证明解释可靠、稳定机制优势或普适性；所有正式有效性结论仍需结合宿主最终完整审计。
