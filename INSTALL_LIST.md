# Install list / 安装与下载清单

入口：根目录 `Install.bat` → `scripts/install.ps1` → `scripts/install-project.py`。

本文件列出默认完整安装涉及的组件。每次安装的实际包名、版本、处理状态和模型文件SHA256会写入 **`data/install-list.md`**；详细阶段记录在 `data/install/result.json`。这些本机记录不上传GitHub。

## 基础条件：脚本不会下载

- Windows 64位。
- Python 3.11 64位，含标准库SQLite。
- Node.js 24，含npm。
- 可用的NVIDIA驱动用于GPU模式；脚本不会安装显卡驱动。

## 下载或从包管理器缓存安装

| 类别 | 组件与版本 | 来源 | 安装位置 |
|---|---|---|---|
| Windows原生运行库（缺失时） | Microsoft Visual C++ v14 x64运行库，验证微软数字签名 | [微软官方](https://aka.ms/vc14/vc_redist.x64.exe) | 系统运行库；可能需要管理员确认 |
| 后端 | FastAPI、Uvicorn、LangChain、OpenAI SDK、HTTPX、DPAPI相关运行依赖等全部锁定包 | PyPI；完整版本见 [requirements.lock.txt](backend/requirements.lock.txt) | `.venv/` |
| 音频 | `imageio-ffmpeg==0.6.0`，Windows wheel附带FFmpeg | PyPI，包含在后端安装中 | `.venv/Lib/site-packages/imageio_ffmpeg/` |
| 前端 | React、TypeScript、Vite、assistant-ui、shadcn相关组件、Tailwind、Motion等全部锁定包 | npm registry；完整版本见 [package-lock.json](frontend/package-lock.json) | `frontend/node_modules/` |
| 模型运行 | `torch==2.11.0`；自动选择CUDA12.8或CPU wheel及其依赖 | `download.pytorch.org/whl/cu128` 或 `/cpu` | `.venv-rag/` |
| 检索 | `transformers==4.57.6`、`qdrant-client==1.19.1`、`sentencepiece==0.2.1`、`numpy==2.2.6`及全部锁定依赖 | PyPI；完整版本见 [requirements-rag.lock.txt](backend/requirements-rag.lock.txt) | `.venv-rag/` |
| BGE-M3 | `BAAI/bge-m3`，revision `5617a9f61b028005a4858fdac845db406aefb181`；完整ZIP约1.42GB | [本仓库Model Release](https://github.com/Ou-morality-uni/shunguang-companion/releases/tag/bge-m3-5617a9f) | `source/resources/models/bge-m3/` |

模型ZIP附带：`pytorch_model.bin`、`config.json`、`tokenizer.json`、`tokenizer_config.json`、`special_tokens_map.json`、`sentencepiece.bpe.model`、`modules.json`、`1_Pooling/config.json`、`model-provenance.json`、`MODEL-CARD.md`、`LICENSE.txt`。包和组件校验值见 [模型Release清单](source/resources/verified/bge-m3-release.json)。

选择 `-ModelSource official` 时，从固定上游版本的Hugging Face下载相同模型组件，实际来源会记录。默认来源失败会停止，不会偷偷替换模型。依赖已安装时可能复用；`npm ci`会按锁文件重建前端依赖。

## 自动创建或构建：不需要下载数据库服务

| 项目 | 行为 | 位置 |
|---|---|---|
| SQLite | Python自带SQLite，新安装创建空的会话、消息、长期记忆和记忆候选表；已有数据保留 | `data/companion.sqlite3` |
| 本地Qdrant | Python包以文件模式运行，用附带资料建1024维向量索引；无需Docker或服务端 | `data/rag/qdrant/` |
| 索引元数据 | 保存资料版本、哈希、切分数和构建状态 | `data/rag/index-state.json` |
| 推理验证 | 执行真实本地embedding、建索引和身份资料检索；成功后才标记检索环境可用 | `data/install/retrieval.json`、`.venv-rag/rag-runtime.json` |
| 前端产物 | TypeScript检查与Vite生产构建 | `frontend/dist/` |
| 下载缓存 | 模型下载缓存与断点文件，重新运行可尝试续传 | `data/install/model-cache/` |
| 实际安装清单 | 本次pip处理、已安装npm包、模型与存储位置；失败也记录阶段 | `data/install-list.md` |

## 已在仓库中：无需使用者另外准备

默认头像、5张立绘／壁纸、23张表情、默认MP3、参考片段和原MP4；角色与世界资料及历史版本、manifest、核实摘要。安装直接索引这些资料。

安装不调用付费聊天/TTS服务，不读取或上传作者的私人数据，不购买服务、不训练声音。API须由使用者在设置中自行填写；参考音频外传默认关闭。

## English

Double-click `Install.bat`. Python3.11 and Node.js24 are prerequisites, not downloads. If missing, it downloads the signed Microsoft Visual C++ runtime from Microsoft. The installer installs the pinned backend/frontend dependencies, FFmpeg bundled with its Python wheel, PyTorch, Transformers, Qdrant's local Python runtime, and the full verified BGE-M3 release. It creates an empty SQLite database, builds the bundled knowledge index, and builds the frontend. No MySQL, Docker, CUDA Toolkit, or separate Qdrant service is needed.

See the linked lock files for exact package versions. Each run writes a detailed local receipt to `data/install-list.md`, identifying pip actions, installed npm packages, model hashes/sources, and storage paths. Existing packages may be reused and package managers may use caches. A failed run is clearly marked failed. No API service calls or reference-audio uploads happen during installation.
