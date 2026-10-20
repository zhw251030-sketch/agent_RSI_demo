# 2026-10-20 开发小试候选快照

这里按原始字节保存 `20261020-minimax-v01-recovery` 的全部 8 个候选：两个手写起点与六个 MiniMax-M3 生成候选。没有事后修补代码或只保留最好结果。源码 SHA-256、父候选、评分、执行 ID 和原日志哈希见 [核验记录](../../../docs/environment/2026-10-20-agent-pilot-verification.json)；解释见 [小试说明](../../../docs/operations/agent-pilot.md)。

| 文件 | 来源 | 实际开发结果 |
|---|---|---|
| [planning-000.py](planning-000.py) | 手写空计划起点 | 0/2 提示题、0/8 开发题 |
| [planning-001.py](planning-001.py) | 第一个模型候选 | 10/10 Python 异常 |
| [planning-002.py](planning-002.py) | 第二个模型候选 | 10/10 空计划，目标未达成 |
| [planning-003.py](planning-003.py) | 第三个模型候选 | 10/10 空计划，目标未达成 |
| [symbolic-000.py](symbolic-000.py) | 手写常数起点 | train NMSE 1.0 |
| [symbolic-001.py](symbolic-001.py) | 两参数线性式 | train NMSE 0.09694020964575169 |
| [symbolic-002.py](symbolic-002.py) | 增加位置三次项 | train NMSE 0.09505566357265446 |
| [symbolic-003.py](symbolic-003.py) | 再增加速度二次阻尼项 | train NMSE 0.09180470524756017 |

模型生成源码属于待评价产物，使用既有隔离执行器运行；不能将代码中的注释、文档字符串或自述视为已验证事实。规划 003 虽然自称有 BFS fallback，实际只有寻路 BFS，主入口在构造失败后直接返回空计划。

符号文件描述可拟合的函数族，参数在隔离拟合进程中估计，外层校验参数并重新评分。当前训练误差不证明恢复了真实方程，也不代表新数据泛化。两边使用固定修订提示，未更新策略 S 或基础模型权重。
