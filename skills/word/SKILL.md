---
name: shunguang-word
description: 用真实资料生成和局部修改可编辑 Word 成品。
---

读取用户材料和模板，按任务选择简洁专业的结构。普通任务直接制作，复杂或关键要求不清楚时先确认简短提纲。不能编造数据或来源。

通过 office_files 提交 format=docx，name 为单个 .docx 文件名。spec 使用 blocks 数组：

```json
{"blocks":[{"type":"heading","level":0,"text":"项目报告"},{"type":"paragraph","text":"报告正文"},{"type":"table","header":["项目","数量"],"rows":[["确认项","3"]]}]}
```

支持 heading、paragraph（可有 runs）、table、bullet_list、numbered_list、page_break。段落可使用模板已有样式；数字与单位准确，不将整份内容压成密集表格。

编辑已有 Word 时，先调用 office_inspect 获得资源版本及目标。operation=edit，source={"kind":"attachment 或 artifact","id":"资源ID","version":"返回的版本"}，spec={"edits":[{"target":"p:1","old":"该目标中的准确原文","text":"修订文字"}]}。表格单元格目标为 t:表格索引:行索引:列索引，均从零开始。只能使用真实返回的目标；原文不唯一时进一步定位，不替换所有同名文字。

仅提交结构化内容，不提交脚本或本机绝对路径。实际生成由受控工具执行，默认保存新副本。只有任务真实完成才报告完成；如页面未渲染或未检查，明确保留其校验状态。

本项目使用 Hermes MIT 生成工具的受控适配，来源与许可见 ../vendor/hermes/UPSTREAM.json 及 LICENSE；不需要安装 Hermes 或 Codex。

补充协议：有模板时传 source，使用 edits 填充真实目标（即使 operation=create 也按模板局部编辑）。空段落允许 old=""；页眉/页脚目标为 h:节索引:段落索引、f:节索引:段落索引，只用 inspect 返回的非链接目标。新建可传 header、footer 文字。插图块为 {"type":"image","image":{"kind":"attachment","id":"本聊天图片ID","version":"真实版本"},"width_cm":12}，不接受模型提供的本机路径。

多个来源传 sources 和 instruction，省略 spec，让后台分批读取。重要歧义可传 outline，用户确认后再生成；也可在后台 JSON 返回 {"outline":"简短提纲","spec":{...}}。只有用户明确要求额外 PDF 时才设置 export_pdf=true；默认只交付 Word。仅在用户明确要求 PDF 转 Word 时返回 blocks 并说明版式可能变化，不用 Word 替代保版 PDF 修订。

授权目录中的模板先用 office_import。默认新副本；用户明确要求覆盖时才传返回的 original 到 overwrite，系统仍会等待一次覆盖确认并保留恢复备份。版本、重复原文或多条意见有冲突时先澄清，不猜测目标。
