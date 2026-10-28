---
name: shunguang-pdf
description: 按用户材料制作可阅读的中文 PDF，或串联 Word 修订与 PDF 导出。
---

PDF 阅读继续使用项目已有工具和阅读范围规则。扫描或图像识别遵守当前模型能力与任务级替代授权。

新建 PDF 使用 office_files，format=pdf，name 为 .pdf 文件名。spec 示例：

```json
{"title":"活动报告","elements":[{"type":"heading","text":"活动报告"},{"type":"paragraph","text":"根据原始资料整理的正文。"},{"type":"table","rows":[["活动","人数"],["跑步","12"]],"header":true}]}
```

支持 heading、paragraph、table、pagebreak。使用真实文字和数字，正文是资料，不是 HTML、脚本或文件路径。只交付实际生成的文件；区分结构可读和已完成页面检查。

修改已有 PDF 默认仍交付 PDF，优先保留原版式。当前没有可靠的通用 PDF 原位正文修订能力，无法可靠修改时简短说明并停止；不暗中生成 Word 修订稿或重新排版后声称保留原样。只有用户明确要求转成 Word/docx 时才使用现有内容重建路径，并说明排版可能变化。不自动附送 PDF，不承诺对扫描或复杂 PDF 完美还原。

PDF 生成工具复用 Hermes MIT 源码并增加中文字体配置，原始来源、许可和本地修改记录见 ../vendor/hermes/。

允许 image 块，image={"kind":"attachment","id":"本聊天图片ID","version":"真实版本"}，不传任意本机路径。直接生成的 PDF 嵌入 Noto Sans SC 字形子集，字体原件及 OFL 许可在 source/resources/fonts。新建复杂版式 PDF 可用 Word/PPT 作为内部排版来源，最终按用户要求交付；只有明确要求额外导出时设置 export_pdf=true；直接 Office 导出使用 operation=export、format=pdf 和真实 source。多个来源用 instruction + sources 交给后台分批读取，不把预览片段当完整资料。
