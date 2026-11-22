# 瞬光伴行 v0.7.13 · 稳定版

Windows 本机用户可以在「陪伴设置 → 关于与更新」手动检查正式或抢先 Release。发现更高版本且更新包就绪时，点击「立即更新」，保留页面等待重启。默认渠道是稳定版；手机和服务器用户可查看发布信息。

从 v0.7.11、v0.7.12 等早期版本过渡时，先停止原服务，备份项目和 data，使用本版完整源码及 Install.bat 完成一次安装。ZIP 用户更新现有目录时保留 data 和本地配置。后续通过 Start_up.bat 启动即可使用网页更新。安装需要足够空间暂存程序包和数据备份。配置、附件与历史仍属于原项目目录。

## 维护者发布

1. 用 GitHub Desktop 打开公开副本，核对本版改动，Commit to main → Push origin，等待 Verify 通过。
2. 打开仓库 Releases → Draft a new release，从已上传的提交创建标签 v0.7.13，填写本版说明。稳定版保留正式发布选项；以后发布抢先版时勾选 Set as a pre-release。
3. 点击 Publish release 后查看 Actions → Package Windows update。完成后，在 Release 资产中核对 shunguang-0.7.13-windows.zip。草稿、标签与版本号不符、缺少构建包或校验摘要的 Release 无法安装。
