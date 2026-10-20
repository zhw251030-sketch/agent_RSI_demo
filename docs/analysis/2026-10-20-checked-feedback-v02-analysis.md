# 可执行主张检查 v0.2：实际提交、预测与解释的逐条审查

日期：2026-10-20。运行：`20261020-checked-feedback-v02`；运行代码提交：`e298713f575ea04d99984a32fc4c1f6dfbc6a5ce`；OpenHands SDK：1.55.1。

**性质：知道条件和结果后的描述性开发轨迹审查，不是盲评、解释准确率估计或方法效果检验。** 本文逐条区分记录中的事实、检查器实际核对的谓词、源码实现和更宽的语言解释。自由文本理由、代码注释和最终总结都是审查对象，不能直接作为研究结论。

## 1. 证据范围与版本边界

本次检查了完整原始安全副本的 97 个文件，包括运行摘要/账本、各会话 `candidates.json`、`audits.json`、`evidence.json`、实际候选源码、请求/响应、状态包及事件记录。候选文件的 SHA-256 已逐一与候选记录核对。正式入口为[证据归档说明](../../artifacts/checked-feedback/2026-10-20/v02/README.md)、[请求—执行索引](../../artifacts/checked-feedback/2026-10-20/v02/request-index.json)及[97文件来源清单](../../artifacts/checked-feedback/2026-10-20/v02/manifest.json)。归档将原始`candidates.json`整理为`trajectory.json`，摘要为派生版本；源码和安全响应保留原始字节，未复制的完整输入由清单记录哈希与映射。原始定位根目录为项目下 `runs/checked-feedback/20261020-checked-feedback-v02/`；下文原始文件名按此定位。审查未重新执行候选、调用模型、读取凭据、符号原始数据行或封存集。

v0.2 是[独立接口修复轮](../protocols/2026-10-20-checked-feedback-v0.2.md)，不是恢复 v0.1。v0.1 的额外结构观察器错误处理 SDK 的 `summary/security_risk` 外层字段，已停止并保留原记录；本轮修复外层参数规范化和公开工具 schema，重新从原弱起点运行。新轮经验已受旧轮调试影响，不能称为独立于开发的新状态验证。检查核心、任务范围、评分/选择规则与[原协议](../protocols/2026-10-20-checked-feedback.md)一致：hidden/checked 都提交声明并计算检查，只有 checked 显示检查结果；语义检查不阻止执行，也不参与选优。

“工具结构有效”“语义主张通过”“候选执行成功”“会话结束”是不同事件。例如 `response_tool_validation=valid_submission` 允许声明进入核心检查器，随后仍可得到 `schema_invalid`；SDK `FINISHED` 也不保证曾执行候选。

## 2. 四个会话实际发生了什么

| 会话 | 请求数 | 工具结构有效且实际执行的子候选 | 执行后的结果，按候选顺序 | 会话终态与完整性 |
|---|---:|---:|---|---|
| planning_hidden | 4 | 1 | planning-001：0/10，未采纳；保留空计划起点 | stopped；SDK ERROR，事件为 MaxIterationsReached；无执行后的模型总结 |
| symbolic_checked | 4 | 3 | NMSE 0.0969402096 → 0.0963921700 → 0.0950556636；三者均采纳 | completed / FINISHED；第四请求为文本总结 |
| planning_checked | 4 | 2 | planning-001、002 均10/10；001采纳，002同分未采纳 | completed / FINISHED；最后显式调用 finish |
| symbolic_hidden | 1 | 0 | **没有模型生成候选的实测成绩** | completed / FINISHED；响应标注 tool_calls，但没有实际 tool_calls 字段 |

四组起点均已评价。规划起点为空计划、0/10；符号起点为一个常数参数、train NMSE=1.0。同族初始观测哈希相同，运行摘要 `initial_observations_match=true`。**symbolic_hidden 的 NMSE=1.0 只是共同起点，不是 hidden 方法完成搜索后的成绩。** planning_hidden 也不是三次修订均失败，而是前三请求未进入候选执行、第四请求才执行一个子候选。

运行总状态为 `completed_with_stops`，账本13次请求、105,932 tokens，usage全部已知；按配置价格估算0.3446898 CNY，保守预留1.3346382 CNY，均不是账户账单。请求输入实际17,044–36,996字节，未触及98,304字节上限。本轮没有新增未知用量，但不能因此清除历史轮次仍未知的费用。包括四份起点在内，共十份实际源码、55条任务执行记录（50条规划、5次符号训练拟合）；这不是55个独立机制实验单位。封存评价0、策略S更新0。

结构校验拒绝共4次：planning_hidden的请求0001–0003、planning_checked的请求0009。已记录工具参数含额外顶层业务字段，或把嵌套内容打散成多个带`$text`/`item`的claims条目。它们消耗请求额度，没有产生候选执行记录，也不应填入主张通过率分母。保存的是SDK/LiteLLM侧标准化响应；仅凭这些文件不能判定不正常嵌套究竟来自模型原始生成还是更上游的协议解析转换。

## 3. 所有已执行候选的主张与预测

以下全部指标取自该会话自己的证据绑定；不同会话即使使用相同 candidate_id，也不是同一条记录。“支持”只表示指定谓词在指定绑定下成立。

| 会话/子候选 | 提交前引用与主张 | 官方检查结果 | 预测及实际子候选变化 | 采纳 |
|---|---|---|---|---|
| planning_hidden / 001 | 父000：fact `action.tighten_nut.effects.negative`，错误地使用eq和原子列表；scalar `plan_length==0` | schema_invalid；supported | total_successes increase≥2；0→0，Δ=0，contradicted | 否，同分保留000 |
| symbolic_checked / 001 | 父000：`bin.x.3.mean_residual>0.05`；`bin.x.0.mean_residual<-0.03` | supported；supported | NMSE decrease≥0.3；1→0.0969402096，Δ=0.9030597904，supported | 是 |
| symbolic_checked / 002 | 父001：`bin.x.2.mean_residual>0.002`；`bin.v.3.rmse>0.025`；两引用均缺session_id | schema_invalid；schema_invalid | NMSE decrease≥0.005；0.0969402096→0.0963921700，Δ=0.0005480396，contradicted | 是 |
| symbolic_checked / 003 | 父002：`bin.x.3.mean_residual<0.003`；`abs_bias<0.005` | supported；supported | NMSE decrease≥0.0005；0.0963921700→0.0950556636，Δ=0.0013365065，supported | 是 |
| planning_checked / 001 | 父000：fact `goal`，错误地使用eq和原子列表；scalar `plan_length==0` | schema_invalid；supported | total_successes increase≥8；0→10，Δ=10，supported | 是 |
| planning_checked / 002 | 父001：fact negative effects contains `["useable","$1"]`；`total_successes==10` | supported；supported | total_successes increase≥0；10→10，Δ=0，supported | 否，同分保留001 |

六个实际子候选共12项主张：9项scalar、3项fact；8项supported、4项schema_invalid，没有contradicted或unavailable主张。分类型看，scalar为7支持/2格式错误，fact为1支持/2格式错误。六项预测均在执行前成功登记，4支持/2反驳。

这些计数不能写成“解释准确率66.7%”或“检查提升了准确性”。主张由模型自行选取，覆盖窄且可平凡化；两个主张的支持也不能认证同次提交的整段理由。预测支持不是严格改进的同义词：planning_checked/002的零阈值只检验未退步。它未被选中，但核验仍用实际002的10分，而不是拿best替代子候选；这是本轮真实出现的未采纳子候选核验。symbolic_checked的三个子候选全部采纳，没有该分支的符号实证。

## 4. symbolic_checked：窄谓词正确，符号与对象解释仍可错误

证据：[完整轨迹](../../artifacts/checked-feedback/2026-10-20/v02/symbolic_checked/trajectory.json)、[检查](../../artifacts/checked-feedback/2026-10-20/v02/symbolic_checked/audits.json)、[可引用证据](../../artifacts/checked-feedback/2026-10-20/v02/symbolic_checked/evidence.json)、`candidates/symbolic-000.py`至`symbolic-003.py`，以及请求0005至0008响应。原始源码顺序是：**常数（1参数）→ x+v（2参数）→ x+v+x²（3参数）→ x+v+x³（3参数）**；所有系数都由可信拟合过程拟合，不能把自由系数的符号等同于模型语言里的物理判断。

### 4.1 001：残差方向引用准确，对目标趋势的符号解释反了

常数起点的残差定义明确为`prediction - target`。x四箱均值为−0.06688509、−0.04430450、0.02267531、0.08851428；001只提交了两端阈值，实际检查正确支持它们。这些观测对发现常数模型的缺失结构有相关性，但两端阈值本身不证明全区间线性，也不识别v的独立作用。

其理由却说该趋势“strongly suggesting the target has a positive linear dependence on x”。常数预测为c时，箱内均值满足`E[target | 箱] = c - E[residual | 箱]`；因此这里上升的残差均值对应**下降**的目标均值，而非正向依赖。这个符号错误无需查看真方程即可核对。

实际两参数线性式将NMSE从1降至0.09694021，说明这一个拟合形式在这些训练点上大幅减小误差。自由拟合系数可以吸收正确方向，故程序改善与理由中的符号误判能够同时存在。没有分别去掉x/v的对照，不能把下降独归某一项，也不能用成绩反向证明正向关系的说法正确。

### 4.2 002：数值线索存在，但漏绑定、读数错误与噪声判断应分开

两项引用均遗漏session_id，官方结果为`reference_schema_invalid`，不能事后补字段改判。离线审查父001可见其拟引用数值确为`bin.x.2.mean_residual=0.0030974844`、`bin.v.3.rmse=0.0324718170`，分别满足0.002和0.025阈值；这只说明其数值摘录有依据，不消除绑定错误。

理由称最高x箱的均值最小，实际父001四箱为0.00227079、0.00060042、0.00309748、0.00219485，最小的是第二箱。最高v箱均值0.00265217，也不是v箱最大均值，第二箱0.00562706更大。高v箱RMSE较大是实测事实，但并不直接推出应该加x²，更不能排除其他遗漏项、输入相关性或异方差等解释。

加入x²后NMSE只下降0.0005480396，低于事前0.005阈值，因此预测被反驳；模型仍因训练误差略降而被采纳，两者不矛盾。“mostly like unstructured noise”未经过检验，不能从少量边际分箱或一次小收益推出不可约噪声。

### 4.3 003：单箱不等于所有箱，阈值成立不认证物理解释

003将x²换成x³。其理由明确将“quadratic x² term”称为“odd in x”，这是数学错误：x²为偶函数，x³为奇函数。代码确实实施了幂次替换，不能因这处理由错误就否认源码变化或实测的小幅改善。

第一项正式主张仅为父002的**一个有符号均值**`bin.x.3.mean_residual<0.003`，实际−0.0001638328；它既没检查绝对值，也没检查其他三箱。因此不能把supported扩大成“全部x箱绝对残差均小于0.003”。父002四箱的真实绝对均值恰好都在该范围内，属于另行读取全部数值得到的事实，而不是这条谓词的覆盖范围。

第二项仅为父002的`abs_bias<0.005`，actual=0.0007975487。它不直接检查“偏差相对MSE很小”；若要量化后一句，需使用同量纲的`bias_squared_over_mse`。父002该比例实际为0.0015123862，即约0.151%，但模型没有把这个比例登记为本次主张。两条都是正确而有限的观测，不是x³物理必要性的证明。

实际子003的NMSE下降0.0013365065，超过事前0.0005；预测成立。该结果是当前训练拟合的改善，没有区分奇次结构原因、优化偶然性或其他能取得相近改善的替代形式。

### 4.4 请求0008总结：分数基本正确，候选身份和主张绑定发生串用

最终状态包`packet-0004.json`只保留当前003的完整可读源码；旧候选001/002保留分数、哈希、声明等摘要，没有完整源码。模型说无法重读001/002源码，是实际上下文限制。但应据此保留不确定性，不能补写错误身份。最终文本见[请求0008响应](../../artifacts/checked-feedback/2026-10-20/v02/symbolic_checked/requests/request-0008.response.json)。

| 总结中的说法 | 与源码、检查或状态包核对 |
|---|---|
| baseline000是`p0*x+p1*v`；001加入x²、3参数 | 错。000是常数，001是2参数线性式；新增x²发生在002 |
| 002“没有有意义地改变公式族” | 002明确新增x²。可以讨论收益小，但不能用省略源码来否认实际结构变化 |
| 003“两项主张都支持：所有x箱均值<0.003，abs_bias≈0.00187” | 两项主张引用父002；第一项仅检查父002的最高x箱，第二项actual为0.00079755。0.00187是子003的偏差，发生对象串用 |
| 最终全部x箱均值<0.003，最大约0.00275 | 错。子003的`bin.x.1.mean_residual=0.0032721603`；0.00274912对应最高v箱均值，不是最大x箱均值 |
| schema_invalid之后没有再核验主张 | 错。003随后提交两项完整绑定的主张，结果都已展示在最后状态包 |
| 残差方差随\|x\|增长 | 超出证据。子003的有符号x箱RMSE依次0.01660、0.02297、0.01779、0.02322，既非单调，也不是按\|x\|分箱；RMSE也不能不加区分地直接称为条件方差 |

总结正确保留了NMSE的大致顺序、002预测未达阈值和训练范围限制。其最终`bias_squared_over_mse≈0.0084`也与子003证据一致，约0.844%的MSE来自均值平方。但这些正确部分并不消除同段中的身份、分箱和主张对象错误。**本轮直接观察到：正确分数、正确窄谓词与不准确的综合叙述可以共存。**

## 5. planning_hidden：主要损失发生在请求格式，唯一执行候选另有源码错误

证据：[完整轨迹](../../artifacts/checked-feedback/2026-10-20/v02/planning_hidden/trajectory.json)、[检查](../../artifacts/checked-feedback/2026-10-20/v02/planning_hidden/audits.json)、该会话请求0001至0004及对应input-audit、[事件](../../artifacts/checked-feedback/2026-10-20/v02/planning_hidden/events.jsonl)、[唯一执行子候选源码](../../artifacts/checked-feedback/2026-10-20/v02/planning_hidden/candidates/planning-001.py)。前三请求都未执行；第四次才进入工具执行。结束事件`MaxIterationsReached`导致SDK状态ERROR，外层如实记为stopped，没有`model_error_type`，不能写成服务商失败。

唯一执行候选实现了BFS及公开动作前提/效果，但所有十题结果均为`invalid_output/operator_syntax`，计划长度1。源码`fmt()`返回`walk ...`等字符串，没有要求的外层括号；回溯循环又在一次取父节点后设置`cur=(prev_state,None)`，因此只返回末尾一个动作。前者对应实际报错，后者是与观测长度1一致的静态缺陷；本次未修补或重跑，不能声称已实验证明分别修复后的效果。

其fact声明试图比较tighten的整个负效果集合，使用eq加嵌套原子列表，故`claim_schema_invalid`。集合里的loose/useable删除关系可以另行从公开契约核对，但不能写成该声明通过。另一项`plan_length==0`确实描述了空计划起点，解释信息量有限，不检查新程序的动作语法或回溯完整性。

成功数增加至少2的预测实测Δ=0，被反驳；子001未采纳。hidden组没有看到该检查结果，且没有第五次响应，因此无法观察它收到新执行反馈后的修复反应。四次请求用完而仅执行一次，也使其与执行三次或两次的其他组不能按“等候选数”比较。

## 6. planning_checked：10/10发生在首次语义反馈之前

证据：[完整轨迹](../../artifacts/checked-feedback/2026-10-20/v02/planning_checked/trajectory.json)、[检查](../../artifacts/checked-feedback/2026-10-20/v02/planning_checked/audits.json)、该会话请求0009至0012及两个执行源码。0009结构校验失败，没有执行；0010是该会话第一个实际执行候选planning-001，直接达到prompt 2/2、development 8/8。

**这次0→10的跃迁发生在模型看到任何本组主张检查结果之前。** 初始状态没有历史检查结果；结构错误反馈为两组共同提供的接口反馈，不能当作checked特有的语义检查干预。001使用公开任务、基础诊断和固定提示构造了可用BFS。相对于hidden这一次程序的差异，不能归因于先前不存在的检查反馈。

001的fact声明仍误用eq和整个goal列表，结果schema_invalid；`plan_length==0`支持；事前成功数增加至少8的预测实测增加10，支持。公共目标事实本身是真的，但“原子列表等于goal”的格式不属于本检查器支持的谓词。

请求0011明确注意到上次fact声明的schema_invalid，改为合法单原子contains：`action.tighten_nut.effects.negative`包含`["useable","$1"]`；这项检查支持，但核对的是公共动作契约，不能仅凭它认证程序在所有状态都正确执行。第二项只复述父001已经10/10。

002只增加`start==end`时跳过walk，把`max_steps`从900000提高到1500000，并把计划长度界限从900提高到999。实际仍10/10，计划长度与001逐题完全相同：11、11、10、10、12、12、11、13、11、10。没有性能测量或未见任务评价，不能将其写为效率、鲁棒性或泛化改善。源码中`steps`每轮BFS层循环增加一次，不是展开节点计数；调高该数值也不能直接表述为扩大了等量节点预算。

002预测用increase/min_delta=0表示不退步；actual是变化量0，不是总分10。预测supported但子002同分未采纳，best仍001。这同时展示了实际子候选与选中候选分开记录的机制，未展示检查带来进一步成绩提升。

最终finish准确说明同分保留001，但又称001“两项主张和预测都支持”，漏掉其fact主张的schema_invalid，并把002预测的“actual”说成10而非审计记录中的Δ=0。把同批10/10总结成“correctness-preserving”也只能限定于这批观察；未见实例正确性没有验证。请求0011正文称公开计划长度11和12，实际两道公开题均11；最终所说全十题长度10–13则正确。

## 7. symbolic_hidden：文本里的候选意图没有变成工具执行

该组仅有[请求0013响应](../../artifacts/checked-feedback/2026-10-20/v02/symbolic_hidden/requests/request-0013.response.json)。响应内容先讨论常数起点和残差模式，随后在普通content里拼接一段未完整闭合的候选JSON，意图使用`-p0*x-p1*v`。但标准化消息没有`tool_calls`字段，虽然choice的`finish_reason`写为`tool_calls`；SDK把会话结束为FINISHED，没有产生任何新增候选文件、audits或候选执行。归档中人为提供的空audits数组表示零条记录，不是原运行又进行了一次检查。

因此可以报告“模型文本表达了一个线性振荡器候选意图”和“工具调用未形成”，不能报告该候选的拟合分数、预测结果、是否被采纳，也不能把常数起点1.0作为hidden的最终方法成绩。该终态暴露了“SDK完成”与“研究任务完成”的差异；现有归档不足以定位缺失tool_calls的上游成因。本轮不追加请求补齐该组，避免事后改变同一轮预算。

## 8. 能支持的观察与不能支持的结论

1. **接口、执行和研究终点必须分开计数。** 本轮全部13请求都有usage，但只有6个子候选执行；两个规划会话的结构错误占用了不同数量的请求；symbolic_hidden完成了SDK会话而没完成产物搜索。完整矩阵保留这些差异，不能只挑有分数的条件。
2. **检查器成功核对有限谓词，不等于认证解释。** 本轮观察到漏绑定、非法fact操作、残差符号误解、x²奇偶性错误、父子候选对象串用、单箱扩大为全箱，以及正确数值拼接成错误历史。8项supported不是对这些自由文本的8次认可。
3. **预测有明确约束，但约束强度不同。** 两项未达阈值、一个零阈值平台预测、三项正阈值兑现都应分别保留；不能把“支持”直接相加成改进次数。预测兑现也未识别物理原因或修改机制。
4. **目前无法估计checked−hidden。** planning_checked首次执行已10/10，先于语义检查反馈；symbolic_hidden没有执行轨迹。执行顺序固定、没有重复、实际搜索长度不等，任务与起点参与过开发。即使表面分数有差异，也不能排名、估计因果收益或作显著性结论。
5. **全会话有界输入解决了本轮已见的长度问题，但压缩后的综合叙述仍须审计。** 最终符号总结省略旧源码后填入错误产物身份，同时忽略仍在状态包中的明确引用。该事件支持继续研究证据绑定、摘要覆盖与结论边界，不能单凭一次错误确定压缩造成了它，或认为恢复全部历史必然修复。

本轮只有产物P的若干开发修改，策略S固定；没有封存测试、跨任务迁移、自改写更新器或新方法有效性的证据。若继续研究，应另行冻结新版本与新父状态、独立选择/评价、实际执行覆盖和解释审查口径；本分析不追认新的实验预算，也不补跑或改写上述两轮记录。
