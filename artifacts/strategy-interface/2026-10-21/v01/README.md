# 策略接口准备与人工校准归档

这里没有新增真实Agent结果。代码版本为 `3b613c14704fe9002593a8258ff623638adfe4a9`，模型调用为0，八份v02来源仍未执行。

- `preparation/`：两端逐字节相同的准备包，包括全部24旧终稿的学习材料、更新packet、36槽分配、来源/角色审计与236文件运行指纹。内部manifest仅对应该目录6个JSON内容文件；第7个文件是manifest自身。
- `calibration/`：人工任务及手写源码的真实sandbox/VAL校准，4条评价、6次sandbox、2次VAL。结果与研究任务评分分开。
- `verification/`：两端118项测试报告与准备审计。本机Linux校准明确跳过；服务器实际通过。
- `source-map.json`：每个服务器输入文件的原项目相对路径、归档路径和SHA256。原始文件内容不修改；例如原`runs/role_executor_feedback/<id>/result.json`移到`calibration/records/<id>/result.json`后，内部journal_path仍保留原路径。

校准使用独立临时目录和合成metadata，固定样例并非真实Spanner/oscillator2数据。人工CSV只包含y=2t+1四行；未归档依赖软链接、VAL二进制、凭据或任何封存数据。

上层manifest核对本目录所有内容文件。准备包可用 `scripts/prepare_strategy_pair.py --output artifacts/strategy-interface/2026-10-21/v01/preparation --verify` 重建核对；需要Python3.12.14及已提交的相同运行源码。该命令不执行候选或调用模型。
