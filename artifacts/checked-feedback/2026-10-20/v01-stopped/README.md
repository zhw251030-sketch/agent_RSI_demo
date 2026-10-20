# checked-feedback v01：已停止的故障运行归档

运行 ID：`20261020-checked-feedback-v01`。这是接口故障现场，不是检查反馈有效性比较结果。

保留全部四条件的轨迹、诊断、证据与紧凑状态；9 份实际候选/基线源码逐字节复制，保留原始 LF；全部 8 份安全模型响应、8 份输入审计及两个已启动条件的事件日志也逐字节复制。两个未启动条件没有审计文件，此归档用空数组表示零条审计，不能当成新计算结果。

`request-index.json` 将请求、源码 SHA、实际执行候选与下一次输入中的错误标记串联；`summary.json` 是紧凑派生视图。`trajectory.json` 删除重复的 incumbent_source，源码以 candidates/ 和 candidate-source-manifest.json 为准。

未执行的两个规划提议完整保留在 request-0002/0003.response.json 中，不计入 9 份实际候选/基线文件或五次候选执行。完整请求、状态包、task-prompt 和重复的原始 summary 未复制；其逐文件哈希以及派生关系见 manifest.json，共覆盖原始副本的全部 74 个文件。

账本 usage 为本轮真实响应使用量；费用为配置单价估算，不是账单。人工停止时第八请求已在途并随后结算；不存在未知 usage。此前其他轮次的未知费用不受影响。

整理仅读取本机无密钥证据副本，没有加载 API 凭据、调用模型或运行候选，也没有改动旧运行。详细诊断见仓库 docs/analysis/2026-10-20-checked-feedback-v01-incident.md。
