# 推断证据轮：8份真实候选的静态与归档诊断审查

本稿仅读取[完整原始归档](../../artifacts/inference-policy/2026-10-20/v01/README.md)中的源码、候选记录、诊断、请求和审计，不重跑候选、不调用模型。本文说明已经发生的具体变化及失败位置；没有通过新的干预隔离每一项修改的因果效应。评分遵循运行时冻结协议，未对失败程序补空格或改分。

## 总体比较

| 起点 | 父本 | self | checked | 可以直接判断的差别 |
|---|---:|---:|---:|---|
| p1/P-A002 | 0/10 | 0/10 | 0/10 | 两者仍返回空计划，未修正携带状态只能保存一把工具的问题。 |
| p1/S-poly5 | NMSE 0.09376229967010528 | 0.09224903410100932 | 0.0923413716534127 | self保留v²并追加v³（6参数）；checked以v³替换v²（5参数）。两者正增益均小于事前0.005预测。 |
| p2/P-H002 | 0/10 | 10/10 | 0/10 | self得到合法计划；checked输出左括号后多一个空格，11动作在第0项就被格式检查拒绝。 |
| p2/S-odd4 | NMSE 0.09180470524756017 | 0.09171468125487472 | 0.09180398722781567 | self替换速度项，checked追加x⁵；两者正训练增益都很小，均未达到各自登记预测。 |

p2两复查最终策略**完全相同**，均为R05/R02/R07/R08。又逐项读取比较了规划两个请求、符号两个请求的完整JSON（model/messages/tools/tool_choice/max_output_tokens），分别完全相同：[规划self请求](../../artifacts/inference-policy/2026-10-20/v01/p2-P-H002-self/requests/request-0014.request.json)、[规划checked请求](../../artifacts/inference-policy/2026-10-20/v01/p2-P-H002-checked/requests/request-0012.request.json)；[符号self请求](../../artifacts/inference-policy/2026-10-20/v01/p2-S-odd4-self/requests/request-0011.request.json)、[符号checked请求](../../artifacts/inference-policy/2026-10-20/v01/p2-S-odd4-checked/requests/request-0013.request.json)。所以p2这两个下游结果差异属于相同已记录输入下的两次生成差异，不能归因于检查反馈，更不能据此说检查“使规划从10/10下降到0/10”。

## P-A002：两次修订都没有解决状态表示的限制

两者公开problem0/1的原始轨迹均到达各自源码第111行`return []`，`get_plan`正常返回list，记录中异常事件为0、trace未截断；计划长度与实际执行动作均0。checked的`apply`在两题仍各调用53/51次。这支持“搜索确实运行但最后没有返回解”，不支持“入口没被调用”“BFS没执行”或“已发生异常所以返回空计划”。参见[self诊断](../../artifacts/inference-policy/2026-10-20/v01/p1-P-A002-self/diagnostics.json)与[checked诊断](../../artifacts/inference-policy/2026-10-20/v01/p1-P-A002-checked/diagnostics.json)。诊断trace本身是候选进程观测，不能升级成任意执行事实的完全可信证明。

两份源码都把携带状态压成一个标量：self第95行`new_carried = s`，checked第62行`carried = s`，每次拾取覆盖前一把工具，而且工具已从地面位置字典删除。两题公开输入都是单向shed→…→gate、3个目标螺母在gate、每次拧紧消耗一把useable工具；到gate无法返回拾取。该表示无法保留提前携带的多把工具，与任务允许多条carrying事实不符。源码与公开实例共同给出了具体限制；没有新增修复消融，所以本稿不把它表述为对所有实例的实验性唯一根因证明。来源：[self源码](../../artifacts/inference-policy/2026-10-20/v01/p1-P-A002-self/candidates/planning-001.py)、[checked源码](../../artifacts/inference-policy/2026-10-20/v01/p1-P-A002-checked/candidates/planning-001.py)、[公开实例及原输入](../../artifacts/inference-policy/2026-10-20/v01/p1-P-A002-self/task-prompt.json)。

self说明把`who in spanner_locs or who in spanners`称为事实误分类，又提出KeyError/内部表示问题；但旧源码的列表成员判断合法，诊断未记录其声称的异常。checked说明自己反复推翻索引与成员判断，再以“清理解析”收尾，没有识别单标量carried的限制。它开头还写“all 8 tasks”，而本批范围为2提示+8开发共10题。两者说明均不等同于故障定位证据。

self主张把完整事实列表交给不匹配的证据操作，得到schema_invalid；预测开发成功数增加≥7，实际0。checked主张父本开发成功数>1，与实际0冲突；预测增加≥1，实际0。原文和精确检查见[self审计](../../artifacts/inference-policy/2026-10-20/v01/p1-P-A002-self/audits.json)、[checked审计](../../artifacts/inference-policy/2026-10-20/v01/p1-P-A002-checked/audits.json)。

## P-H002：相同策略与输入，生成结果仍可跨越成功和接口失败

旧源码在三个动作生成器中把`(at man location)`里的`a[1]`当成人的位置；`a[1]`实际是人名，后续location过滤使动作列表为空。旧源码还对`_apply`返回的可变set执行`seen.add(ns)`；当动作生成恢复且后继未立即达到目标时，这会成为另一个需要处理的潜在类型问题。两份新源码都改用`a[2]`读取位置，并把后继状态转为frozenset；此处可由源代码直接核验，不需假定原隐藏分支已执行。来源：[旧源码](../../artifacts/inference-policy/2026-10-20/v01/p2-P-H002-self/candidates/planning-000.py)、[self新源码](../../artifacts/inference-policy/2026-10-20/v01/p2-P-H002-self/candidates/planning-001.py)、[checked新源码](../../artifacts/inference-policy/2026-10-20/v01/p2-P-H002-checked/candidates/planning-001.py)。

self保存完整事实集合，可同时保留多个carrying事实。两道公开题都返回11动作且全部合法、无剩余目标，全批通过10/10。checked也搜索出了11动作，但其`_fmt`第86行是`"(" + " " + " ".join(...) + ")"`，产生`( walk ...)`。本项目宿主执行器的预检查正则要求左括号之后立即是动作名称（不是对VAL原生空白语法的结论）；公开两题记录均为`operator_syntax`、首错index0、实际执行0动作、全批0/10。这是明确观察到的最早失败；没有去掉空格重跑，不能声称剩余算法必定10/10。参见[执行器语法检查](../../rsi_eval/planning.py)、[checked诊断](../../artifacts/inference-policy/2026-10-20/v01/p2-P-H002-checked/diagnostics.json)。

这里再次出现“预测正确但没有完成任务”：checked登记的是problem0的**plan_length增加≥5**，实际增加11，故预测supported；它不是任务成功预测，11个未执行动作不能算任务改善。self的说明预测成功增加，但实际登记ID指向动作负效果事实，无法作为数值预测注册；结果schema_invalid，不能因最终10/10事后补成预测成功。[checked审计](../../artifacts/inference-policy/2026-10-20/v01/p2-P-H002-checked/audits.json)、[self审计](../../artifacts/inference-policy/2026-10-20/v01/p2-P-H002-self/audits.json)。

成功也不认证整段解释：self称原分层frontier实现退化成DFS，但旧代码逐层生成`nxt`，这是分层BFS；它也笼统说旧人/螺母/工具位置都取a[1]，实际螺母和工具位置此前已经取a[2]。checked承诺加入“入口别名”和“greedy/serial fallback”，实际提交只有get_plan的BFS，没有所称别名或贪心后备。这些是未由本轮4命题检查覆盖的新说明错误。

p2两份新规划诊断trace均达到20,000事件上限而截断，`get_plan`的return_events为0不能解释为没有返回；外部结果和plan_replay已实际取得计划并评分。不要用截断trace否认成功或返回行为。

## S-poly5：追加与替换是两种不同函数族

父式基函数为x、v、x³、v²、x⁵。self新增v³，5→6参数，训练NMSE下降0.0015132655690959645。checked把v²替换为`v*abs(v)*abs(v)`，即实数上的v³，保留5参数，NMSE下降0.0014209280166925797。因此self略低的训练误差还伴随一个额外自由系数；这不是等复杂度公式比较，也不是两个独立方程。[self源码](../../artifacts/inference-policy/2026-10-20/v01/p1-S-poly5-self/candidates/symbolic-001.py)、[checked源码](../../artifacts/inference-policy/2026-10-20/v01/p1-S-poly5-checked/candidates/symbolic-001.py)。

二者都使最高有符号v分箱的RMSE下降，但最高有符号x分箱RMSE反而上升：父本0.02338814→self0.02580247/checked0.02535159。全局改善不能解读为各局部区域都改善。二者理由把有符号v分箱直接叫作“最高|v|分箱”，并没有真正按绝对值重新分箱；对幅值依赖或物理阻尼的判断仍只是候选解释。self也在解释中列举了全部8条规则，虽然当前真正选中的是R03/R04/R06/R08；actor能见到完整8条目录，不能据其提及规则就断言该规则是本策略新增效果。

self主张NMSE<0.09而父本0.09376230，checked主张父本RMSE严格小于自身相同数值0.020226424138122107，均contradicted。两者登记NMSE下降≥0.005，实际均不足。[self审计](../../artifacts/inference-policy/2026-10-20/v01/p1-S-poly5-self/audits.json)、[checked审计](../../artifacts/inference-policy/2026-10-20/v01/p1-S-poly5-checked/audits.json)。

## S-odd4：很小的训练收益不支持重新叙述物理机制

self保持4参数，把速度项`v*abs(v)`替换为`v*exp(-abs(v))`；checked保留原4项，再附加第五项x⁵。self NMSE下降0.00009002399268544925；checked下降0.0000007180197444944802。二者公式不同，但如前所述其完整请求和策略相同，不能把具体公式形状归因于检查条件。[self源码](../../artifacts/inference-policy/2026-10-20/v01/p2-S-odd4-self/candidates/symbolic-001.py)、[checked源码](../../artifacts/inference-policy/2026-10-20/v01/p2-S-odd4-checked/candidates/symbolic-001.py)。

self从总残差分箱推断“原速度项在大|v|过度预测阻尼”，并不具备分离各项贡献或控制相关变量的证据；最多是假设。它提到“对应”x分箱也有最大RMSE，但仅有两个边际分箱统计，不能将两箱自动视为同一批样本。checked称残差随|x|增长，引用的却是最负x到最正x的有符号分箱，而且原4个x分箱RMSE为0.01381、0.02158、0.01696、0.02565，并非单调。该证据不足以认定缺少五次刚度项。新式的正训练增益也不证明真实物理必要性。

checked说明写预测NMSE下降0.004，实际结构化登记是0.003；按事前登记评估，实际约7.18e-7，仍contradicted。self登记**MSE**下降3e-5，实际仅3.927970702734913e-7，不能拿NMSE下降量与此阈值比较。checked的窄主张父本NMSE<0.095确实supported，但这只认证该不等式，不认证其“幅值依赖刚度”解释。self主张最高v箱RMSE<0.0285与实际0.029564664082667107冲突。[self审计](../../artifacts/inference-policy/2026-10-20/v01/p2-S-odd4-self/audits.json)、[checked审计](../../artifacts/inference-policy/2026-10-20/v01/p2-S-odd4-checked/audits.json)。

## 汇总与下一步证据需要

8条新候选主张：1 supported、5 contradicted、2 schema_invalid。8条事前预测：1 supported、6 contradicted、1 schema_invalid；7条成功登记，另1条注册unavailable。这唯一supported预测是计划长度，不是成功率。窄主张通过的公式也仍有开放解释越界；规划10/10的候选也仍有解释错误与无效预测。各层应分开统计。

本轮已可见三种明确断层：策略判断符合预设证据契约，不代表actor会作可靠解释；策略相同，不代表再次生成同一程序；记录指标改善，不代表原解释机制已获证实。若继续研究，优先将actor的未来预测目标限制到明确质量指标，并针对具体修订意图事先定义可执行检查或最小干预。但不能修改本轮预测计分、删除接口失败候选，或以本轮同策略的生成差异宣称检查有效/有害。
