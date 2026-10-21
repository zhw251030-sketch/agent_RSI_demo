# 后续规划逐题耗时：已完成槽的只读诊断

范围仅为已完成的 `r1-evaluation-P-eval-1-fixed`。没有重新调用模型、执行候选、调用评价门校验或修改运行设置；只读取该槽 63 条已保存结果及截至该槽完成的事件。结果文件哈希前后相同。数据见 `strategy-v03-completed-slot-timing.json`，提取代码为 `diagnose_strategy_v03_completed_timing.py`。

63 条结果均为 `candidate_error / NameError`，但每次 sandbox 子进程均正常返回结构化错误，状态为 `completed`。没有任何 VAL 调用。sandbox 耗时中位数 **0.045132 秒**，范围 0.039302–0.075803 秒；不是每题等待 CPU 上限 10 秒或墙钟上限 20 秒。

连续测量事件间隔中位数 **7.443813 秒**，范围 6.384491–7.638702 秒。结果自身的 `elapsed_seconds` 中位数 **3.679436 秒**；其余约 3.762514 秒位于该计时器之外。首末测量相隔 451.669 秒，槽开始到完成共 487.743 秒。差值说明绝大部分时间发生在宿主校验，不能解释为候选自身运行缓慢。

源码显示后续评价的每一题会触发四次完整评价门验证：

| 调用位置 | 是否包含在结果 elapsed 中 |
| --- | --- |
| `strategy_pair_run.py` 的 `execute` 循环调用 `self.authorize(state_id)` | 否 |
| `RoleExecutor.evaluate` 入口 `_authorize` | 否，计时器尚未启动 |
| `RoleExecutor.evaluate` 创建凭据前再次 `_authorize` | 是 |
| `prepare_task` 调用 `_authorize` | 是 |

每次都经 `_check_gate → verify_evaluation_gate → _decision → bind_selection`，重新回放 r1、r2 两份策略选择。它重新核对选择基线、四个选择状态、八份终稿的源码/请求/测量、分配清单与运行依赖哈希，再计算选择结果并与冻结决定比较。按当前分配，一次 gate 校验检查两个重复共 204 条选择基线/终稿结果；每题四次约为 816 次 `_raw_evaluation` 验证。它们是读取旧记录，不是重做任务或重新学习 S，也不重新执行 24 条学习历史。

此外，每题还有宿主运行清单/模板冻结检查、任务文件哈希及解析和记录写入；槽开始与结束也有额外授权/结果绑定校验。`sandbox.py` 的 0.05 秒 selector 等待只负责读取进程输出，不构成固定 10 秒延迟。一次进程快照显示主 Python 进程累计 CPU 使用约 71.2%，与大量宿主 Python 校验相符，但快照不能独立分解函数耗时。

本诊断没有采样 profiler，也未重跑 gate；四次校验由静态调用路径确定，具体各次校验与文件系统的精确耗时尚未单独测量。后继版本可以研究在不可变证据快照上减少重复完整回放，同时保留每次任务访问前的有效授权和变化检测。本轮仍按冻结实现运行，不能中途优化或对 NameError 提前省略剩余任务。
