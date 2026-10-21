# 符号数值诊断 v01

本目录实现 2026-10-22 设计 A 的八次拟合。它是研究者指定的已见训练任务诊断，不生成 Agent 候选、不学习 S、不调用模型。后续 168 请求设计 B 不在本轮范围内。

`candidates.json` 固定八份源码、父来源、特征集合及参数顺序。stress-original-7 与旧源码逐字节一致；stress-direct-4 用四个直接系数表达同一有限实数多项式族。bact 六条件统一旧 fixed 的输入/输出契约。输入变换为 identity，旧文档的“归一化”并不代表曾做标准化。

`preregistered-expectations.md` 保存执行前解释边界：同族重参数化、等参数数特征替换、全平方族与删项族的包含关系。四个删项条件必须全部报告。`pre-execution-review.md` 保存独立接口检查。

`runtime/rsi_eval/` 中 sandbox、worker、__init__ 与旧文件逐字节一致。新 symbolic_worker 只增加元数据，不增加求解器或候选调用。保留 scipy least_squares 的 ones 初值、max_nfev=100 和安装版本默认设置。每次 sandbox 启动都包含旧人工 warmup，单独计数。

`diagnostic.py` 使用原已验证 v03 EvaluationGate 和 RoleExecutor.prepare_task；再硬限 stressstrain/bactgrow 的 train。它创建新目录 `runs/symbolic-diagnostic/v01`，目录存在即拒绝，无恢复或补抽。拟合后用不含 y 的独立进程预测，宿主沿用 population variance NMSE 并计算 SSE。失败 NMSE 留空。保留每个位置的预约、源码哈希、请求哈希、优化器原始回执、预测回执及结果；不将原始 CSV 放入仓库。

先执行 `calibrate --output runs/symbolic-diagnostic/calibration-v01`，分别用旧/新工作器拟合人工线性与常数函数，再做新进程预测和错误形状负例：5 次人工拟合尝试、2 次预测、7 次启动 warmup。它们与八次 benchmark 拟合分开。

之后用 `freeze --output docs/experiments/2026-10-22-symbolic-diagnostic-freeze.json --calibration runs/symbolic-diagnostic/calibration-v01` 固定源码、测试、校准、旧运行文件、门禁、两 train 哈希、环境、限制、顺序和运行目录。执行 `run --protocol <冻结文件> --sha256 <已记录摘要>` 时重新核对。`verify --output <归档目录>` 只做离线完整性和字段关系核对，不重跑拟合。

测试命令：`python -m unittest discover -s analysis/symbolic-diagnostic-v01 -p 'test_*.py'`。候选测试只用人工数组；工作器测试使用优化器 double，非真实拟合。真实服务器校准和诊断另有原始回执。
