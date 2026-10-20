# 干预检查校准：完整原始归档

运行已完成，代码 `b1f4f81752fc9a162a030c4055a24f80f43733c4`。这是研究者指定的离线开发干预，0新增LLM请求；不是Agent自主改进成绩。

- [汇总](summary.json)：完整结果、判定、下一编辑范围和计数。
- [案例](cases.json)：五个真实来源及父子源码，原历史成绩不被替换。
- [运行冻结](freeze.json)与[协议参数](config.json)。
- [格式失败公开题0](planning/p2-P-H002-checked/public-0.json)：保存同一份原始/规范化计划及验证。
- [严格源码补丁](format-patch/candidate.py)与[修改契约](format-patch/contract.json)：后续10题均成功，属于人工干预。
- [v³删项配对](symbolic/p1-S-poly5-self/probe.json)与[x⁵删项配对](symbolic/p2-S-odd4-checked/probe.json)：三版重拟合的原始记录。
- [不适用人工控制](unsupported-fixture.json)：静态拒绝，0候选执行。
- [文件清单](manifest.json)：31个服务器原文件逐字节一致；树SHA256 `cc2d69a1cb5c07f36634ee30593c25ccc4863daafb3cb5ff2eb07d8207a18819`。

新增22次任务评价、28次sandbox调用、20次VAL。原始31文件未改名或规范化；本说明与manifest为本机新增。完整解释见[操作说明](../../../../docs/operations/intervention-probes.md)和[逐项分析](../../../../docs/analysis/2026-10-21-intervention-results.md)。
