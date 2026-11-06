# Linux 服务器部署与维护

适用：Linux amd64／x86_64，推荐 Ubuntu 24.04 LTS。保留 Web、记忆、云端模型及可选 QQ，不安装 BGE-M3。4 GB 内存较有余量；2 GB 仅作为受限试运行目标，不能保证所有负载下长期稳定。

## 准备部署包

在 Windows 开发电脑完成安装和前端构建后，在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts/package-server.py --output 服务器部署
```

得到 `ye-shunguang-server-lite-0.7.3-linux.zip` 与 `.zip.sha256`，包内有已构建前端，无需服务器安装 Node。包不含个人密钥、聊天、模型权重，也不是离线镜像包；初次构建需要 Docker Hub 和 PyPI 网络。

下载者如只取得 GitHub 源码，同样需要先构建前端并打包。不能将源码 ZIP 当成已经构建的服务器部署包。已有维护者提供的部署包可直接使用。

## 服务器首次安装

1. 使用自己的 SSH 登录方式连接服务器，核对 `cat /etc/os-release`、`uname -m`、`free -h`、`df -h /`、`sudo ss -lntp`。检查已有业务，不为部署重装系统或强杀进程。
2. 按 [Docker 官方 Ubuntu 安装指南](https://docs.docker.com/engine/install/ubuntu/) 准备 Docker Engine 28+ 和 Compose 插件；已有合格版本直接复用。至少留约 10 GB 初始磁盘余量，后续关注图片和备份增长。
3. 上传部署包和校验文件，执行 `sha256sum -c ye-shunguang-server-lite-0.7.3-linux.zip.sha256`，解压到新的空目录，例如 `/opt/shunguang-0.7.3`，进入包内目录，运行 `sudo python3 manage.py verify`。
4. 默认只安装 Web：

   ```bash
   sudo bash install.sh
   ```

   按提示设置至少 10 位管理密码；脚本创建独立持久化数据和加密主密钥，构建并启动应用。默认不会下载／启动 NapCat，不需要机器人 QQ 号。

5. 本地电脑建立 SSH 隧道：

   ```powershell
   ssh -N -L 18000:127.0.0.1:8000 用户名@服务器IP
   ```

   保持窗口打开，浏览器访问 `http://127.0.0.1:18000/`，登录后填写自己的模型、声音、搜索服务。模型配置通过界面填写，不读取 `.env` 内的模型密钥。

管理端口保持 loopback，不为了省略隧道将其直接暴露公网。服务器默认启用后台重启策略；关闭电脑或浏览器不停止服务器后台。

### 首次构建下载很慢

默认从官方PyPI安装锁定依赖。如果网络较慢，可明确选择镜像运营方提供的软件源，例如：

```bash
sudo bash install.sh --pip-source tencent
# 或明确选择阿里云：sudo bash install.sh --pip-source aliyun
```

可选值是 `official`、`tencent`、`aliyun`。选择记录在本部署的 `.env`，后续构建沿用；不改全局pip配置、不关闭TLS校验，也不自动换源。镜像可能同步滞后，某个锁定版本缺失时应检查失败信息并重新明确选择其他源，而非取消版本锁定。说明见[腾讯云软件源文档](https://cloud.tencent.com/document/product/213/8623)和[阿里云镜像站](https://developer.aliyun.com/mirror/pypi/)。已有部署也可私下修改 `.env` 的 `PIP_SOURCE` 后按更新流程构建。

## 可选 QQ

先阅读 [QQ 指南与使用说明](qq-setup.md)。你可自行安装官方 NapCat 桥接并连接本机 OneBot。

如明确选择使用包内 Docker 桥接编排，可以在**首次安装**时执行：

```bash
sudo bash install.sh --with-qq
```

这条命令才会下载并运行可选 NapCat 镜像、询问机器人号。需本人扫码登录和绑定；初始化连接不等于已登录，也不自动授权群聊天。默认应用上限512 MB，桥接上限1024 MB，限额不是稳定性承诺。

已完成 Web-only 安装后，如需启用包内桥接，在原目录 `.env` 将 `COMPOSE_PROFILES=` 改为 `COMPOSE_PROFILES=qq`，保留其他字段和 runtime 路径，再运行 `sudo docker compose up -d napcat`。使用现有生成配置，私下查看 `runtime/napcat.env` 内 WebUI 登录 Token；OneBot Token 位于 `runtime/napcat/config/onebot11.json`，不要发给他人。网页 QQ 接入内填入自己的机器人号、OneBot Token并启用，按指南绑定和授权。

打开 NapCat 面板可另外建立 `-L 16099:127.0.0.1:6099` 转发，然后访问 `http://127.0.0.1:16099/webui/`。Windows版和服务器版的数据不自动同步，不直接复制 Windows DPAPI 加密配置到 Linux。

## 更新、备份与恢复

- 更新前正常备份，保留管理密码和备份口令。不要把新 ZIP 覆盖解压进正在运行的程序目录。
- 在原部署目录运行 `sudo bash update.sh /完整路径/新部署包.zip`。脚本先校验并构建，成功后生成加密备份并切换应用；持久化 data 和主密钥保留，桥接登录目录沿用。失败时按输出检查，不反复初始化或删除 runtime。
- `sudo bash backup.sh`：停止相关服务，生成包含主密钥与数据的加密备份，再恢复启动。备份口令遗失不能恢复；定期安全转存并管理磁盘，手工备份不会自动清理。
- `sudo bash restore.sh /完整路径/备份.sgbackup`：先验证备份并恢复到暂存目录，再切换；原运行目录保留。恢复后保持停服，核对程序和数据库版本再启动。不要用旧程序直接打开已升级数据库。
- `sudo bash doctor.sh`：检查状态，不调用模型、不输出密码。健康接口200不等于模型、QQ或外部 API真正可用。
- `sudo docker compose ps` 查看状态；`sudo docker compose stop` 正常停止；`sudo docker compose up -d` 恢复。不要公开未经检查的完整日志或配置。

## 部署后自检

确认面板可登录、静态资源可加载、未配置模型时能看到配置入口；按自己的服务验证一次 Web 回复。选用QQ时再验证连接、私聊、图片授权、表情和摘要任务，检查目标权限及投递去向。收费模型与QQ实际验证由使用者自行执行。

观察 `sudo docker stats --no-stream`、磁盘、掉线和重启情况。数据、主密钥、QQ登录状态与备份都是私人文件，不能上传 GitHub。仅有离线测试、容器健康或短时间内存观察不代表24小时稳定性验收。
