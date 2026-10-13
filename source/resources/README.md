# 本地资源

公开仓库仅包含 `verified/knowledge-verified.json` 的少量事实摘要与来源链接。开发记录、私人资料、完整原始资源、图像、录音和大模型权重没有上传。

## 图片与参考声音

按需在自己电脑创建以下路径并放入有权使用的文件：

- 默认头像：`character/avatar.png`。
- 右侧立绘：`assets/ye-shunguang/warm-dawn-full-body.webp`。
- 摸头表情：`character/stickers/10-red-pat.png`。
- 默认参考MP3：`voice/ye-shunguang/reference-original.mp3`；也可通过陪伴设置选择/上传自己的MP3。

这些路径相对于本目录。没有图片会显示占位；参考音频缺失时TTS明确提示，文字聊天仍可用。素材与语音属于本机资源，默认被Git忽略。

## 角色/世界资料

从根README的导入命令添加Markdown/TXT。导入工具保存原文、哈希、历史版本和manifest，资料只是检索数据，不会作为系统指令。新资料需更新索引。

模型通过 `scripts/install-rag.ps1` 及官方下载脚本安装到 `models/bge-m3/`；不要把模型文件、私人参考录音或用户数据提交到GitHub。
