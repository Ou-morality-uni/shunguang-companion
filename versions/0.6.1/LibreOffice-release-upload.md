# 将 LibreOffice 依赖包放到 GitHub Releases

本文说明如何由项目维护者手动上传第三方依赖包；不会自动提交、推送或发布。小光 0.6.1 尚在开发，发布 LibreOffice 依赖包不代表小光 0.6.1 已完成。

## 要上传的文件

本地打包完成后，使用项目 `delivery/` 目录中的这两个文件：

- `LibreOffice-26.8.1-Windows-x64-installer-bundle.zip`
- `LibreOffice-26.8.1-Windows-x64-installer-bundle.zip.sha256`

ZIP 内应包含未经修改的官方 Windows x64 MSI、安装指南、许可证/第三方说明、对应源码获取说明和内部文件校验清单。它是完整的主程序安装包及说明集合，不是免安装便携版，也不是小光项目或个人使用环境的备份；不含离线帮助包、Java、Python、Node.js 或用户数据。

不要上传本机安装后的整个 `tools/LibreOffice/`、`data/`、配置文件、日志或验收资料。不要在 GitHub Desktop 中提交 ZIP 或 MSI；它们应作为 Releases 附件上传。

## 方式一：单独发布依赖包（推荐）

1. 浏览器打开你自己的 GitHub 项目仓库，登录有该仓库写权限的账户。
2. 在仓库主页右侧点击 **Releases**，然后点击 **Draft a new release**；第一次发布时按钮可能为 **Create a new release**。
3. 在 **Choose a tag** 输入 `deps-libreoffice-26.8.1-win-x64`，选择创建这个新标签；**Target** 选择你的公开项目分支。该标签只标记这次依赖包发布，不要使用尚未完成的小光版本标签。
4. **Release title** 填写 `LibreOffice 26.8.1 · Windows x64 依赖安装包`。
5. 将下方“可复制的发布说明”粘贴到描述框。
6. 在 **Attach binaries by dropping them here or selecting them** 区域拖入上述 ZIP 和 `.sha256` 文件，等两个附件上传完成。
7. 取消 **Set as latest release**（如有该选项），避免这个依赖包取代小光应用的最新版本。它不是小光测试版，不必仅因“依赖包”身份勾选 **pre-release**。
8. 先点击 **Save draft**，核对附件名称、大小、版本和描述。检查无误后由你点击 **Publish release**。如果仓库开启不可变发布，务必在发布前确认所有附件齐全。
9. 发布后展开 **Assets**，右键 ZIP 复制下载链接。可以将该真实链接补充到本版本的 `LibreOffice-install.md`，与官方下载链接一起提供；不要改成指向自动生成的 **Source code (zip)**。
10. 用浏览器重新下载一次 ZIP，按同页 `.sha256` 核对外层 ZIP 摘要，并解压查看文件是否齐全。这一步由维护者在实际上传后完成，本地打包检查不能代替线上下载检查。

## 方式二：附到已有的小光 Release

如果已有适合的正式应用 Release，而且允许修改附件，可以进入该 Release，点击编辑/铅笔按钮，在附件区域上传 ZIP 与 `.sha256`，补充依赖说明后点击 **Update release**。若已启用不可变发布而不能增加附件，使用上面的独立依赖 Release。

## 可复制的发布说明

```markdown
## LibreOffice 26.8.1 · Windows x64

这是小光的可选 Office 引擎依赖包，提供未经修改的 LibreOffice 官方主程序安装包、安装指南、许可证、源码获取说明及 SHA-256 校验清单。

- 用途：Office 页面预览、Office 转 PDF、Excel 公式重算；需搭配支持这些功能的小光版本使用。
- 系统：Windows x64；不适用于 Windows ARM64、macOS 或 Linux。
- 安装：解压 ZIP，阅读 INSTALL.md，运行 MSI 并选择自定义目录。推荐安装到小光项目根目录下的 tools/LibreOffice/，再按指南配置 PATH 并重新检测。
- 此包不是便携版，不会随小光的一键启动脚本自动安装；已有 LibreOffice 可优先沿用。
- 官方项目：https://www.libreoffice.org/
- 许可证：https://www.libreoffice.org/licenses/
- 对应版本源码获取方法见包内 SOURCES.md；第三方版权与许可见包内 licenses/。
- LibreOffice 由 The Document Foundation 及其贡献者提供。本项目提供下载镜像及使用说明，不代表官方发布或背书，也没有修改安装包。

下载 Assets 中的 LibreOffice-26.8.1-Windows-x64-installer-bundle.zip。
外层压缩包校验值见同名 .zip.sha256；解压后的 MSI 校验值见 SHA256SUMS.txt。
```

页面步骤依据 [GitHub 官方发布管理指南](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository?tool=webui)。按钮文案可能随语言和界面更新略有变化。
