# 基函数提交接口 v01

模型选择结构，宿主固定执行条件。完整字典包括 1–4 输入、总次数不超过 3 的全部单项式（4/10/20/35 项）。这是有限多项式字典搜索；不等于无约束符号发现。固定 K 只控制项数，不证明相同秩、表达能力或计算成本。

```python
from extensions.symbolic_basis_v01.contract import make_spec, compile_submission
spec = make_spec(n_inputs=2, k=3)  # 由可信宿主冻结，不是模型参数
payload = {
    'feature_ids': ['m_0_0', 'm_0_1', 'm_2_0'],
    'explanation': '保留常数和第二变量一次项，将第一变量一次项替换为平方项。'
}
compiled = compile_submission(payload, spec)
```

该结构表示 β0 + β1*x1 + β2*x0²。系数从全 1 开始由原 least_squares 拟合；模型不能填写 β。同一集合改变顺序或解释文本，生成的源码及结构哈希不变。参数顺序为 `(总次数, 指数向量)` 升序；不接受重复 ID、别名、任意 Python 或模型自报项数。

`executor.evaluate_submission` 是可信宿主的数组入口。正式角色入口 `evaluate_role` 复用原 RoleExecutor 与 EvaluationGate，只开放授权 train。初始提交标记 initial；swap_one 要求同 K 且保持或一删一加；add_one 要求保留全部父项且恰加一项。拟合和预测使用两个独立沙箱，预测请求不含 y。源码不在宿主执行。

`sdk_adapter` 提供实际 OpenHands ToolDefinition/Action/Executor 与一次性回调。宿主先调用 handler.prepare_response 验证原始单工具回复，随后 SDK Action 才能被接受；重复 JSON 键、额外字段、重复工具和类型强转均拒绝。它是提交组件，不包含完整 Conversation/provider 调度、策略更新或实验预算控制；真实轮前须接入统一调度器并做完整假 provider 验收。

本轮校准固定 10 个人工拟合条件（含 K=16）、10 次独立预测和 2 次极端有限输入保护预测，共 22 个沙箱；每次启动的人工 warmup 另计。零方差目标应 fit 成功而 NMSE 不可用；共线样例可精确预测但不能识别唯一系数。测试与校准均不读取真实 CSV，不调用模型。

数值测试在服务器使用 `PYTHONPATH=.task-runtime/python /usr/bin/python3 -m unittest extensions.symbolic_basis_v01.test_contract extensions.symbolic_basis_v01.test_executor extensions.symbolic_basis_v01.test_calibrate`；SDK 测试使用 `.venv/bin/python -m unittest extensions.symbolic_basis_v01.test_sdk_adapter`。两个既有环境保持分开。

`python -m extensions.symbolic_basis_v01.calibrate prepare` 只冻结源码、人工输入和环境；`run --sha256 ...` 创建独立一次性目录；`verify --directory ...` 使用保存预测重算人工分数，不重跑候选。运行目录存在即拒绝，没有恢复补抽。实际完成状态以带日期的 operations/analysis/verification 报告为准。
