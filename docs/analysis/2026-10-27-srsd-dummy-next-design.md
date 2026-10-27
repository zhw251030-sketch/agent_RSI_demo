# SRSD-Feynman Easy-Dummy 下一轮设计

首个 Easy 外部 round 已经完成；下一轮不再重复同一批 Easy 题，而是使用 SRSD-Feynman Easy-Dummy 的同题干扰变量版本，专门测试结构证据能否处理“必要变量”和“无关变量”的混淆。

## 已核验的兼容任务

| task_id | train 文件列数 | 真值表达式 | 当前契约 |
| --- | ---: | --- | --- |
| `srsd-feynman-i12-1-dummy` | 3 输入 + y | `x0*x1` | 三输入单项式可表示，`x2` 是干扰变量 |
| `srsd-feynman-ii8-31-dummy` | 3 输入 + y | `4.427e-12*x1**2` | 三输入单项式可表示，`x0/x2` 是干扰变量 |

`srsd-feynman-i14-4-dummy` 的训练行是 5 输入 + y，超过当前 `symbolic-basis-v0.1` 的 1–4 输入限制，因此暂不加入下一轮；扩展输入契约时要重新做 runtime、SDK 和 hash 校准。

## 研究问题

固定权重模型在看到数值反馈后，是否会把干扰变量误认为有用结构，或把真值中的必要项误删？下一轮仍使用单项替换、train fit/check/outcome、val 自然域块和一次性 test 回放，唯一变化是输入空间增加了显式干扰变量。

## 执行顺序

先下载 Dummy 的 train/val 并生成独立 manifest；再用两个任务×一个 parent×两次重复做 FakeProvider 预演；真实轮最多 4 个 MiniMax 请求；最后按与 Easy round 相同的冻结 val action 做一次 test 描述性回放。Easy round 的 test 结果不会进入 Dummy 的阈值选择。
