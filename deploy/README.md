# mission 生产部署

生产使用 `wsgi:create_cloud_app()`、Gunicorn 和 HTTPS 反向代理。正式站通过独立身份服务 OIDC/PKCE 登录，读取无密码身份视图，并保存 Mission 自己的本域会话；不与计算平台共享父域 cookie，不读取其业务库、不调用其业务 API。身份接入复用固定版本的 `team-accounts` 包。

公共包来自 [STARGATE 的 accounts 目录](https://github.com/Jarv1sP/stargate/tree/main/accounts)，实际构建版本以 `requirements-cloud.txt` 固定提交为准。身份服务及视图由其维护者配置；日常业务发布保留已有身份配置，不重复提取或迁移账号。

## 发布规则与当前进度

遵守 [开发守则](../AGENTS.md)。生产镜像只使用成功 CI 的 main 提交制品，不在 VPS 构建、临时叠加镜像或修改运行中的源码。

现有 [CI 工作流](../.github/workflows/ci.yml) 在 PR 和 main 上执行完整后端测试、差异检查和镜像构建；main 另导出 `mission-<完整提交号>` 制品，包含镜像、提交号及部署文件，保留 14 天。**目前没有自动部署步骤，也没有自动浏览器检查。** 合并成功不代表生产已更新。

目标是测试通过后合并 main 自动上线，失败保留上一版。接通部署通路、服务器凭据和工作流需要所有者或指定总控确认后单独实施。当前已获授权的发布，由维护者通过现有运维入口取对应 CI 制品、备份业务数据、维护窗口停旧起新、检查健康和登录后恢复流量。不要为普通功能或文档提交顺手修改 `.github/workflows`。

上线前准备相应回退版本。恢复访问之前失败可以恢复旧服务及对应业务备份；开放访问之后不能直接覆盖新写入的数据。发布只操作 Mission，不重启或部署身份服务、GPU 平台与节点。真实服务器地址、凭据和现场发布记录放在私有运维资料中。

## CI 离线构建输入

`requirements-cloud.txt` 将公共包固定到审查过的源码提交。准备普通依赖的 Linux wheel，并从该同一提交构建公共包（纯 Python）：

```sh
python -m pip download --only-binary=:all: --platform manylinux2014_x86_64 \
  --python-version 312 --implementation cp --abi cp312 -r requirements.txt gunicorn==26.2.0 -d wheels
python -m pip wheel --no-deps --wheel-dir wheels \
  'git+https://github.com/Jarv1sP/stargate.git@0e883682b4476c27c131f06484b8d08a7fa1e9f3#subdirectory=accounts'
docker build --network=none -t bounty-platform:VERSION .
```

构建时只从 `wheels/` 装包，避免容器联网取源码。开发及认证测试使用 `pip install -r requirements-cloud.txt`；基础本地演示可继续仅安装 `requirements.txt`。

## 运行配置

必需环境：

```text
BOUNTY_DOMAIN=mission.example.test
BOUNTY_DATA_DIR=/data
TEAM_ACCOUNTS_DATABASE=/accounts/identity.sqlite
TEAM_IDENTITY_CONFIG=/identity/mission.json
```

Gunicorn：`gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 2 --preload --worker-tmp-dir /tmp 'wsgi:create_cloud_app()'`。仅给反向代理网络，不向宿主机发布 8080；根文件系统只读，单独挂载 `/data`、`/accounts` 和临时 `/tmp`。身份视图及会话目录只授予现有接入所需的权限，OIDC 客户端配置只读；不要挂载迁移前的密码库。每个容器最多 512 MiB；本应用可沿用 256 MiB/0.5 CPU。

mission 不设管理员。所有已登录成员都能整理标签；任务的发布、认领、提交、验收仍按各自的业务角色执行。统一账号的停用、密码恢复、邀请码及应用权限由独立门户管理；AMAX 管理员不会自动成为门户所有者。

启用 `TEAM_IDENTITY_CONFIG` 后，`TEAM_ACCOUNTS_DATABASE` 指向由独立身份服务发布的无密码视图，不能继续指向迁移前的密码库。视图每 15 秒刷新、60 秒后过期，缺失或过期时拒绝登录，不回退到本地密码。网页通过 OIDC/PKCE 登录，使用本域的 `__Host-mission_session`，忽略旧父域 cookie。客户端配置包含 `origin`、`issuer`、`clientId`、`clientSecret`、`portalOrigin`、`identityUrl`，只读挂载，不提交仓库。

`/healthz` 同时确认业务库和账号视图可读。正式库不导入演示账号或测试任务。业务数据继续独立备份；公共账号库与配套 `.key` 另行一致性备份。独立身份迁移前保存一致性备份，在同一维护窗口将两个应用切换到无密码视图；保持原用户 ID 和任务归属。切换后原密码库只作受限备份，不能再让旧进程写入。

身份视图及会话目录由身份服务维护者先建立；`deploy/compose.yml` 另需设置 `TEAM_ACCOUNTS_DIR`（宿主机目录）、`TEAM_ACCOUNTS_GID`（专用共享组）和 `BOUNTY_PROXY_NETWORK`。日常业务备份仍沿用 `deploy/backup.py` 与 systemd 定时器；身份服务的数据和会话按其维护流程独立备份。

若不设置 `TEAM_IDENTITY_CONFIG`，云端会查找现有账号目录旁的 `mission-identity.json`；其中 `projectionDatabase` 指定独立无密码视图路径。这样可先准备私有配置，再从合并后的 main 启用，避免手工修改运行中容器。配置存在但无效时启动失败。
