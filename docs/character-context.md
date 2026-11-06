# 角色上下文维护与验证

- `backend/prompts/character.md`：人格、说话方式、真实能力边界。
- `backend/prompts/profile.md`：常驻角色事实，第一人称仅指叶瞬光。每轮都与人格规则组装进首条系统消息，不依赖 RAG 是否就绪；两个文件都按各自修改时间刷新缓存。
- `source/resources/character/timeline.md`：截至 2.5 的剧情年表，登记在同目录 `manifest.json`，保留来源范围与剧透标记。它是已有用户归档的摘要，没有新增官方核实结论。
- 用户事实与共同经历仍由原有记忆模块维护；角色经历不会因常驻注入而写入用户记忆。

修改年表后，需同步更新 manifest 中对应文档的 SHA256，再运行 `.venv/Scripts/python.exe scripts/rag-cli.py build` 增量索引。应用正在使用检索时，通过“陪伴设置”构建索引，避免另一个进程打开同一 Qdrant 存储。年表遵循原有剧透许可规则。

离线验证：

```powershell
.venv/Scripts/python.exe -m pytest backend/tests/test_character_context.py backend/tests/test_upgrade_context.py
```

测试覆盖 20 条固定提问、闲聊与用户记忆的误匹配、RAG 有无就绪时的聊天链路、事实常驻和热更新、资料作为数据的边界。离线测试不证明实际模型的语气表现。

显式启用真实回复评估（读取应用已保存的模型，发出 20 次 API 请求，可能计费；不会写入聊天历史或用户记忆）：

```powershell
$env:SHUNGUANG_PERSONA_LIVE = '1'
.venv/Scripts/python.exe -m pytest backend/tests/test_character_context.py -k live_persona_reply
Remove-Item Env:SHUNGUANG_PERSONA_LIVE
```

真实回复评估检查常见客服措辞、师父与拜师经过、未知年龄和身份坦诚。身份提问允许必要的技术词，功能失败仍需如实说明，不对输出做关键词删除。
