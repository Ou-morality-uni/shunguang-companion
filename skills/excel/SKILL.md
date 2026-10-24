---
name: shunguang-excel
description: 制作有真实数值、公式和原生图表的 Excel 工作簿。
---

先确认原始数据、单位、期间和目标，保留原始资料及必要来源。缺失数据不得填为零或编造。不创建无意义的工作表。

通过 office_files 提交 format=xlsx 和单个 .xlsx 文件名。spec 使用 sheets 数组：

```json
{"sheets":[{"name":"活动统计","rows":[["项目","人数"],["跑步",12],["游泳",8]],"charts":[{"type":"bar","title":"活动人数","data":"B1:B3","categories":"A2:A3"}],"freeze_panes":"A2","column_widths":{"A":22,"B":14}}]}
```

数值保持数字类型，公式用单元格对象的 formula 字段，例如 {"formula":"=SUM(B2:B3)"}，不要将全部结果写成字符串。支持 bar、line、pie 原生图表，指定正确数据范围与类别。只使用当前任务需要的常规功能，不创建外部数据连接、宏或脚本。

修改已有文件先用 office_inspect 取得实际版本和单元格目标，再提交 operation=edit 与 source。spec 示例：{"edits":[{"target":"s:0:B2","old":"12","value":15}]}。公式使用 formula 字段而非 value，不能猜测目标或跳过原文检查。

写入公式不代表已完成计算。必须区分结构检查、真实重算、关键值核对和页面检查；引擎缺失或公式失败时给出原因，不能报告计算已验证。完成前以实际任务结果为准。

执行工具基于 Hermes MIT 工具适配，来源与许可见 ../vendor/hermes/UPSTREAM.json 及 LICENSE。

模板须传 source 并使用 edits；多个资料传 sources 和 instruction，省略 spec，由后台完整分批阅读。复杂任务传 outline 等待确认。export_pdf=true 可同时交付 PDF；包含公式时必须实际重算成功才发布，空缓存或公式错误会中止，不当作零。仅支持常规公式；宏、外部链接、数据连接及无法可靠保留的复杂对象会被拒绝。不要承诺所有 Excel 函数兼容。

授权目录文件先 office_import；仅用户明确要求覆盖时将返回的 original 传给 overwrite，系统要求确认并保存恢复备份。每条修改引用实际 source/version/target，不能将选区或页码猜成单元格。
