# 第二批冷启动来源：八槽完成

运行版本 `67d8d873c05da8dbfc73bbc75f0d2842e30fc813`，run ID `20261021-state-generation-v02`。实际8请求、8份提交，全部用量已知，无重试/恢复，无候选执行、拟合、任务评分或S更新。v01两份源码没有拼入本批。

130份原文件逐字节复制自服务器；[manifest](manifest.json)保存逐文件及整树SHA256。README与manifest是附加说明，不计入130份原文件。

| 槽位 | 角色 | 实际源码 |
|---|---|---|
| P-select-1 | 规划选择 | [source.py](sessions/P-select-1/source.py) |
| S-select-1 | oscillator2选择 | [source.py](sessions/S-select-1/source.py) |
| P-eval-1 | 规划后续评价 | [source.py](sessions/P-eval-1/source.py) |
| S-bact-eval-1 | bactgrow后续评价 | [source.py](sessions/S-bact-eval-1/source.py) |
| P-select-2 | 规划选择 | [source.py](sessions/P-select-2/source.py) |
| S-select-2 | oscillator2选择 | [source.py](sessions/S-select-2/source.py) |
| P-eval-2 | 规划后续评价 | [source.py](sessions/P-eval-2/source.py) |
| S-stress-eval-1 | stressstrain后续评价 | [source.py](sessions/S-stress-eval-1/source.py) |

[batch-freeze](batch-freeze.json)绑定新配置与协议；[input-freeze](input-freeze.json)保存相同的匿名生成输入和全部角色；[source-freeze](source-freeze.json)保存120份会话文件的哈希，随后才[静态分析](static-analysis.json)。各session的transport-request/result记录实际180秒设置、零重试和耗时。

全部源码/AST不同且未与151个历史源码文件碰撞，均能解析并匹配入口；不证明语义独立、正确性或性能。耗时5.42–39.22秒，全低于60，不能将本批完成因果归于延长超时。

见[本批结果](../../../../docs/analysis/2026-10-21-state-generation-v02-results.md)、[机器审计](../../../../docs/analysis/2026-10-21-state-generation-v02-audit.json)、[操作说明](../../../../docs/operations/state-generation-v02.md)。复核使用Python3.12.14，旧批记录保持中止。
