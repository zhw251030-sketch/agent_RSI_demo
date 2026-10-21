# sdk-preflight-v02 原始记录归档

实现提交 729318e817cda5ea581fdb033201ce0aeab4dbdb；证据类型 `synthetic`。

`raw/` 保存本运行目录原文件；`executions/`（若有）保存该真实轮产生的角色执行器记录。共 3644 份原文件逐字节复制。`verification/` 保存双端只读回放及相关验收证据。

`manifest.json` 的 source_map 映射项目内原路径到归档位置；内部引用不改写。离线回放需在相同运行版本中按映射恢复文件，不覆盖已有记录。

本目录全部 provider 回复、用量、策略与分数均为模拟，不计研究调用、费用或结果。
