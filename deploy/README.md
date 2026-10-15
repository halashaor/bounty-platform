# mission 生产部署

生产使用 `wsgi:create_cloud_app()`、Gunicorn 和 HTTPS 反向代理。必须先安装公共 `team-accounts` 包，并挂载独立公共账号库；它和计算平台共用账号、邀请码与会话，不读取计算平台业务库、不调用计算平台 API。

公共包来自 [STARGATE 的 accounts 目录](https://github.com/Jarv1sP/stargate/tree/main/accounts)，两边使用同一版代码。先按该目录的迁移说明提取已有账号，再启动 mission。构建镜像只在开发机完成，发布镜像到 VPS；不在生产服务器构建。

## 离线构建输入

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
TEAM_ACCOUNTS_DATABASE=/accounts/accounts.sqlite
TEAM_IDENTITY_CONFIG=/identity/mission.json
```

Gunicorn：`gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 2 --preload --worker-tmp-dir /tmp 'wsgi:create_cloud_app()'`。仅给反向代理网络，不向宿主机发布 8080；根文件系统只读，单独挂载 `/data`、`/accounts` 和临时 `/tmp`。公共账号目录用专用共享组授予两个运行用户读写权限。每个容器最多 512 MiB；本应用可沿用 256 MiB/0.5 CPU。

mission 不设管理员。所有已登录成员都能整理标签；任务的发布、认领、提交、验收仍按各自的业务角色执行。统一账号的停用、密码恢复、邀请码及应用权限由独立门户管理；AMAX 管理员不会自动成为门户所有者。

启用 `TEAM_IDENTITY_CONFIG` 后，`TEAM_ACCOUNTS_DATABASE` 指向由独立身份服务发布的无密码视图，不能继续指向迁移前的密码库。视图每 15 秒刷新、60 秒后过期，缺失或过期时拒绝登录，不回退到本地密码。网页通过 OIDC/PKCE 登录，使用本域的 `__Host-mission_session`，忽略旧父域 cookie。客户端配置包含 `origin`、`issuer`、`clientId`、`clientSecret`、`portalOrigin`、`identityUrl`，只读挂载，不提交仓库。

`/healthz` 同时确认业务库和账号视图可读。正式库不导入演示账号或测试任务。业务数据继续独立备份；公共账号库与配套 `.key` 另行一致性备份。独立身份迁移前保存一致性备份，在同一维护窗口将两个应用切换到无密码视图；保持原用户 ID 和任务归属。切换后原密码库只作受限备份，不能再让旧进程写入。

共享账号卷由发布者先建立并初始化；`deploy/compose.yml` 另需设置 `TEAM_ACCOUNTS_DIR`（宿主机目录）、`TEAM_ACCOUNTS_GID`（专用共享组）和 `BOUNTY_PROXY_NETWORK`。日常业务备份仍沿用 `deploy/backup.py` 与 systemd 定时器；公共账号库按公共包说明独立备份。

若不设置 `TEAM_IDENTITY_CONFIG`，云端会查找现有账号目录旁的 `mission-identity.json`；其中 `projectionDatabase` 指定独立无密码视图路径。这样可先准备私有配置，再从合并后的 main 启用，避免手工修改运行中容器。配置存在但无效时启动失败。
