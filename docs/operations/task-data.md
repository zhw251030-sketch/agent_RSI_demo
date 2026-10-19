# 两条路线的数据下载与验收

更新：2026-10-20。服务器已取得规划与符号两类真实公开数据，下载和离线验收通过；本次模型调用为 0，没有运行 Agent、方法基线或正式研究实验。

后续进展：开发任务执行器、候选隔离和 OpenHands 工具已实现并通过离线验收，见 [任务执行器说明](task-executors.md)。下文保留本次数据准备时的证据边界与下一步记录。

## 当前实际使用的数据

规划保留 llm-genplan 的 Spanner，来源是 [AAAI 2024 正式论文](https://ojs.aaai.org/index.php/AAAI/article/view/30006)及[作者仓库](https://github.com/tomsilver/llm-genplan)。完整包有 100 个训练问题、300 个测试问题和 1 个域文件。现有 seed0 的 2 个 prompt、8 个开发问题、30 个封存问题仍只是准备稿，没有扩大实验授权或冻结评价协议。

符号发现改用 [LLM-SR 的 ICLR 2025 正式论文](https://proceedings.iclr.cc/paper_files/paper/2025/hash/28df8e730c054c5331855fd4d5403ba9-Abstract-Conference.html)配套的[官方公开数据](https://github.com/deep-symbolic-mathematics/LLM-SR/tree/41c212312df6c16d936c9cb395356a62774c47e3/data)。用户要求替换访问困难的受限数据后，选择它作为当前起步版本；先用 oscillator1/2，另两题已下载作为库存，尚未指定机制训练/测试角色。

| 方程问题 | 输入 → 预测输出 | train | test_id | test_ood | 当前角色 |
|---|---|---:|---:|---:|---|
| oscillator1 | x、v → a | 10,000 | 10,000 | 10,000 | 起步任务 |
| oscillator2 | t、x、v → a | 10,000 | 10,000 | 10,000 | 起步任务 |
| bactgrow | b、s、temp、pH → db | 7,500 | 2,500 | 15,000 | 保留，未分配实验角色 |
| stressstrain | strain、temp → stress | 2,161 | 1,442 | 738 | 保留，未分配实验角色 |

共 12 个 CSV、89,341 个观测。CSV 最后一列是输出，前面各列是输入；这个约定直接来自固定源码 `main.py`，不能套用之前 LLM-SRBench 的列顺序。所有文件通过哈希、列名、行数和有限值检查；文件内没有完全相同的行或输入，同一题的不同划分之间也没有精确重叠。此检查不证明轨迹观测统计独立。

## 为什么采用这个替代

LLM-SR 原任务与现有研究接口直接对应：LLM 提出公式程序，数值优化器拟合参数，执行器返回误差或失败信息，再由策略决定如何修订。两个振荡器保留了物理方程发现的目标，并已有明确的同分布/分布外测试文件。它们是正式论文使用的数据，不是本项目临时编造的例子。

但 **LLM-SR 原始四任务包不是 LLM-SRBench**。后者的访问仍需登录和接受共享联系信息的条件，本次没有申请或绕过。数据卡正文的物理 43 题与机器元数据 44 条还存在差异，未取得数据就不能确认真实题数。旧的 `symbolic-phys-osc-v0.1.json` 和接口说明保留作历史参照，当前数据入口以 `downloads-v0.1.json` 和新版符号协议为准。

| 公开候选 | 正式来源 | 实际任务单位 | 本次判断 |
|---|---|---|---|
| LLM-SR | ICLR 2025 | 4 个方程问题，其中 2 个振荡器 | 当前采用；接口和目标最接近，可直接开始执行器准备 |
| SRBench / Strogatz | [NeurIPS 2021 Datasets and Benchmarks](https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/hash/c0c7c76d30bd3dcaefc96f40275bdc0a-Abstract-round1.html) | 14 个标量导数任务，来自 7 个二维系统，每题 400 行 | 可作为后续同接口扩展；应按系统分组，公开经典方程存在记忆风险 |
| ODEBench / ODEFormer | [ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/5ed5c3c846f684a54975ad7a2525199f-Abstract-Conference.html) | 63 个系统，1–4 维 | 适合后续跨系统验证；原任务从轨迹发现整组 ODE，需要额外积分评价器 |

SRBench 与 ODEBench 的公开文件已在本机临时审查目录实际下载核验，但未并入服务器的当前任务集。两个振荡器只能支撑初步机制诊断；六万观测或多个随机种子不能替代更多独立方程，不能据此声称方法普适。

## 文件如何分工

所有服务器相对路径均相对于当前项目根目录。

| 文件/目录 | 做了什么 | 原因 |
|---|---|---|
| `configs/tasks/downloads-v0.1.json` | 锁定两个官方源码 commit、压缩包大小和 SHA-256，记录 12 个 CSV 的身份、列与行数 | 后续下载得到同一批材料，避免分支变化悄悄改变实验 |
| `configs/tasks/planning-spanner-v0.1.json` | 保存 400 个问题、域文件的哈希与准备稿角色 | 数据盘点和实验划分可以独立审查 |
| `scripts/prepare_task_sources.py` | 校验压缩包，拒绝不安全路径，解压并复制指定任务；已有不同内容不自动覆盖 | 获取过程可重跑，避免覆盖或混用版本 |
| `scripts/check_planning_data.py` | 核对源码/数据副本各 401 个文件；运行固定 VAL 样例 | 区分数据损坏、规划错误和验证器启动错误 |
| `scripts/check_symbolic_data.py` | 检查 12 个 CSV、输出位置、有限值、重复及划分重叠 | 防止目标列用错、非法数值和明显的数据泄漏 |
| `docs/environment/2026-10-20-task-data-verification.json` | 保存本次服务器实际验收摘要、代码 commit、脚本与完整日志哈希 | 结论对应可追溯的执行证据 |
| `vendor/llm-genplan/`、`vendor/LLM-SR/` | 保存固定上游源码与许可证 | 供研究和实现接口时参考；被 Git 忽略 |
| `data/planning/spanner/` | 保存域文件与官方 train/test PDDL | 后续可据 manifest 制作受控任务目录 |
| `data/symbolic/llm-sr/` | 按四个任务保存 train/test_id/test_ood.csv | 保留官方数据划分与原始字节 |
| `runs/data-preparation/` | 本机运行生成的完整验收 JSON | 原始运行产物被 Git 忽略；只提交检查过的摘要 |

源码包含参考结果、描述和可能的答案线索，测试数据也在同一用户可读目录。**目录分开与 Git 忽略不构成隔离**。未来不能让实验 Agent 任意读取项目根目录；需要创建受控工作区和工具接口，才可以开始可信评价。

## 实际验收结果

源码包总计 40,316,793 字节。Spanner 数据与上游各 401 个文件均匹配；LLM-SR 的 12 个 CSV 均匹配。服务器重复运行下载脚本也通过，说明已有材料可直接校验重用。

VAL 仅在公开 prompt `spannerlearning/seed0/problem0` 上执行手写固定计划：11 步正确计划判为 valid，空计划及违反前置条件的计划判为 invalid，故意缺失可执行文件判为 infrastructure_error。四项验收通过，没有执行封存规划任务，也没有运行生成的程序。

这次只用系统 Python 3.10.12 标准库和仓库附带的 Linux VAL，不需要新增 Python 包。现有 OpenHands/Canvas 环境未改动。PDDL 的全量文件检查仅包括哈希、UTF-8、括号及单个 define 外层结构；没有声称完整官方解析器已安装。VAL 的域/问题语义检查只覆盖该固定 prompt 样例。超时处理已经写入检查器，但此次未专门注入超时故障。

上游根许可证分别保留；llm-genplan 固定源码中没有单独的 VAL 许可证文件，不能凭根 MIT 推断第三方二进制的许可细节。本项目不把第三方源码、二进制或原始数据重新上传 GitHub。

## 如何重跑

在服务器项目根目录执行：

```bash
python3 scripts/prepare_task_sources.py
python3 scripts/check_planning_data.py
python3 scripts/check_symbolic_data.py
```

首次下载需要能访问 GitHub codeload；本次已从官方源下载并校验，经 SSH 传到服务器，服务器仍按同一哈希校验，因此无需依赖服务器访问 GitHub 的认证。没有模型调用。合成异常输入自检可用 `python3 scripts/check_symbolic_data.py --self-check`，它只验证检查器，不算研究实验。

## 下一步具体要补什么

先做可调用的任务执行器：规划将统一的程序输出送入 VAL；符号将公式程序、参数拟合和数值评价接起来。生成代码必须隔离执行，失败、非有限输出、超时与基础设施错误要分别返回。

在模型调用前确定允许的训练反馈和独立策略选择规则。符号侧保留 test_id/test_ood 作最终评价，不能拿测试文件反复选择修订策略；还需在 train 内制定适合轨迹来源的开发划分。原始 LLM-SR 在训练集上拟合并打分，不自动提供我们的策略选择方案。

之后才做固定策略与更新策略的等预算对照，记录全部候选和失败。两项数据准备验收没有验证任何 RSI 改进，也没有产生可写成性能提升的简历结果。
