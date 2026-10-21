# measured-v03 离线机制分析

入口：[研究解释](../../docs/analysis/2026-10-22-strategy-mechanism-audit.md)，[下一步设计](../../docs/experiments/2026-10-22-mechanism-next-design.md)。

`audit.py`只读取固定v03归档，按完整请求和实际派发/传输设置分组，核对32终稿、16配对、原始716测量；`results.json`为可重复计算的结果。`edit-claims.*`是32个窄编辑谓词的人工事后标注；`symbolic-structure.*`是16终稿和4起点的代数与拟合回执审查；`variation-design.*`保留独立设计意见。人工标签和代数解释不会因文件哈希通过而变成自动证明。

在仓库根目录执行（服务器用`.venv/bin/python`）：

```bash
python -m unittest discover -s analysis/strategy-v03 -p test_audit.py
python analysis/strategy-v03/audit.py --output tmp/offline-recomputed.json
python analysis/strategy-v03/verify.py --output tmp/offline-verification.json
```

输出文件必须是未存在的新路径。程序不读CSV、不导入候选、不调用模型、不重新评分；历史原文件保持不变。`verify.py`自动核对引文、源码哈希、行片段、人口覆盖和冻结文件；语义判定仍须人工复核。

此分析独立于旧运行文件清单，不修改任何旧执行器、提示、测试或实验协议。新设计的`execution_ready=false`，还没有新的实际任务成绩。
