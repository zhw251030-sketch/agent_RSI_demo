# sdk-preflight-v03 原始记录归档

实现提交 0065d8c5cc0a1af5b4a1618920a5eb4a4b281ae6；证据类型 `synthetic`。

`raw/` 保存本运行目录原文件；`executions/` 保存本真实轮产生的角色执行器记录（若有）。共 3644 份原文件逐字节复制。`verification/` 保存双端只读回放和相关验收证据。

`manifest.json` 的 source_map 映射项目内原路径到归档位置；内部引用不改写。离线回放需按映射在相同运行版本恢复，不能覆盖不同内容的已有记录。

本目录全部provider响应、策略、分数及用量均为模拟，不计研究调用、费用或结果。
