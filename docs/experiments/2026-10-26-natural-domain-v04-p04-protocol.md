# natural-domain v04 p04 独立开发重复协议

状态：配置与 fake/real wrapper 已实现；真实请求尚未启动。

## 为什么改用 p04

上一轮 v03/v04 使用的是四个任务的 p01。进一步审计全部历史 `round-summary.json` 后发现，p02 也已在早期 v02/v03/v04 或 cross-task 真实轮中出现，不能把 p02 作为“新父结构”。因此本轮冻结四个从未在历史 round 中出现的 p04 结构，并在请求前做 task-specific source hash collision audit。源码哈希按 `(task_id, source_sha256)` 绑定：stressstrain 与 oscillator1 的二维通用源码可能相同，但输入名和任务映射不同，不能因此把两个任务错误判为冲突。

## 固定任务和父结构

每个任务一个 p04 parent、两个一次性请求，共 8 个槽位；父结构和 feature IDs 在第一条请求前冻结：

- `bactgrow-p04`：`1, b, s, temp, b*s`；
- `stressstrain-p04`：`1, strain, temp, strain*temp, strain^2`；
- `oscillator1-p04`：`1, x, v, x*v, x^2`；
- `oscillator2-p04`：`1, t, x, v, t*x, x*v`。

候选仍只能是 `keep` 或恰好一次 `swap_one`，常数项必须保留。非法结构、SDK 未接受、sandbox 失败、usage unknown 或源码碰撞均停止本轮，不补抽、不重试。

## 证据和结果门

模型权重、MiniMax-M3、OpenHands SDK 1.55.1、symbolic runtime lock、`shift-aware-dev-v02` split manifest 和 natural-domain v04 报告哈希在证书中冻结。replacement evidence 仍使用原来的 `supported/contradicted/unknown` 三态；v04 replay 再对同一批 proposal 应用固定的 ordinary + natural-domain 双重结果门：普通结果和所有有效域块均至少改善 `1e-5`，域块最少 32 行，允许的最大域块退化为 0。

本轮先执行 FakeProvider 8 槽预演，生成新的证书；证书验证通过后才允许真实 8 请求。真实轮只负责生成 proposal 和三条件 gate，之后由独立的 v03 synthetic replay 和 v04 natural-domain replay 读取冻结的 round summary，模型请求数应为 0。

## 防泄漏和评价边界

- 只读取四个任务的 `train.csv` 及已冻结的 `fit_dev_v2/check_dev_v2/outcome_dev_v2`；
- 不读取官方 `test_id`、`test_ood` 或任何封存文件；
- 不用本轮结果修改阈值、父结构、提示词、策略 S 或模型权重；
- 以 `task × parent × repeat` 作为分析单位，8 个槽位不当作 8 个独立任务样本；
- p04 轮属于新的开发重复，只有完成完整审查后才考虑注册下一轮 holdout。

## 预登记输出

保存 p04 parent/candidate 源码哈希、接受槽位、gate rows、evidence 状态、三种动作（old/v02/v03）与 v04 双重门结果；报告中单独列出源码新颖性检查、普通结果和每个自然域块结果。任何官方 test/OOD 访问标志为真都使本轮无效。
