# 瞬光伴行 v0.6.0

[v0.6.0 更新说明](versions/0.6.0/README.md) · [语音配置与选型](docs/tts.md) · [LibreOffice 安装指南（0.6.1 准备）](versions/0.6.1/LibreOffice-install.md)

[English README](README.en.md) · [安装与下载清单](INSTALL_LIST.md) · [BGE-M3 模型 Release](https://github.com/Ou-morality-uni/shunguang-companion/releases/tag/bge-m3-5617a9f)

- [v0.6.0](versions/0.6.0/README.md)：整合聊天文件工作区、自动跨会话记忆、天气关怀、在线语音输入、会话模型选择与全局动态光效。
- [v0.5.6](versions/0.5.6/README.md)：更新暖霞红金布局与动态光效，支持导航折叠、紧凑状态与语音控制、可调宽及放大的独立文件预览。
- [v0.5.5](versions/0.5.5/README.md)：打通聊天附件与后台文件任务，支持长资料分批阅读、超限确认续接、总结自动另存和关键节点工作语音。
- [v0.5.4](versions/0.5.4/README.md)：新增六类资料阅读与上传、多文件总结、视觉能力及替代识别授权、自然工作语音和代码块朗读过滤。
- [v0.5.3](versions/0.5.3/README.md)：新增本机工作台、文件夹授权、文件任务与删除确认，支持操作记录、取消、备份和冲突保护恢复。
- [v0.5.2](versions/0.5.2/README.md)：修复角色身世与拜师检索，新增常驻角色事实及剧情年表，优化自然表达与记忆边界。
- [v0.1.5](versions/0.1.5/README.md)：完善模型与语音连接、流式朗读、自动记忆、表情及工具查询。

以《绝区零》叶瞬光为原型的非官方陪伴 Web 应用。支持角色对话、流式回复与停止、多模型连接、角色与世界知识检索及引用、天气与网页搜索、自动跨会话记忆与手动管理、参考音频声音克隆、播放队列和休息提醒。电脑运行后端，电脑或同一 Wi-Fi 的手机通过浏览器使用；所有配置集中在“陪伴设置”。

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

## LibreOffice：按需手动安装

**当前代码版本为 0.6.0；Office 创作编辑、页面排版预览、Office 转 PDF 和 Excel 重算仍属于开发中的 0.6.1。** 发布 LibreOffice 依赖包不代表这些应用功能已经交付。使用 0.6.0 的聊天、资料文字阅读和 Markdown 总结，无需为此安装 LibreOffice。

准备使用后续办公能力时，请阅读 [LibreOffice 下载与安装指南](versions/0.6.1/LibreOffice-install.md)：

1. 从 [LibreOffice 官网](https://www.libreoffice.org/download/download-libreoffice/) 下载 Windows x64 主程序；也可查看 [本项目 Releases](https://github.com/Ou-morality-uni/shunguang-companion/releases)，在维护者发布附件后下载 `LibreOffice-26.8.1-Windows-x64-installer-bundle.zip` 和同名 `.zip.sha256`。自动生成的 **Source code (zip)** 不是 LibreOffice 安装包。
2. ZIP 下载后先核对同页 SHA-256，再解压并运行其中的 MSI。推荐将下载包放在项目 `tools/installers/`，在自定义安装中把程序安装到项目 `tools/LibreOffice/`；安装向导需要填写完整路径。已有安装可直接沿用。
3. 自定义目录安装后，按指南将完整的 `tools/LibreOffice/program` 目录加入用户 PATH，重启小光后端；安装了支持 Office 检测的应用版本后，再点击“重新检测”。系统默认安装目录也受支持。

`Install.bat` 和 `Start_up.bat` **不会自动下载或安装 LibreOffice**。这个 ZIP 是主程序安装包与说明，不是免安装便携版；只把它解压到项目内不能启用引擎。LibreOffice 保留其原有许可，不适用本项目原创代码的非商业限制。

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

## 开始使用 0.6.0

- **模型选择**：在设置中保存可用的 API 连接后，可从输入区按服务切换模型及支持的思考强度；每个聊天独立记住选择，新聊天使用默认配置。
- **文件任务**：在聊天中拖入或上传文件，再发送自然语言要求。任务在后台执行，聊天显示短摘要；点击资料或成果入口打开右侧多标签工作区，查看进度、来源及完整 Markdown，支持主动朗读和下载。新成果保存在 `data/outputs/任务-<任务ID>/`。旧 `.doc/.xls/.ppt` 请先另存为 `.docx/.xlsx/.pptx`；0.6.0 不提供 Office 成品编辑或 PDF 导出。
- **语音输入**：在“声音与播放 → 语音输入”配置实际支持音频转写的 HTTPS 接口、模型和密钥。点击开始录音，再点击结束；文字先进入草稿，检查后自行发送。它与 TTS 朗读分别配置，文字模型或看图模型不一定支持转写。浏览器会请求麦克风权限。
- **个人资料与关怀**：在记忆空间填写称呼、常住城市和年龄；默认称呼为“小师妹”。城市供天气关怀使用，不需要填写详细住址。自动记忆与跨聊天整理可在长期记忆设置关闭；网页关闭后不继续天气提醒。

## 声音、工具与提醒

- **声音与播放**：仅保留小米 MiMo 与阿里云百炼。小米引用服务电脑的 MP3 路径；百炼可在页面临时提交录音、创建并保存多个云端音色，刷新、选择、复制和删除。支持 Qwen-Audio 3.1/3.0 流式合成；旧 Qwen-TTS 单独兼容，音色不能跨模型混用。支持分句朗读、停止、重播及静音。详细配置见 [TTS 接入与选型](docs/tts.md)。
- **工具服务**：天气使用Open-Meteo；网页搜索默认使用无需Key的公开入口，Tavily是可选配置。公开服务可能限流或要求验证；界面显示调用结果、失败和真实来源。
- **长期记忆**：根据明确自述自动保存用户资料与偏好，后台整理会话摘要，相关话题按需召回旧聊天并展示真实来源；已移除手动总结入口。支持编辑、忘记与自动记忆开关。后台整理可能额外调用所选模型，不保证记住所有历史细节；聊天历史、用户事实与游戏知识分开管理。
- **关怀提醒**：配置间隔、安静时段、暂停和测试，使用多组话术并结合常住城市天气；天气不可用时退回普通提醒。按时间触发，不检测坐姿；浏览器后台可能延迟，关闭页面后暂停，不补发离线积压。

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

## 许可与使用范围

本项目作者有权授权的原创代码采用 [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)。完整许可条款通过上述链接提供；以下中文说明帮助理解，具体权利、义务及例外以许可原文为准。这是一项非商业源码许可，不是符合 OSI 定义的开源许可证。

### 允许的使用

- 在许可允许的范围内，用于非商业学习、研究、实验、私人娱乐和个人兴趣项目。
- 为上述许可目的阅读、运行和修改代码，并按许可要求分享原版或修改版。
- 以商业目的出售源码、提供收费部署或托管服务、经营付费服务、集成进商业产品等用途，不在此非商业授权范围内；需要另行取得相关代码权利人的书面授权。

### 分发与版权声明

分发本项目原创代码或其修改版时，必须向接收者提供上述许可全文或许可链接，并保留本项目的以下声明及相关版权、许可声明。修改代码不意味着可以将原作者的成果冒充为自己独立完成的作品。

```text
Required Notice: 瞬光伴行 — https://github.com/Ou-morality-uni/shunguang-companion
```

第三方依赖、模型和其他第三方内容继续适用各自原有许可及使用条款，本节不替换或收紧其原有授权。再分发时也应保留这些内容所要求的版权与许可声明。

### 角色与声音的独立权利

本节的代码许可不授予《绝区零》、叶瞬光角色及其名称、形象、游戏设定、官方素材、第三方图片、录音或声音的使用权。相关权利归各自权利人；素材被收录或可下载，不代表本项目已经取得完整的再分发、声音复刻或商业使用授权。

使用、分享或复刻声音前，应确认对相应素材及声音具备必要权限，并遵守有关服务的条款。即使另行取得本项目原创代码的商业授权，也仍需独立解决角色、图片和声音等第三方权利；不得以本项目名义暗示获得游戏官方授权或背书。


## 开发与长期维护

模块边界、数据迁移与后续技术债见 [维护指南](docs/maintenance.md)，本版本变化与验证范围见 [更新说明](versions/0.6.0/README.md)。

开发环境安装 `backend/requirements-dev.txt` 后，可用 `python scripts/dev.py verify` 统一运行检查；接口变化后用 `python scripts/dev.py contracts` 更新契约。生产安装继续使用运行时锁文件。数据库升级会先自动备份旧库；升级后不要用旧程序直接打开新库。
