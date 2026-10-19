# 两类任务执行器实施计划

用户已要求继续完成上一轮提出的执行器、隔离与反馈准备。本轮以可验证的开发执行层为交付，不冻结科研方法，不调用模型，不执行封存测试。

**目标：** 同一入口接收候选源码、任务身份和版本信息，分别执行规划程序或拟合/评价公式，返回可追溯反馈。

**实现边界：** Bubblewrap 的 user/mount/PID/network namespace 隔离文件和网络；候选运行前设置 seccomp 和资源限制。可信控制器只传入当前允许的数据，候选不能读取项目或用户目录。NumPy 1.26.4、SciPy 1.13.1 单独安装到 `.task-runtime/python`，不改变 OpenHands。隔离失败时拒绝执行，不降级为宿主执行。

## 1. 公共执行隔离

文件：`rsi_eval/sandbox.py`、`worker.py`、`tests/test_sandbox.py`。

接口：`run_candidate(source, request, *, timeout_seconds=20, memory_mb=2048, cpu_seconds=10, max_output_bytes=2000000, deps_dir=None) -> dict`。正常进程返回 `status=completed` 和结构化 `result`；超时、输出过量、资源/进程/基础设施错误分开。

- [x] 编写拒绝宿主 canary、环境变量、网络、子进程、写文件的检查，以及超时/输出上限后恢复检查。
- [x] 只读挂载系统运行库、可信 worker、当次源码/请求、独立数值库；不挂载项目数据目录。
- [x] 所有候选源码只在隔离 worker 中执行；输出流有上限，终止时回收子进程。

## 2. 规划执行器

文件：`rsi_eval/planning.py`、`planning_worker.py`、`tests/test_planning.py`、`fixtures/planning/`。

接口：`prepare_task(task_id, root)` 返回 objects/init/goal；`validate_plan(task_id, plan, root)` 由可信侧检查动作结构并调用 VAL。

- [x] 先测试任务角色、哈希、不支持的 PDDL 构造、错误动作和封存任务拒绝。
- [x] 实现当前 Spanner 所需的严格 typed STRIPS 解析子集，不宣称完整通用 PDDL/PDDLGym 支持。
- [x] 用手写通用 Spanner 程序验证 2 个 prompt + 8 个开发实例；用错误候选检查反馈分类。测试实例不运行。

## 3. 符号执行器

文件：`rsi_eval/symbolic.py`、`symbolic_worker.py`、`tests/test_symbolic.py`、`fixtures/symbolic/`。

接口：`prepare_task(task_id, root)` 只读 oscillator1/2 的 train.csv；worker 分 `fit` 和 `predict`；`score_predictions(y, predictions)` 在可信侧算 MSE/NMSE。

- [x] 先用人工线性数据验证参数恢复，测试错误形状、NaN/Inf、零目标方差和非法任务身份。
- [x] 拟合使用固定初值、最多 16 个参数、100 次优化器 nfev 预算；实际候选函数调用数单独记录。预测进程不接收 y。
- [x] 原始训练数据上的常数/线性候选只检查流水线，不当作正式基线结果；不访问 test_id/test_ood。

## 4. 控制器、记录与部署

文件：`rsi_eval/executor.py`、`scripts/evaluate_candidate.py`、`scripts/check_task_executors.py`、`tests/test_executor.py`、运行说明和验收摘要。

- [x] 统一 `evaluate_candidate(family, task_id, source, *, root, n_params, candidate_id, parent_id, strategy_version)`；记录源码哈希、父候选/策略版本、限制、执行反馈和耗时。
- [x] 控制器测试须证明预测请求没有标签，候选自报分数不被使用，前一阶段失败时不继续下阶段。
- [x] 服务器运行全部相关测试与两类真实开发任务验收，保留成功及故障证据；检查无模型调用、无封存评分。
- [x] 审查后同步 GitHub 和服务器，更新状态入口，解释仍未完成的正式策略选择协议与 OpenHands 研究 Agent。

当前只提供开发反馈，不开放通用 split/path 参数。正式研究仍需确定独立策略选择/评价方案；不会把 train 内拟合误差作为泛化结论。此有限入口使未冻结协议不会被误用为已经可跑正式实验。

验收完成：39 项任务测试和 4 项 SDK 测试通过；10 个规划开发实例、4 次符号训练拟合、5 项负例/访问检查、2 次 SDK 工具往返通过。额外实现 rsi_eval/openhands_tool.py 与 scripts/check_openhands_evaluator.py，只提供受控接口，未发模型请求。证据见 docs/environment/2026-10-20-task-executor-verification.json。
