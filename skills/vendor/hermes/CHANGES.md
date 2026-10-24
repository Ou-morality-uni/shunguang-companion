# 小光适配记录

固定上游版本与原始文件哈希见 UPSTREAM.json。保留同目录 LICENSE。

- pdf/scripts/pdf_create.py 增加由调用方指定的已注册字体，并用于正文样式、表格和表头；用于中文 PDF。调用方另外校验内容类型、转义正文标记和限制文件范围。
- 其余当前选取的生成脚本保持原文，权限、范围、格式和输出检查由小光适配层完成。上游技能说明仅作来源保留，应用实际加载 skills/word、skills/excel 和 skills/pdf 的说明。
