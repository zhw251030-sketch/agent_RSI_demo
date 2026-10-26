# Shift-aware v02 fake-agent 门控预演结果

日期：2026-10-26  
运行脚本：`scripts/run_shift_gate_preflight.py`  
预演报告：`docs/environment/2026-10-26-shift-aware-preflight.json`

## 预演目的

本轮验证 shift 状态接入 gate 后，宿主是否按照预先登记的动作规则执行。预演使用四个训练任务的 v02 manifest 和输入诊断结果，不调用 MiniMax、不执行候选程序、不读取官方测试文件。

## 四类边界

| replacement evidence | 输入覆盖度 | 预期动作 |
|---|---|---|
| `supported` | `covered` | `execute_candidate` |
| `supported` | `shifted` | `retain_parent` |
| `contradicted` | `covered` | `retain_parent` |
| `unknown` | `shifted` | `retain_parent` |

四种状态在四个任务上各运行一次，共 16 个确定性案例；4 个应执行候选，12 个应保留父结构，实际结果全部匹配。

## 完整性

- `status=passed_shift_action_preflight`；
- `task_count=4`，`case_count=16`；
- `model_requests=0`，`candidate_executions=0`；
- `official_test_read=false`，`official_test_ood_read=false`；
- shift 诊断不读取目标值；
- 预演报告包含源 manifest SHA-256 和每个 proposal 的预期/实际动作。

## 结论边界

预演证明的是动作契约：发生 shift 时，`supported` 不会直接绕过保护执行。它没有证明 shift 指标能准确预测真实任务退化，也没有证明 v02 比旧 gate 有统计优势。下一步需要在新的开发数据上接入真实候选评分，先运行 fake outcome 回放，再考虑真实 Agent 请求。

