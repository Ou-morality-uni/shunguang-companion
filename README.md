# 瞬光伴行

以《绝区零》叶瞬光为原型的非官方陪伴 Web 应用。电脑运行后端，浏览器聊天；每个人填写自己的 API，不共享作者的密钥和数据。

支持角色对话与流式回复、会话历史、多模型配置、角色知识检索、天气/网页搜索、手动长期记忆、参考音频 TTS、休息提醒。界面采用暖霞拾光红金三栏，所有配置集中在“陪伴设置”。

## 1. 准备环境

目前按 Windows 使用。安装 **Python 3.11** 和 **Node.js 24**，确认终端可执行 `python` 与 `npm`。凭据使用 Windows 当前账户加密，macOS/Linux 尚未适配密钥存储。

点击仓库页面 **Code → Download ZIP** 并解压，或通过 Git 克隆。必须进入解压后的项目根目录，不能在 ZIP 里面直接启动。

## 2. 首次安装

在项目根目录打开 PowerShell，执行一次：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

脚本创建项目虚拟环境、安装锁定依赖并构建前端。需要网络，不需要复制作者的虚拟环境、数据库或模型文件。

## 3. 启动与填写自己的 API

双击根目录 **Start_up.bat**。CMD 显示后端日志，服务就绪后自动打开 `http://127.0.0.1:8000/`。

1. 打开“陪伴设置 → 模型连接”。
2. 选择提供商和协议，填写你自己的 API Key。
3. 读取可用模型并选择；上游没有列表权限时手动填写模型 ID。
4. 保存并测试连接，再开始聊天。

模型配置只在界面填写，不读取 `.env` 或 `LLM_*` 环境变量。支持 MiMo、DeepSeek 和自定义兼容接口；OpenAI 兼容与 Anthropic 兼容使用不同适配。其他服务是否可用取决于接口与权限。

已有密钥不回显：留空保留、填写替换、明确移除。数据和加密配置保存在你自己电脑的 `data/`，该目录被 Git 忽略。不同 Windows 账户或电脑需重新填写密钥。

保持后端 CMD 窗口打开。关闭它可停止后端，`Ctrl+C` 用于正常退出；关闭网页本身不会停止后端。再次启动发现已有服务时只打开网页，日志及停止操作仍在原后端窗口。

## 4. 其他配置

- **工具服务**：天气使用 Open-Meteo；默认网页搜索无需 Key，使用公开搜索入口。公开服务可能限流或要求验证。Tavily 是可选配置，需要你自己的有效 Key。
- **长期记忆**：初始为空。手动总结会话、核对候选后确认；可编辑、处理冲突与删除。聊天历史和长期事实分别管理。
- **声音与播放**：当前使用 MiMo `mimo-v2.5-tts-voiceclone`。填写自己的语音 API Key，选择自己的本地参考 MP3，保存后合成新文字。选择文件会自动选中，支持重新选择。默认路径为 `source/resources/voice/ye-shunguang/reference-original.mp3`，也可使用服务电脑上的绝对路径。
- **参考音频外传**：默认关闭。开启并保存后，合成会将所选音频发给 MiMo；本地选择/验证不会外传。没有参考音频或未授权时不会改用预置音色。支持排队、停止、缓存重播与静音，语音失败不影响文字聊天。
- **关怀提醒**：设定间隔、安静时段和暂停；文字提醒可配合已配置的 TTS。它不检测坐姿，浏览器后台可能延迟，关闭页面后不能可靠提醒。

模型和工具请求会发送到你配置的服务，使用服务可能产生其规定的费用。

## 5. 可选：本地知识检索

基础聊天不需要安装本地 embedding。本仓库包含角色与世界观原始资料、版本清单，以及经过核实的事实摘要。资料中的社区整理、听写存疑、同人和剧透标签保留，不代表所有设定都已核实。

有合适 NVIDIA GPU 时：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-rag.ps1
```

没有 NVIDIA GPU 时可选择 CPU 安装路径，性能取决于电脑：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-rag.ps1 -Cpu
```

这一步单独安装 PyTorch/BGE-M3/Qdrant，下载约2.3GB的官方权重及配套组件，执行推理检查并建索引。无需另装 Docker 或独立 Qdrant 服务。下载文件按固定版本与 SHA256 校验，失败会明确报错。

添加你自己的 UTF-8 Markdown/TXT 资料：

```powershell
.\.venv\Scripts\python.exe scripts/import-character-resource.py 'D:\my-materials\character.md'
.\.venv\Scripts\python.exe scripts/import-character-resource.py 'D:\my-materials\world.md' --category world
```

导入后在“世界档案”点击更新索引。命令行重建前关闭后端，避免同一 Qdrant 库被两个进程占用：

```powershell
.\.venv-rag\Scripts\python.exe scripts/rag-cli.py rebuild
```

## 6. 可选：图片和手机访问

仓库已包含默认头像、5张立绘/壁纸、23张表情包、参考MP3及原始MP4。下载后无需另行寻找这些角色素材。默认参考声音为 `source/resources/voice/ye-shunguang/reference-original.mp3`；使用TTS仍需自己的MiMo API Key，并自行选择启用参考音频外部处理。素材位置与知识资料说明见 [资源说明](source/resources/README.md)。

你的API密钥、聊天、个人记忆及本机配置均在 `data/`，不会随代码分享。模型权重不上传，由可选检索安装脚本下载。工程进度文档、测试报告和作者的旧开发Git历史也不包含在仓库中。

同一可信 Wi-Fi 下使用手机：先停止本机后端，再执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-lan.ps1
```

首次设置至少10位访问口令，手机打开脚本显示的电脑 IPv4 地址并登录。手机不要使用127.0.0.1访问电脑。脚本不修改防火墙或开放公网。真实手机的键盘、布局与音频权限可能因设备而不同。

## 常见问题

- 找不到 `python` / `npm`：确认安装了上述运行时，重开终端。
- 缺少虚拟环境或前端构建：先完成首次安装，并查看安装窗口错误。
- API认证、额度或模型列表失败：核对自己提供商的地址、协议、模型权限和 Key。
- 8000被其他程序占用：先停止占用者；启动脚本不会杀掉不认识的进程。
- 语音没有参考文件：在“声音与播放”选择自己的 MP3，保存并按需启用外部处理。
- 浏览器阻止音频自动播放：先点击消息播放按钮。
- 想更新代码：Git用户先停止后端、`git pull`，然后重新运行安装脚本；ZIP用户重新下载代码，不要覆盖或分享私人 `data/`。

本应用不是官方产品。角色设定及游戏名称归原权利方；AI回答和检索材料可能存在错误。
