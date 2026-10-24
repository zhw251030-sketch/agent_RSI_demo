# 三条件编辑检查 runner 操作说明

当前实现提交：`8191274568c5112c725d294228b6d53ea11be454`。

## 预演

服务器使用 OpenHands SDK 1.55.1 运行：

```bash
.venv/bin/python -m unittest tests.test_basis_edit_runner -q
```

预演使用假 provider 和 synthetic evaluator，不调用 MiniMax、不读取真实 CSV。证书位于
`docs/environment/2026-10-24-edit-runner-preflight.json`，真实模式必须匹配当前提交。

## 模拟 runner

```bash
.venv/bin/python -m analysis.basis_edit_comparison.runner simulate \
  --output runs/basis-edit-comparison/synthetic-v01
```

## 真实 runner

真实模式固定只允许 6 次模型请求、每槽一次、无自动重试。认证文件只在进程内读取，不能作为参数传入密钥内容：

```bash
.venv/bin/python -m analysis.basis_edit_comparison.runner run \
  --preflight docs/environment/2026-10-24-edit-runner-preflight.json \
  --output runs/basis-edit-comparison/measured-v01
```

如果使用非默认认证文件，可增加 `--auth-file /path/to/auth.json`。运行目录必须不存在；旧 v02 目录不会恢复或覆盖。

runner 先拟合三个父结构，再发送六次 actor 请求；所有三条件门结果冻结后才执行候选 shadow 评分。任何模型请求失败、usage unknown 或候选执行失败都会保留失败状态，不补抽、不自动重试。
