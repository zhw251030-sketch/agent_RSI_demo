# measured-v03：r1 已完成评价的只读核对

2026-10-21 运行记录。初稿仅核对已完成的 `r1-evaluation-P-eval-1-{fixed,updated}` 与 `r1-evaluation-S-bact-eval-1-{fixed,updated}` 四个槽，以及对应冻结 context；第 5 节在 P-eval-2 两臂完成后追加。合计只读六个已完成槽，未读取正在执行的 stress 或后续 r2 评价；未调用模型、执行候选、拟合或重评分。

以下路径相对项目根目录，省略共同前缀 `runs/strategy-pair/measured-v03/experiment/`。

## 1. 最重要的归因边界

本文六个槽的实际测量中 `strategy_version` 均为 S0 哈希：

`9937882539c30e7e519bf5251c14b35b29b84b23bb6f506077bdad39d3438445`

前三节两对真实请求分别核对共同 actor packet、除用户 packet 外的请求模板、repair_policy，三项均相同；第 5 节新增配对的完整请求文件也逐字节相同。r1 的选择结果保留了 S0，所以这里名为 fixed/updated 的两臂实际上是**同一策略、相同输入的两个模型采样**。下述差异不能归因于策略改进。

## 2. P-eval-1：两臂均 0/63，发生不同的源码错误

依据 `bound-sessions/r1-evaluation-P-eval-1-fixed.json` 和 `...-updated.json` 引用的全部结果：

| 臂 | 63 道 evaluation 任务 | 定位 |
|---|---|---|
| fixed | 63 次 candidate_error / NameError | source.py 第 293 行 |
| updated | 63 次 candidate_error / KeyError | source.py 第 115 行 |

fixed 源码哈希为 `3242c3314c112b0bb979813a28d4cd08891ce4654914ad8d78cb24c4e7849947`；updated 为 `0ed38074463245e3f7da292cc59da1b2b34a0d0a67e12961dd2951e7cd46ccea`。

- `sessions/r1-evaluation-P-eval-1-fixed/source.py:293` 在 `_walk_path(src, dst, links)` 内用 `man` 格式化 walk。`man = men[0]` 定义在另一个内部函数 construct 的局部作用域（第 199 行），并未作为参数或闭包变量传给 `_walk_path`。静态作用域问题与 63 条 NameError 定位相符。
- `sessions/r1-evaluation-P-eval-1-updated/source.py:112` 找到目的地时才建立 `parent = {nb: cur}`，前面的 BFS 没有保存整个父节点链。第 115 行继续重建多跳路径时查找缺失键，符合 63 条 KeyError 记录。
- `sessions/r1-evaluation-P-eval-1-updated/requests/request-0022.response.json` 声称修订 `“keeps the ten observed successes intact”`；这些十题是 context 中的 learning 任务，模型没有执行修订稿来支持该保证。fixed 的 `request-0021.response.json` 同样声称保守、行为保持并保留 BFS 回退，但新构造器异常发生在回退前。

`contexts/P-eval-1.json` 中旧起点 learning 10/10 成功；当前终稿测的是另一个 evaluation 63 题集合。因此不能把 10/10→0/63 作为同题重测的退化量。可以确认的是：两份新终稿在本轮 63 道后续任务上均未产生有效结果，解释中的行为保持尚无相应证据。

## 3. bactgrow：训练拟合分数确有差异，但同策略、参数量也不同

依据 `contexts/S-bact-eval-1.json` 和两份 `bound-sessions/r1-evaluation-S-bact-eval-1-*.json`：

| 对象 | 参数数 | train MSE | train NMSE |
|---|---:|---:|---:|
| 冻结起点 | 7 | 0.016493488944562467 | 0.8503733599018976 |
| fixed 终稿 | 8 | 0.016679449559615107 | 0.8599611404838751 |
| updated 终稿 | 12 | 0.015600311502324351 | 0.8043228059470892 |

两份终稿都已接受并完成拟合。fixed 比起点多一参数且误差更高；updated 比起点多五参数且训练误差降低。updated 相对 fixed 的 NMSE 差为约 -0.0556383345，增加四参数；按固定目标规则属于精度收益而非简化，但这里不是不同策略的机制比较，也不是封存测试上的预测泛化。

fixed 源码哈希为 `ed997a93fc95f08d6d991974138eb68eeb17e2edc59862b19db6b4ec53141492`；updated 为 `96afd970ef2268ec9983cced418b21baf6ddc084a87b3a1eb0e78f8ed6828780`。

**fixed 的代数解释有直接错误。** `sessions/r1-evaluation-S-bact-eval-1-fixed/requests/request-0024.response.json` 将基线缩放描述为 `“a non-identity nonlinear map that compresses large responses”`。基线实际为：

```python
scale = 1.0 + np.abs(out)
out = np.clip(out / scale, -1.0, 1.0) * scale
```

对有限实数、忽略浮点误差时，`abs(out/(1+abs(out))) < 1`，clip 不改变值，再乘 scale 恢复 out，因此代数上是恒等变换。大幅压缩以及“can only hurt”的判断不成立；本轮没有数值条件或梯度诊断来证明浮点影响。

**updated 对恒等关系的描述较准确，但其他因果说法未被验证。** `sessions/r1-evaluation-S-bact-eval-1-updated/requests/request-0023.response.json` 说缩放 `“algebraically a no-op for finite values”`，与上述代数一致；同时声称数值噪声/条件影响，但没有相应实验。它新增线性 u3、平方项、交叉项和 tanh 压缩，并提高参数数，多项变化同时发生，不能将训练下降归因于某一个解释。

基线的线性部分确实没有单独 u3 项，但原表达式已有 `u2*u3`，所以不能说整个模型没有利用第四输入。fixed 添加线性 u3，换为八参数线性/二次特征组合；updated 保留原三次混合项并添加更多项，总十二参数，再作 `8*tanh(out/8)`。这些源码修改与主要结构声明相符；所谓“噪声被吸收”“起始时近共线”“更好条件”等仍是未验证推测。

## 4. 当前可写结论

同一固定策略、相同上下文的重复调用可以产生差别明显的程序与符号公式。正确描述或看似合理的解释都不能代替执行；参数扩容及多个结构变化也使单例训练收益无法直接定位机制。此处不提前合并尚未完成的其他评价槽，不改变任何运行记录。

## 5. P-eval-2：相同完整请求产生 0/63 与 63/63，不能计为策略收益

本节只在 `bound-sessions/r1-evaluation-P-eval-2-fixed.json` 与 `...-updated.json` 均完成后读取；两份 bound session 引用的 126 个结果文件逐一通过自身记录的 SHA256 校验。两臂对应的 63 个 task_id、数据/域/分区/评价器哈希、评价门哈希和资源限制均逐项相同。

| 臂 | 真实请求记录 | 63 道 evaluation 任务 | 接受源码 SHA256 |
|---|---|---|---|
| fixed | `sessions/r1-evaluation-P-eval-2-fixed/requests/request-0025.request.json` | 0/63；63 次 invalid_output / unknown_operator | `be6bf79fde8fcf2fd50196a75bc6137424fc988fd13c9aaa9b845c0a95c02286` |
| updated | `sessions/r1-evaluation-P-eval-2-updated/requests/request-0026.request.json` | 63/63；63 次 VAL valid | `5ed5c9ba44123ff98e1f56b127043f021a159b78475b20dfe06b8e9de4779df9` |

上述两份完整请求文件均为 25,904 字节，SHA256 均为 `f76f9a0634dc7f661d97a48d97ab21b5bb030ecb452a4afefdee6abbe9a49096`，直接字节比较为相同。两臂全部测量使用第 1 节的同一个 S0 哈希；因此不仅共同部分相同，保存的整个模型请求内容也相同。请求号、响应与采样结果不同，不构成策略内容差异。

**明确缺陷是 fixed 创造了域中没有的动作，不是括号格式不同。** 两份源码的 `_fmt` 函数体完全相同，均输出括号包围的动作串。fixed 的 `sessions/r1-evaluation-P-eval-2-fixed/source.py:83` 定义 `do_drop`，第 92 行实际追加 `drop_spanner`；第 241–246 行 `drop_all` 调用它，第 268、283 行在尝试拧紧后调用 `drop_all`。对应 `contexts/P-eval-2.json` 的公开域只定义 `walk`、`pickup_spanner`、`tighten_nut` 三种动作，没有 `drop_spanner`，也没有“已持有用坏的扳手会堵住位置/妨碍再次拾取”的前提。

fixed 的 `sessions/r1-evaluation-P-eval-2-fixed/requests/request-0025.response.json` 明确解释：`“drops the now-unusable spanner so it does not block the location for later pickups”`。这个新增动作和阻塞假设没有公开域依据。63 个结果的 `first_invalid_action` 分别为索引 6（17 题）、7（22 题）、8（24 题），全部在进入 VAL 前被拒绝为 unknown_operator。静态源码仅有上述一个未定义动作名，这与运行记录相符；没有修改源码后重跑，因此不能声称“只删 drop 就能通过 63 题”。贪心路线、用具获取与剩余目标处理还可能有其他问题，本次没有作消融。

**updated 改成完整状态搜索，其成绩有实际 VAL 支持。** `sessions/r1-evaluation-P-eval-2-updated/source.py:50` 的动作空间只列上述三个域动作；第 70 行 effects、第 89 行 preconditions 对应公开域，第 118 行实现初始 delete-relaxation 可达性筛查，第 184 行起作 BFS，最多 400,000 次状态展开、1,000 步计划。真实 63/63 仅证明该终稿在本轮这 63 道允许评价题上的有效性；本次没有证明任意规模效率、全部 Spanner 实例完备性或最优性。

两份解释都正确引用了旧起点 learning 十题返回空计划的症状，也都提及旧源码 `_restore` 中的 `global state`。该语句确实存在于 context 源码第 265 行，但本轮没有针对这个原因作干预验证；updated 在 `request-0026.response.json` 用 `“Hypothesis (not verified)”` 标注原因，边界更准确。fixed 所说 operator-definition gap 与自己创造新操作的行为不能被真实旧失败记录证明。

可直接复核的首题记录（下列路径相对项目根目录，不使用本报告共同前缀）：fixed 为 `runs/role_executor_feedback/0f14b1bdfee7410896cd326d4a557938/result.json`，updated 为 `runs/role_executor_feedback/40a83b36c88e406e95d73543d9774463/result.json`；同为 `spannerlearning/seed3/problem0`，分别返回长度 8 的非法计划和长度 11 的 VAL 有效计划。

**归因结论：** 0/63 与 63/63 是同一策略、相同模型请求下两个不同程序的同题差异，支持“生成产物的波动可非常大”，不支持 learned S* 相对 S0 的机制优势。旧起点是另一个 learning 十题上的 0/10，不能将 0/10→63/63 报成同题收益；本轮也没有执行官方封存测试。
