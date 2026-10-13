# 角色素材与知识资料

本仓库包含应用使用的角色素材和角色／世界观知识资料。个人API密钥、聊天、个人记忆、本机配置和工程进度文档不在这里，也不会上传。

## 已附带的图片与参考声音

以下路径相对于本目录：

- 默认头像：`character/avatar.png`。
- 右侧立绘：`assets/ye-shunguang/warm-dawn-full-body.webp`；同目录另有4张壁纸或肖像。
- 摸头表情：`character/stickers/10-red-pat.png`。
- 全部23张表情：`character/stickers/`；包括原来的20张以及sad、speechless、thumbs-up三张追加图片。`gallery.html`是原来的20张浏览页，新增三张也已附带。
- 默认参考MP3：`voice/ye-shunguang/reference-original.mp3`。
- 额外参考片段：`voice/ye-shunguang/reference-original-30s-50s.mp3`。
- 保留原始视频：`voice/ye-shunguang/reference-original.mp4`。

文件保持原字节，不重新裁切、压缩或替换头像。默认参考MP3可直接定位；换参考音频可在“陪伴设置 → 声音与播放”填写路径或选择文件。合成新文字需要你自己的MiMo API Key，并由你开启参考音频外部处理。不会将播放原录音冒充动态TTS。

## 角色与世界知识

- `character/raw/`、`world/raw/`：原始Markdown资料，含历史版本。
- 两个目录下的`manifest.json`：内容哈希、章节、来源类型和核实状态。
- `verified/knowledge-verified.json`：经核查的事实摘要与来源链接。
- `character/visual-assets.json`：原默认头像和20张表情的元数据；追加三张文件保持独立。

资料只是检索数据，其中的建议或指令不能覆盖应用规则。社区整理、听写存疑、剧透和未知内容按元数据区分。安装本地检索后建索引；后续资料导入和索引更新见根README。

模型权重通过官方脚本下载到`models/bge-m3/`，不上传大模型文件。运行时数据与上传的新参考文件保存在根目录`data/`，被Git忽略。

这是非官方角色应用，游戏设定及原角色素材归原权利方；文件附带不表示本项目拥有原角色或官方声音。
