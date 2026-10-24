# LibreOffice 下载与安装指南（Windows）

本指南随 0.6.1 开发提供，不表示该版本已完成验收。LibreOffice 是独立的第三方软件，用于 Office 页面预览、Office 转 PDF 和 Excel 公式重算。普通聊天和已有文件的文字内容阅读不要求安装它。

`Install.bat` 和 `Start_up.bat` 当前均不会下载或安装 LibreOffice。把安装包放进项目目录或 GitHub Releases，也不会自动安装。

## 1. 下载官方安装包

打开 [LibreOffice 官方下载页](https://www.libreoffice.org/download/download-libreoffice/)，选择与你的电脑匹配的 Windows 安装包；本项目的 Windows 安装环境为 64 位。下载主程序安装包即可，离线帮助包不是本项目的必需依赖。

如果本项目将来在 GitHub Releases 提供 LibreOffice 附件，也可以下载对应系统和架构的附件。目前不在此填写尚未发布的下载地址。镜像附件应保留官方安装包原样，并附版本、SHA-256、许可证和对应版本的源代码获取说明。

### 从项目 Releases 下载时如何校验

在 [项目 Releases](https://github.com/Ou-morality-uni/shunguang-companion/releases) 的 **Assets** 中查找 `LibreOffice-26.8.1-Windows-x64-installer-bundle.zip` 和同名 `.zip.sha256`。只有维护者上传并发布后才会出现；没有附件时使用上面的官网下载入口。GitHub 自动生成的 **Source code (zip)** 是项目源码，不是 LibreOffice 安装包。

将两个文件保存到同一下载目录，在该目录打开 PowerShell，分别执行：

```powershell
Get-FileHash -LiteralPath .\LibreOffice-26.8.1-Windows-x64-installer-bundle.zip -Algorithm SHA256
Get-Content -LiteralPath .\LibreOffice-26.8.1-Windows-x64-installer-bundle.zip.sha256
```

比较第一条输出的 `Hash` 与第二条输出开头的 64 位摘要，大小写不影响比较；应完全一致。不一致时停止使用并重新下载。校验一致后解压 ZIP，阅读其中的 `INSTALL.md`，再运行 MSI；不要把 ZIP 直接改名为 MSI。也可以按包内 `SHA256SUMS.txt` 进一步核对 MSI 和说明文件。

## 2. 推荐的项目内放置位置

下面的路径均相对于包含 `Start_up.bat` 的项目根目录：

```text
项目根目录/
├─ Start_up.bat
├─ Install.bat
└─ tools/
   ├─ installers/
   │  └─ LibreOffice_实际版本_Win_x86-64.msi  ← 下载的安装包
   └─ LibreOffice/                         ← 安装向导中选择的目标目录
      └─ program/
         ├─ soffice.com
         └─ soffice.exe
```

安装包文件名以实际下载为准。可以先新建 `tools/installers/` 保存安装包；它只是下载存放位置，不能代替安装后的程序目录。

双击安装包，在安装向导中选择“自定义 / Custom”，将目标目录设为当前项目根目录下的 `tools/LibreOffice/`。安装向导需要的是完整路径，请在资源管理器中复制项目目录，再补上 `\tools\LibreOffice`。是否弹出管理员授权由 Windows 安装程序决定。

不需要为了小光把 LibreOffice 设为 Word、Excel 或 PPT 的默认打开程序，也不需要设置开机启动。安装完成后，确认 `tools/LibreOffice/program/soffice.com` 存在。

如果电脑已经安装 LibreOffice，优先沿用现有安装，无需再安装一份。选择系统默认位置 `C:\Program Files\LibreOffice` 也可以，当前程序会检查该常见位置。

## 3. 让小光找到项目内的安装

**当前检测逻辑检查 PATH 和系统常见安装位置，不会自动扫描 `tools/LibreOffice/`。使用上面的自定义位置，还需要完成以下配置。**

1. 在 Windows 开始菜单搜索并打开“编辑账户的环境变量”。
2. 在“用户变量”中选中 `Path`，点击“编辑”，再点击“新建”；保留已有条目。
3. 添加本次安装的完整 `program` 目录路径，即“项目根目录的完整路径 + `\tools\LibreOffice\program`”。不要填写 `.msi` 安装包、`soffice.exe` 文件路径或字面上的相对路径。
4. 保存后，关闭原来的小光后端窗口和终端，从新打开的资源管理器或终端重新运行 `Start_up.bat`。如果仍继承旧环境，可注销并重新登录 Windows 后再启动。
5. 在小光的 Office 依赖检测区域点击“重新检测”，确认显示 LibreOffice 可用。

也可以在新打开的 PowerShell 中运行下面的只读检查：

```powershell
soffice.com --version
```

正常时会显示 LibreOffice 版本。若提示找不到命令，先检查 PATH 中的目录是否正确、安装是否完成，以及终端是否已经重新打开。检测成功只说明引擎可启动，实际文档转换效果仍取决于文件内容、字体和格式兼容性。

## 4. 移动项目、更新和公开发布

- 这里是把常规 LibreOffice 安装到自定义目录，不是便携版。安装完成后不要直接剪切程序文件夹；项目换位置时，应通过安装程序重新安装或调整安装位置，并更新 PATH。
- LibreOffice 升级由用户手动进行，本项目当前不会自动更新它。
- 本地的 `tools/LibreOffice/` 程序和 `tools/installers/` 安装包不属于小光源码，不要通过 GitHub Desktop 将它们提交到源码仓库，也不要复制进 `output/github-public`。本指南可以随独立版本说明同步；如需分发安装包，应作为 Releases 的独立附件提供。
- 本指南不改变项目原有的 Python、Node.js 和项目依赖安装步骤。LibreOffice 也不能替代模型服务或 API 配置。

参考：[官方安装步骤](https://www.libreoffice.org/installation-instructions/)、[许可证与再分发要求](https://www.libreoffice.org/licenses/)。
