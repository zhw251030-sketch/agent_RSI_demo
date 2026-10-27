# v02 工程闭环验收

## 闭环定义

本阶段的工程闭环指：同一份代码和同一组冻结证据可以在服务器上完成以下链路，并由一个只读入口统一核验：

`source/dev/val-domain → FakeProvider preflight → real round → val replay → one-time holdout → hash/audit certificate`

验收入口是 `scripts/verify_srsd_i144_v02_closure.py`。它不调用模型、不下载数据、不改写已有报告；输出文件单独保存为 engineering closure certificate。

## 验收内容

入口检查：

1. source、dev、fake certificate、fake round、real round、val replay、holdout 和 runtime lock 全部存在；
2. source/dev/runtime 的两种哈希语义分别核对：dev 绑定 source 的 `manifest_sha256`，preflight certificate 绑定 source JSON 文件 SHA256；
3. fake round、real round、val replay、holdout 的输入哈希逐级一致；
4. fake/real/val 在 test 读取前均标记 `official_test_read=false`，holdout 标记一次性读取且规则已冻结；
5. val allow 数不超过协议上限；
6. 当前提交包含 fake certificate 所绑定的代码祖先；
7. v02 contract、adapter、controller、preflight、val replay、holdout 六个关键文件可以编译；
8. tracked worktree 没有未提交修改。

## 服务器执行

```bash
cd /home/hanwen/Project/project/agent_RSI_demo
.venv/bin/python scripts/verify_srsd_i144_v02_closure.py \
  --output docs/environment/2026-10-27-srsd-feynman-dummy-i144-v02-engineering-closure-v01.json
```

该命令只读已存在文件。服务器当前证书结果为 `status=passed`，代码提交为 `264e2fe1`，模型调用为 0，下载为 0，val allow 为 0，部署有害数为 0。

## 环境边界

OpenHands/SDK 使用项目 `.venv`。数值诊断若需要 NumPy/SciPy，使用任务执行器的 Python 3.10 runtime：

```bash
PYTHONPATH=.task-runtime/python /usr/bin/python3.10 <diagnostic-script>
```

项目 `.venv` 是 Python 3.12，不能直接加载 `.task-runtime/python` 中为 Python 3.10 编译的 NumPy 扩展。

## 结论边界

工程闭环通过只说明证据链、协议边界和运行入口一致，不等于缩放方法已经实现，也不等于 Agent 机制已经获得稳定性能优势。下一阶段仍需先完成隔离的 v02.1 数值缩放校准，再进行新的 FakeProvider 和真实机制轮。
