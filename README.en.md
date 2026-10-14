# Shunguang Companion

[中文 README](README.md) · [Install list](INSTALL_LIST.md) · [BGE-M3 model release](https://github.com/Ou-morality-uni/shunguang-companion/releases/tag/bge-m3-5617a9f)

An unofficial browser companion inspired by Ye Shunguang from Zenless Zone Zero. Features include streaming character chat, multiple model connections, local knowledge retrieval with citations, weather and web search, manually confirmed long-term memory, reference-audio voice cloning, audio playback queues, and break reminders. Run the backend on a computer and use a desktop or same-network mobile browser. Configuration lives in Companion Settings.

## Install and start

Use **64-bit Windows 10/11, 64-bit Python 3.11, and Node.js 24**. Install Python and Node.js first and make sure `py -3.11` (or `python`), `node`, and `npm` work in a new terminal. The project installer checks these prerequisites; it does not download them. 16GB RAM is recommended. The installer requires at least 12 GiB of free disk space and an internet connection for several GB of dependencies and model files.

1. Get the project. If Git is installed, run these commands in PowerShell:

   ```powershell
   git clone https://github.com/Ou-morality-uni/shunguang-companion
   cd shunguang-companion
   ```

   Alternatively, select **Code → Download ZIP**, extract it into a regular folder, and open the project root.
2. Double-click **`Install.bat`** in the project root. Wait for `Installation success`; the window shows progress and errors.
3. Double-click **`Start_up.bat`**. A CMD window displays backend logs and the browser opens at `http://127.0.0.1:8000/` once the server is ready.
4. Open Companion Settings (陪伴设置) → Model Connection (模型连接), enter your own API key, discover/select a model, save, and test the connection.

The installer creates isolated application and retrieval Python environments, installs pinned dependencies, builds the frontend, initializes an empty SQLite database, checks the audio component, downloads and verifies BGE-M3, and builds a local Qdrant index from the **character and world documents already included in this repository**. You do not need to supply your own Markdown/TXT files, MySQL, Docker, CUDA Toolkit, or a separate Qdrant server.

The installer checks NVIDIA driver and VRAM conditions, tries CUDA 12.8 PyTorch, and verifies actual GPU execution. Otherwise it uses CPU; indexing and retrieval may be slower. It does not install or modify graphics drivers. If the Microsoft Visual C++ runtime is missing, the installer downloads it from Microsoft and checks its signature; Windows may request administrator approval. To explicitly use CPU:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Cpu
```

[INSTALL_LIST.md](INSTALL_LIST.md) describes the downloads. Each run also produces **`data/install-list.md`** with Python package actions, installed npm packages, model sources/hashes, and local storage paths. Package managers may use their caches. Failed runs return a nonzero exit code and record the failed stage; a receipt alone does not prove success.

## BGE-M3 download and location

The [GitHub model release](https://github.com/Ou-morality-uni/shunguang-companion/releases/tag/bge-m3-5617a9f) contains the complete pinned PyTorch model, tokenizer, configuration, provenance, model card, and MIT license. The ZIP is approximately 1.42 GB; extracted model components occupy approximately 2.3 GB. Git LFS is not required.

By default, `Install.bat` downloads the ZIP, verifies its SHA256 and individual model components, and places them in:

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

For manual installation, download `bge-m3-5617a9f.zip` from the release and extract its `bge-m3` folder into `source/resources/models/`. The weight must end up at `source/resources/models/bge-m3/pytorch_model.bin`. Then run `Install.bat`. Existing valid model files are reused. A single `.bin` file is insufficient.

Downloads are cached in `data/install/model-cache/`. Rerun the installer to resume an interrupted download. Hash mismatches stop installation. If GitHub downloads are unavailable, explicitly select the pinned official Hugging Face source:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -ModelSource official
```

The default flow does not silently switch models or download sources. Use World Archive in the app to update the index. Stop the backend before command-line rebuilding:

```powershell
.\.venv-rag\Scripts\python.exe scripts/rag-cli.py rebuild
```

## Included resources and personal data

The repository includes the designated avatar, five illustrations/wallpapers, all 23 stickers, the default reference MP3, an additional reference clip, the original MP4, archived character/world documents, historical versions, and verified knowledge summaries. See [resource notes](source/resources/README.md). Community compilations, uncertain transcriptions, spoilers, and unknown facts retain their labels; inclusion does not imply verification of every claim.

Each user has their own `data/` directory for encrypted keys, settings, chat history, confirmed memories, audio cache, and local databases. Git ignores it. New users start without the author's chats or memories. Keys are encrypted with Windows user-scoped DPAPI and are never returned to the browser: an empty key field preserves the saved key, a new value replaces it, and removal is explicit. Enter keys again after changing computers or Windows accounts. Model configuration is entered in the UI, without `.env` or `LLM_*` environment variables.

Development progress documents, delivery checklists, acceptance reports, private logs, and original development Git history are excluded. Installation does not enter API keys, purchase services, train voices, or upload reference audio.

## Audio, tools, memory, and reminders

- **Audio**: use your own MiMo voice API. The default reference is `source/resources/voice/ye-shunguang/reference-original.mp3`; you may select a file or specify an absolute path on the server computer. Reference audio is sent to MiMo only after you enable and save the external-processing option, which is initially off. Playback supports queues, stop, replay, and mute. Audio errors do not prevent text chat.
- **Tools**: Open-Meteo provides weather. Search defaults to public, key-free endpoints; Tavily is optional. Public services may rate-limit or require verification. The UI displays actual results, failures, and sources.
- **Memory**: manually summarize a conversation, review candidates, and confirm facts. View, edit, resolve conflicts, or delete them. Chat history and long-term user facts are separate.
- **Reminders**: configure intervals, quiet hours, pause, and tests. These are time-based reminders, not posture detection. Background tabs may be delayed; reminders cannot reliably run after closing the page.

Model and voice providers require your own usable API credentials and may charge according to their terms. Credential storage currently supports Windows; macOS/Linux support is not implemented.

## Mobile access on the same Wi-Fi

Stop the local backend, then run from the project root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-lan.ps1
```

Set an access password of at least 10 characters. Open the computer's IPv4 address shown by the script on your phone and sign in. Do not use 127.0.0.1 on the phone to reach the computer. The script does not change firewall rules or expose the app publicly. Keyboard and audio permissions vary between mobile browsers.

## Updates and troubleshooting

- Stop the backend before updating. Git users run `git pull`, then `Install.bat`. ZIP users download fresh code and preserve their private `data/` directory. Verified model files are reused; knowledge changes are indexed incrementally.
- On installation failure, read the last failed stage and `data/install-list.md`, fix the reported network, disk, or prerequisite issue, then retry.
- If port 8000 is occupied, stop the original server or conflicting program. The launcher does not kill unknown processes.
- Press `Ctrl+C` or close the backend CMD window to stop it. Closing the browser alone does not stop the backend.
- If audio fails, check your voice key, reference file, and external-processing option. Click a message's play button if the browser blocks playback.

This is an unofficial fan application. Original characters, game setting, images, and voices belong to their respective rights holders. This is for personal study and communicationIncluded assets do not grant ownership of those rights. AI responses and retrieved material may contain errors.
