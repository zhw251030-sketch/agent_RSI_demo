# 已完成的八次符号数值诊断

本轮入口为[结果与解释](../analysis/2026-10-22-symbolic-numerical-diagnostic.md)，原先设计是[设计 A](../experiments/2026-10-22-mechanism-next-design.md)。代码、八源、独立事前审查见 [analysis/symbolic-diagnostic-v01](../../analysis/symbolic-diagnostic-v01/README.md)。冻结文件在实际数据拟合前提交 `59edb382`，运行目录已占用，**不重复运行 run 命令或恢复这轮**。

八条件全部完成。查看[完整汇总](../../artifacts/symbolic-diagnostic/2026-10-22/v01/summary.json)和各位置原始 fit/predict；校准在相邻 calibration-v01 目录。新增模型费用为零。

只读核验命令（从项目根目录）：

```bash
.venv/bin/python analysis/symbolic-diagnostic-v01/diagnostic.py verify --output artifacts/symbolic-diagnostic/2026-10-22/v01
PYTHONPATH=.task-runtime/python /usr/bin/python3 -m unittest discover -s analysis/symbolic-diagnostic-v01 -p 'test_archive.py'
```

服务器需核对已保存预测的数值评分时，可给 verify 加 `--verify-scores`；它只重读已见两张 train 并重算指标，不执行候选或重新拟合。原历史 gate 依赖留在服务器 runs 下，本机没有该数据/门禁运行树，因此本机只做档案绑定核验。

数值单元测试应使用系统 Python 3.10 与 `.task-runtime/python`。SDK `.venv` 没有 NumPy；不要为了跑数值测试把它与数值环境混装。完整新测试集合为 test_candidates.py（8）、test_diagnostic.py（10）、test_worker.py（9）、test_archive.py（9），共 36 个不同测试。

后续先实现可检查的基函数/直接系数契约，再冻结策略选择对照。没有预先指定的新模型运行命令。旧 measured-v01/v02 不恢复，measured-v03 不追加。
