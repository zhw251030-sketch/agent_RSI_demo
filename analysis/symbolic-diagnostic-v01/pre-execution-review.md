# 8 次符号诊断执行前独立审查

审查范围：只读设计、既有执行器/沙箱/工作器、角色元数据和既有候选源码。没有读取真实 CSV 数值，没有运行候选、拟合、模型或 Git。以下是实现约束，不是已完成实验的认证。

## 建议的最小执行结构

旧 `rsi_eval/sandbox.py:run_candidate` 使用自身 `__file__` 父目录作为挂载 `/runtime/rsi_eval` 的源，固定执行该目录的 `worker.py`。因此可在 `analysis/symbolic-diagnostic-v01/runtime/rsi_eval/` 放入逐字节复制的 `sandbox.py`、`worker.py`、`__init__.py`，只对新 `symbolic_worker.py` 增补记录。以独立 importlib 模块名加载新 sandbox 副本；不修改旧模块的全局值或 `__file__`。

这样能原样保留 bubblewrap 的 unshare-all、只读挂载、禁网、seccomp、CPU/内存/时间/输出上限、进程组清理和严格 JSON 传输。候选只在该沙箱执行。需要在冻结清单中记录新 runtime 全部文件与旧副本对应哈希，执行前检查副本确为原字节。`worker.py` 导入 `rsi_eval.symbolic_worker`，从 `/runtime` 的副本包加载；应使用实际 Linux 合成校准验证这一点，不能只靠宿主单测。

## 数据和历史门禁

优先复用 `RoleExecutor(role='evaluation', evaluation_gate=...)` 的 `prepare_task('symbolic', task_id)`，保留其门禁回放、路径/哈希、header、bytes、rows、有限值检查。必须再由诊断宿主限定 task_id 恰为 `stressstrain` 或 `bactgrow`、split 恰为 train；不要向 CLI 提供任意数据路径/任务/分割。

门禁来自已完成 observed v03 的真实 r1/r2 决策。原 gate 引用原运行路径；不能把归档 gate 复制到新目录后假定相对路径自动有效。门禁构造应明确原路径和哈希，并先回放再读取训练值。新记录标注这些是已经暴露的数据，不把它们描述为仍未见的后续评价。

元数据中的预期训练哈希：stressstrain `6b850acb3567b10ccadb0d57cda3d7926297846f30be35ca1bc258b1c135fa73`；bactgrow `e3c0cc688b4543652360bda708302f1134091fe18c119a2033f204a5826a49da`。封存 CSV 连数值或新哈希读取都不需要。

## 数学和拟合条件

实际既有源码没有输入标准化，只有 `np.asarray(...).ravel()`。新协议宜明确 `input_transform=identity`，避免“保持相同归一化”被误解为新增标准化。stress 原 7 参数按 `[c01,q0,q1,l0,l1,g,b]` 排列，直接 4 系数按 `[b,g*c01*l0*l1,g*q0*l0²,g*q1*l1²]`。两边 ones 映射一致；保留 `nan_to_num(nan=0,posinf=1e6,neginf=-1e6)`，但代数等价不能提升为任意非有限/浮点运算逐位等价。

bact 六条件统一 `nan_to_num`。旧 updated 的 `out/(1+abs(out))*(1+abs(out))` 需要明确不保留于共同表示，故这是结构复核，不是旧 14/15 字节重跑。共同前 11 项、三变量项以及 square drop0/1/2/3 的顺序必须冻结。

继续使用同安装版本的 `least_squares(residual, np.ones(n_params), max_nfev=100)`，记录 NumPy/SciPy/Python 和实际默认 method/jac/tolerance/loss/x_scale；若把默认值改成显式参数，要用安装版本的函数签名确认完全相等。不能给 direct4 或线性 bact 换线性解析解。相同参数数不保证相同实际矩阵秩，也不意味着无限样本容量已匹配。

## 回执和计数

诊断 worker 应原样保留优化器成功与失败时的 `success/status/message/nfev/njev/optimality/cost/x`（非有限值显式 null + 原因），并记录 initial params。优化器异常与 `success=False` 分开，失败不伪造终止消息或 NMSE。失败时可归档 last iterate，但不能把它升级为成功得分。历史失败不重解释。

每次成功拟合后仍用 fresh-process predict，只传 X 和 fitted params，不传 y/优化器对象；host 用旧 `symbolic.score_predictions` 重算 NMSE，SSE 用 `math.fsum((y-pred)**2)`。评分来自 fresh prediction，不接受 worker 声称的 score。`nfev` 不包含 SciPy 所有有限差分调用，保留实际 `candidate_calls`。若新增 initial/final 检查调用，分别计数，不混称为求解器调用。

冻结的 8 位置固定顺序、source hash、参数数、初值规则、数据 hash、worker+host hash、依赖版本、资源、停止规则和结果目录。位置在派发前写 once journal；新目录原子创建且存在即拒绝；不提供 resume/overwrite/retry。合法候选或优化失败作为该位置结果保留并继续，基础设施/记录完整性/数据门禁失败停止，剩余位置显式 not_started，不补抽。不可捕获所有异常后默默继续。

旧 `prepare_runtime` 每个 sandbox 启动都会执行一次 max_nfev=2 的人工 warmup。真实计划是 8 次 benchmark fit，成功时另有 8 次 fresh predict；这些 bootstrap warmup、校准拟合、合成映射验证都应各自计数，不能统称系统只做了 8 次优化器调用。模型调用/S/权重更新/封存执行均为零。

## 关键校准

用人工构造输入验证 stress 任意有限参数映射和初始预测；bact 所有条件的共同项顺序、drop 索引、14/15 参数及初值。合成拟合用已知可解目标验证 status/message、nfev/calls、拟合参数和 fresh-process host score；用非收敛模拟或短上限人工例验证失败元数据不丢失、不产生成功分数。使用真实 Linux sandbox 验证网络/写文件拒绝和 copied runtime 来源。

执行后只读回放 8 个位置、source/receipt 哈希、两训练文件哈希、原 258 文件和 v03 档案，报告全部 8 行而不择优。单次训练结果最多支持参数化、特征替换和增项的数值观察，不能支持稳定优化优势、预测泛化、策略学习效果或 RSI 机制有效。
