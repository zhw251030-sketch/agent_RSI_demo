# v02 holdout 失败与 v03 真实 replay 交叉审计

日期：2026-10-26  
范围：最终 holdout 失败审查、v03 真实 proposal 与 `outcome_dev_v2` proxy 记录。  
性质：只读事后分析；没有修改 holdout、阈值或历史动作。

## 对齐关系

v02 最终 holdout 的 4 个残余 OOD 有害部署全部来自开发阶段 `supported`：

- `bactgrow-p02-r2`：OOD ΔNMSE `+0.120225`；
- `stressstrain-p03-r1/r2`：OOD ΔNMSE `+0.168057`；
- `oscillator2-p01-r2`：OOD ΔNMSE `+0.013170`。

v03 真实轮是另一批 proposal，但覆盖同样的四个任务和对应的三类输入 shift proxy。它不能被当作 holdout 失败 proposal 的重新评测，只有结构和任务层面的机制对照意义。

## v03 对失败模式的覆盖

| 失败模式 | v03 对应证据 | v03 动作 | 判断 |
|---|---|---|---|
| bactgrow 范围扩展 | `bactgrow-p01-r2` 为 contradicted，proxy ΔNMSE `-0.013329` | retain | 没有直接覆盖 holdout 的 `p02-r2` supported 失败 |
| stressstrain 温度条件塌缩 | `stressstrain-p01-r1/r2` supported，proxy ΔNMSE `-0.134319` | v03 allow_after_validation | proxy 允许恢复，但不能解释真实 holdout `p03-r1/r2` 的 OOD 退化 |
| oscillator2 时间窗口切换 | `oscillator2-p01-r1` supported，proxy ΔNMSE `-0.017704`；`p01-r2` supported，proxy ΔNMSE `+0.116023` | 前者 allow，后者 retain | 直接捕获了与 holdout `p01-r2` 同一 proposal 标识的有害方向 |

因此，v03 当前最强的证据是 oscillator2：同一 `p01-r2` proposal 在 shift proxy 上被 outcome gate 保留。stressstrain 的证据相反：v03 synthetic condition-collapse 使用原训练目标复用，候选改善，但真实 holdout 的温度固定同时改变了响应关系，说明该 proxy 没有重现真实 OOD 机制。

## 机制结论

- v03 相对 v02 的安全拦截新增数为 0；v02 已经拦截了本轮唯一的 proxy harmful proposal。
- v03 相对 v02 恢复了 3 个 supported 候选，显示 shift gate 的保守机会成本可以被 outcome 复核降低。
- v03 不能据此证明 stressstrain 的 OOD 可靠性；当前 synthetic fixture 与真实 OOD 的目标关系不同。
- contradicted evidence 仍具有优先级：即使 oscillator1 的 proxy 候选改善，v03 也不会用 outcome 分数越过 contradicted 状态。

## 下一开发协议

下一版不再只依赖手工输入变换。只使用训练文件，从 `fit_dev_v2` 建立输入分位数分箱，再按输入分箱组合的确定性哈希构造自然 domain-blocked outcome。目标值来自真实训练行，因此不需要复用变换前目标值。对每个 supported proposal 同时报告 ordinary outcome 和 blocked-domain outcome；只有两者都改善才允许在 shifted 状态执行。该协议需要在使用前冻结分箱数、哈希分块规则、最小样本数和改善阈值，不能用最终 holdout 调整。
