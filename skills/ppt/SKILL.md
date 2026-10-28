---
name: shunguang-ppt
description: 按资料制作原生可编辑的演示文稿，或按版本和对象定位修订。
---

先确定受众、目的和真实资料，复杂任务先给简短提纲确认。普通任务直接制作。有模板优先保持模板样式；修改现有稿时局部处理，不重建未涉及页面。

office_files 的 format=pptx，name 为 .pptx 文件名。spec 示例：

```json
{"slides":[{"title":"活动汇报","blocks":[{"type":"paragraph","text":"根据已确认资料整理的结论。"}]},{"title":"活动数据","blocks":[{"type":"table","rows":[["项目","人数"],["跑步","12"]]},{"type":"chart","chart_type":"bar","categories":["跑步","游泳"],"series":[{"name":"人数","values":[12,8]}]}]}]}
```

每页一个清楚目的，优先原生文字、表格和常规图表，不使用整页截图冒充可编辑内容。标题最多 90 字，每页最多四个内容块，表格最多 12 行 6 列，内容过多就拆页。图表必须有实际类别与匹配的数字。

修改已有稿先用 office_inspect 获得文件版本和 slide:页索引:对象ID，再提交 operation=edit 与 source。文字 spec 示例：{"edits":[{"target":"slide:1:2","old":"旧标题","text":"新的标题"}]}。只能使用真实返回的对象和原文，不重建未改页面；跨段或复杂对象修改需要细化目标。

项目适配采用 PPT Master 的规划思路及 MIT 包关系检查工具，保留来源于 ../vendor/ppt_master/。当前受控执行协议是本项目的结构化内容接口，不能把它称为完整的上游 SVG、动画、配音或视频导出流水线。结构检查不替代真实页面检查。

表格单元格目标为 slide:页索引:对象ID:cell:行:列，沿用 old/text。原生分类图表修改示例：{"edits":[{"target":"slide:0:3","chart":{"categories":["跑步","游泳"],"series":[{"name":"人数","values":[15,8]}]}}]}；先 inspect 原类别和数据，不擅自修改单位。复杂、组合或非分类图表需改用受支持副本，不宣称无损编辑。

新稿可插入本聊天已附图片块 {"type":"image","image":{"kind":"attachment","id":"真实ID","version":"真实版本"}}，保持比例，文字仍为原生对象。模板传 source + edits，不重建全部页。跨资料制作传 instruction + sources，省略 spec。复杂任务传 outline 等待确认；只有用户明确要求额外 PDF 时才设置 export_pdf=true，默认只交付 PPT。授权目录先 office_import，只有明确覆盖要求才传 overwrite=返回的 original，并等待系统确认。
