# Grounded policy development: archived input provenance

日期：2026-10-20。本目录只补齐既有诊断证据，没有执行候选、增加模型调用或生成新分数。

`pilot-symbolic-003-feedback.json` 是原始
`runs/diagnostic-checks/20261020-diagnostic-probe-v01/feedback/073.json` 的逐字节副本，
复制来源为本机 `tmp/diagnostic-evidence/` 下已下载的同名运行文件。
SHA-256 为 `ed849fd17ccafa807637be37d3617afe926d26efb1da88471777786260ff4fda`。
这是后续**原件重放的反馈**，不是最初 pilot 生成时的原始反馈。

该文件绑定模型源码 `artifacts/pilot/2026-10-20/symbolic-003.py`，SHA-256
`f3c893f0989dc6a72029687090cd1e3c444eca24e8643740a0a62dddd21d801e`，
评价 ID `d6c079a6fc3341b6ae87b1d59b61c754`。四参数公式为
`-k*x-c*v-d*x**3-c2*v*abs(v)`；无符号约束的自由参数不保证其为物理耗散模型。
train MSE 为 `0.00040056676206938317`，NMSE 为 `0.09180470524756017`。
这两项分数与原模型记录一致，诊断使用同一 oscillator1/train 的 10,000 行。

原模型身份取自 `docs/environment/2026-10-20-agent-pilot-verification.json`
（SHA-256 `a4df3771754340b7a4872a5e8aaa07bcc45c6d5da777bbf8f0e53b5f012a6453`），
JSON pointer `/session_outcomes/1/trajectory/3`；原评价 ID 为
`a8019bf73a40470f9d61dd196b2e0821`。该精简记录不含 results 和诊断。
装载器保留原模型身份、参数数目和理由，经核对同分后，以本目录的后续重放结果
组装可供控制器复制的 record。provenance 同时保存两种评价来源，不能把重放 ID
改写成原评价 ID，也不能将这次装载计为新评价。

原件未修改的其它证据：

- `artifacts/diagnostic-probe/2026-10-20/manifest.json`，SHA-256
  `04c30c81aa4f09d70a0e1b9fd991eac70be20b1980d0a87ca06ccf79c1509d97`，
  将此公式标为 `unchanged_model_candidate`。
- 同目录 `summary.json`，SHA-256
  `f640388066df7211d916f33e1590bcb0e2bfab55f508afc7f5bfe2a52be700b4`，
  保存当时重放的同分和残差摘要。

## 本轮四个固定修订起点

装载实现和完整来源哈希见 `rsi_eval/grounded_states.py` 的 `PINNED_STATES`。
固定输出顺序为 P-A002、P-B002、S-poly5、S-odd4；状态 ID 是本轮标签，
不是新任务、随机种子或新的模型采样。程序只读取所列来源，核对原记录、参数、
任务顺序、分数、诊断和源码的绑定；所有历史经验字段均为空，不向评价 Agent 提供
后来答案或整个历史轨迹。

| 状态 | 既有模型源码 | 起点表现 |
|---|---|---|
| P-A002 | `artifacts/diagnostic-comparison/2026-10-20/planning_A/planning-002.py` | 0/10；公开题为空计划，内部仅保存一把携带工具。 |
| P-B002 | `artifacts/diagnostic-comparison/2026-10-20/planning_B/planning-002.py` | 0/10；公开题执行七个合法动作，仍有两个目标未满足。 |
| S-poly5 | `artifacts/checked-feedback/2026-10-20/v01-stopped/symbolic_checked/candidates/symbolic-003.py` | 五参数 `x,v,x³,v²,x⁵`，train NMSE 0.09376229967010528。 |
| S-odd4 | `artifacts/pilot/2026-10-20/symbolic-003.py` | 四参数 `x,v,x³,v|v|`，train NMSE 0.09180470524756017。 |

## 谱系与解释边界

这四项均为研究者已经检查过的**开发修订状态**，使用同一批 Spanner seed0
两道公开题与八道开发题，以及同一 oscillator1/train；不属于封存集或独立任务。
两个符号公式族确有不同，不能将源码哈希不同本身当成统计独立。

- P-A002 属于 planning_A 信息历史，生成前已有 A001；其后成功的 A003 不开放。
  它与 U-P 的 checked-v02→paired 分支分离，但共享手写空计划根。
- **P-B002 是上一轮 E-P/B003 的信息前序。** 两者虽然都选空计划为 parent_id，
  B003 生成时已经看过 B002 的反馈。当前状态不包含 B003 或随后答案。
  P-B002 与 U-P 不在同一模型修订分支，不能据此说它独立于旧 E-P。
- S-poly5 来自 v01-stopped 的常数→线性→三次→五参数公式链；U-S 来自 v02
  的常数→线性→位置二次→paired绝对速度项链。没有相同模型源码祖先/后代，
  但常数根相同、线性祖先数学等价。
- S-odd4 来自最早 pilot 的常数→线性→三次→带绝对值速度项链，与 U-S/v02
  及 E-S/symbolic_C 会话分离；它和 S-poly5 也共享等价的线性、三次公式祖先。

符号侧两起点都正常执行；残差不为零不等于执行失败，也不足以识别缺失物理机制。
规划的“空计划”与“七步合法计划未完成目标”是不同外部失败现象，但内部原因仍需
区分源码解释、辅助轨迹观察和实际干预证据。候选原始理由是模型生成的待审查文本，
本装载步骤不认证其解释正确。
