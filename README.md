# 瞬光伴行 v0.1.5

[v0.1.5 更新说明](RELEASE_NOTES_v0.1.5.md) · [语音配置与选型](docs/tts.md)

[English README](README.en.md) · [安装与下载清单](INSTALL_LIST.md) · [BGE-M3 模型 Release](https://github.com/Ou-morality-uni/shunguang-companion/releases/tag/bge-m3-5617a9f)

以《绝区零》叶瞬光为原型的非官方陪伴 Web 应用。支持角色对话、流式回复与停止、多模型连接、角色与世界知识检索及引用、天气与网页搜索、手动长期记忆、参考音频声音克隆、播放队列和休息提醒。电脑运行后端，电脑或同一 Wi-Fi 的手机通过浏览器使用；所有配置集中在“陪伴设置”。

## 首次安装

支持 **Windows 10/11 64 位、Python 3.11 64 位和 Node.js 24**。先安装 Python 与 Node.js，确认终端能运行 `py -3.11`（或 `python`）、`node` 和 `npm`。它们是基础运行时，项目安装脚本不会替你安装。建议16GB内存；脚本要求至少12GiB磁盘余量，首次安装需要联网下载数GB依赖和模型。

1. 获取项目。已安装 Git 时，可在 PowerShell 执行：

   ```powershell
   git clone https://github.com/Ou-morality-uni/shunguang-companion
   cd shunguang-companion
   ```

   也可点击 **Code → Download ZIP**，解压到普通文件夹并进入项目根目录。
2. 双击根目录 **`Install.bat`**。安装窗口会显示进度与错误；等待出现 `Installation success`。
3. 双击 **`Start_up.bat`**。CMD 显示后端日志，服务就绪后自动打开 `http://127.0.0.1:8000/`。
4. 在“陪伴设置 → 模型连接”填写自己的 API Key，读取并选择模型，保存并测试连接。

`Install.bat` 会创建两个隔离的 Python 环境，安装锁定的后端、前端和检索依赖，构建前端，创建空 SQLite 数据库，检查音频组件，下载并校验 BGE-M3，然后使用**仓库已附带的角色与世界资料**建立本地 Qdrant 索引并验证实际检索。不需要自己整理或添加 Markdown/TXT，也不需要另外安装 MySQL、Docker、CUDA Toolkit 或独立 Qdrant 服务。

安装会检查 NVIDIA 驱动与显存条件，尝试 CUDA 12.8 版 PyTorch并验证实际运算；条件不满足时使用CPU，CPU索引和检索可能较慢。脚本不会安装或修改显卡驱动。若缺少Microsoft Visual C++运行库，会从微软官方下载并检查签名，Windows可能要求管理员确认。主动使用CPU可执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Cpu
```

安装项目清单见 [INSTALL_LIST.md](INSTALL_LIST.md)。每次运行还会生成 **`data/install-list.md`**，列出本次处理的 Python包、实际安装的 npm包、模型文件、来源和数据库位置，区分已有依赖与本次安装；包管理器可能使用缓存。失败会返回非零退出码并保留阶段记录，不能把失败清单当作安装成功。

## BGE-M3 的下载和位置

完整模型在 [GitHub Release](https://github.com/Ou-morality-uni/shunguang-companion/releases/tag/bge-m3-5617a9f)，包括 PyTorch权重、tokenizer、配置、来源记录、模型卡和MIT许可。ZIP约1.42GB，解压后模型组件约2.3GB；不需要Git LFS。

**默认自动安装：**`Install.bat` 下载ZIP并验证包与每个模型组件的SHA256，解压到：

```text
source/resources/models/bge-m3/
├── pytorch_model.bin
├── config.json
├── tokenizer.json
├── tokenizer_config.json
├── special_tokens_map.json
├── sentencepiece.bpe.model
├── modules.json
├── 1_Pooling/config.json
├── model-provenance.json
├── MODEL-CARD.md
└── LICENSE.txt
```

**手动下载：**从Release下载 `bge-m3-5617a9f.zip`，把ZIP内的 `bge-m3` 文件夹解压到 `source/resources/models/`，确保权重最终位于 `source/resources/models/bge-m3/pytorch_model.bin`，然后运行 `Install.bat`。验证合格的现有模型会复用，不会重复下载。只有一个`.bin`文件不算完整模型。

下载缓存位于 `data/install/model-cache/`。网络中断后重新运行安装脚本即可尝试续传；哈希错误会明确停止。如果GitHub下载不可用，可明确选择锁定版本的官方Hugging Face来源：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -ModelSource official
```

默认不会静默切换模型或下载源。运行中更新索引可使用“世界档案”；命令行重建前关闭后端窗口：

```powershell
.\.venv-rag\Scripts\python.exe scripts/rag-cli.py rebuild
```

## 资源与个人数据

仓库附带原默认头像、5张立绘／壁纸、全部23张表情、默认参考MP3、参考片段及原始MP4，还有你可直接使用的角色／世界原始资料、历史版本和核实摘要。资料说明见 [资源目录](source/resources/README.md)。社区整理、听写存疑、剧透与未知内容保留标记，不代表所有设定均已核实。

每位使用者的密钥、本机配置、聊天、长期记忆、音频缓存和数据库都保存在自己的 `data/`，被Git忽略。新用户没有作者的聊天或个人记忆。密钥使用当前Windows账户DPAPI加密，不回显已有值：留空保留、输入替换、明确移除。更换电脑或Windows账户需重新填写。模型配置只在界面填写，不读取`.env`或`LLM_*`环境变量。

工程进度、交付清单、验收报告、私人日志和原开发Git历史不在公开仓库；README与安装清单是面向使用者的操作文档。安装不会替你填写API、购买服务、训练声音或上传参考音频。

## 声音、工具与提醒

- **声音与播放**：支持小米 MiMo、阿里云 Qwen 实时声音复刻和火山豆包声音复刻 2.0。小米选择本地参考 MP3 并明确允许外部处理；阿里云、火山填写已注册音色 ID，阿里云也可在页面授权后创建音色。支持边生成边分句朗读、提前准备下一句、停止、重播及静音。详细配置见 [TTS 接入与选型](docs/tts.md)。
- **工具服务**：天气使用Open-Meteo；网页搜索默认使用无需Key的公开入口，Tavily是可选配置。公开服务可能限流或要求验证；界面显示调用结果、失败和真实来源。
- **长期记忆**：手动总结会话、预览候选并确认，支持查看、编辑、冲突更新和删除；聊天历史与长期事实分别管理。
- **关怀提醒**：配置间隔、安静时段、暂停和测试。按时间触发，不检测坐姿；浏览器后台可能延迟，关闭页面后不能可靠提醒。

模型与声音服务需要使用者自己的可用API，可能按服务规则计费。Windows 使用 DPAPI；其他系统已增加系统密钥环后端，macOS/Linux 仍需实机验收。

## 同一 Wi-Fi 的手机访问

先关闭本机后端，再在项目根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-lan.ps1
```

首次设置至少10位访问口令，手机打开脚本显示的电脑IPv4地址并登录。手机不要用127.0.0.1访问电脑。脚本不修改防火墙、不开放公网。手机浏览器的软键盘和音频权限可能因设备不同。

## 更新与常见问题

- **更新**：先关闭后端，Git用户执行 `git pull`，再双击 `Install.bat`。ZIP用户下载新代码，保留自己的 `data/`，不要把它分享给别人。已有模型通过校验后复用，资料索引按版本增量更新。
- **安装失败**：查看窗口最后失败阶段及 `data/install-list.md`，解决网络、磁盘、基础运行时等问题后重新运行。不要把含私人数据的整个工程打包求助。
- **端口被占用**：关闭原后端或占用8000的程序；启动脚本不会杀掉不认识的进程。
- **停止后端**：在后端CMD按 `Ctrl+C` 或关闭该窗口；关闭网页不会停止后端。
- **没有声音**：核对自己的语音Key、参考文件及外部处理开关；浏览器阻止播放时先点击消息播放按钮。

本项目是非官方角色应用。原角色、游戏设定、图片和声音归各自权利方；本项目用于个人开发学习。AI回答和检索资料可能存在错误。


## 开发与长期维护

模块边界、数据迁移与后续技术债见 [维护指南](docs/maintenance.md)，本版本变化与验证范围见 [更新说明](RELEASE_NOTES_v0.1.5.md)。

开发环境安装 `backend/requirements-dev.txt` 后，可用 `python scripts/dev.py verify` 统一运行检查；接口变化后用 `python scripts/dev.py contracts` 更新契约。生产安装继续使用运行时锁文件。数据库升级会先自动备份旧库；升级后不要用旧程序直接打开新库。
