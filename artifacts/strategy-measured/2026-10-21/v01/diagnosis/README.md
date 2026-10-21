# 离线诊断与反事实会话

所有内容由服务器SDK1.55.1离线生成，真实网络被禁止，未读取凭据、调用模型或执行候选。

- `measured-failure-sdk-replay.py`和JSON保存复现步骤、源码/原请求/响应哈希、实际SDK解析路径和16项投影正负例。
- `replay/original_response/`：未改适配器，返回保存的原始响应，仍为error、无接受。
- `replay/counterfactual_metadata_omitted/`：仅从模拟响应中删除summary/security_risk，SDK返回accepted；这里的policy/submission是反事实模拟记录，不是研究策略，不补入measured-v01。
- 两次SDK实际组装的请求都与原始请求文件逐字节相同。模拟响应沿用原usage以检查原路径，但两次均从研究调用/费用排除。

SDK常规路径先提取两个元数据，再验证基础Action。完整raw直接调用基础Action仍被拒绝；动态增强Action用于生成schema，不能把它的直接model_validate等同实际工具派发。当前schema的SecurityRisk引用缺少定义，是附带发现，未证实导致本次直接失败。

严格投影助手只在诊断脚本中试验，未接入生产，也未完成actor或整轮后继修复验收。原33文件未改。读取这些记录时必须保持“真实停止轮”和“离线反事实”两种证据的区别。
