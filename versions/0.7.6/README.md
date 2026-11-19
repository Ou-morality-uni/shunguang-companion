# 瞬光伴行 v0.7.6

- Windows 的 `Install.bat` 优先复用可用的标准 64 位 CPython 3.11～3.14。没有已有项目环境或显式指定路径时，从检测到的兼容版本中选最高的版本。
- 只有找不到可用解释器时，才会复用应用专用的 3.14.10 缓存或准备官方 Python 3.14.10。下载包经过 SHA-256 与 Python Software Foundation 签名校验，安装到当前用户专用目录，不修改系统 PATH。
- 安装窗口现在显示实际使用的 Python 版本和完整路径；如需手动指定，可用 `Install.bat -PythonPath "D:\Programs\Python\python.exe"`。加 `-CheckPython` 只检查，不下载安装。
- 安装完成后双击 `Start_up.bat`。启动入口、Node.js 和 Linux 部署流程不变。

## 同版本补充修复

- Windows 安装不会再选用 LibreOffice 自带的 Python；无需修改系统 PATH 或卸载 LibreOffice。
- 修复 Windows 重定向服务器管理命令行的中文输出，并同步 OpenAPI 契约。应用版本仍为 v0.7.6。
