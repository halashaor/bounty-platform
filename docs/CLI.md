# Mission 命令行与 AI

`mission` 使用站点的 `/api/v1` JSON 接口，复用网页的任务服务和业务角色。CLI 不直接访问 SQLite，不需要 GPU 平台凭据，也不能绕过验收权限。需要同时部署包含这些接口的服务端；旧版本服务端不能仅靠安装 CLI 获得新接口。

## 安装

需要 Python 3.10 或更新版本。CLI 本身只使用标准库，不安装 Flask 或服务器依赖。

```bash
pipx install git+https://github.com/halashaor/bounty-platform.git
mission --version
```

也可在克隆的仓库里用虚拟环境执行 `python -m pip install .`，或直接运行 `python mission_cli.py`。Windows 使用对应虚拟环境的 `Scripts\python.exe`；下列命令除 shell 的多行语法外相同。

## 登录与撤销

```bash
mission --server https://mission.example.test login
mission me
mission logout
```

`login` 打开站点 `/cli`。先通过正常网页登录，再点击「生成一份命令行访问凭据」，将其粘贴到终端的隐藏输入提示处。首次登录完成后如网页跳回首页，回到原授权页刷新即可。`--no-browser` 可以只显示地址。

这是独立的命令行会话，`logout` 撤销它，不退出浏览器。生产会话沿用独立身份服务的有效期、应用授权、停用和密码变更规则；身份视图不可用时不会回退到本地密码。旧共享 cookie 接入模式不新增 CLI 登录能力，需先按现有流程配置独立 OIDC。本地演示账号也可在网页生成凭据，有效期 7 天，可单独撤销。

不要把访问凭据写进命令参数、截图、PR 或对话。非交互环境可从受保护的标准输入传入：

```bash
mission --server https://mission.example.test login --token-stdin < /private/mission-token.txt
```

本地默认配置为 `~/.config/mission/config.json`，按站点分别保存凭据；Linux/macOS 文件权限为 0600。Windows 请放在只有本人可访问的用户目录。可用 `--config` 或 `MISSION_CONFIG` 指定其他文件。无状态脚本也可通过秘密注入设置 `MISSION_SERVER`、`MISSION_TOKEN`，不必执行 `login`；不要在共享 shell 历史中粘贴令牌。

CLI 只向指定站点发送凭据，不跟随 HTTP 重定向；远程地址必须是 HTTPS。本机开发可使用 `http://127.0.0.1:5080`。服务器地址优先级：`--server`、`MISSION_SERVER`、配置文件。

## 查询和处理任务

```bash
mission members
mission tags
mission mine
mission task list --status open --tag 代码 --limit 20
mission task list --kind team
mission task show 12
mission task events 12 --limit 50
mission task claim 12
mission task submit 12 --body-file deliverable.md
mission task return 12 --body '补充边界样例'
mission task accept 12 --body '结果完整'
mission task comment 12 --body-file -
```

`members` 返回已进入 Mission 的成员及本地业务编号，不读取身份目录里的所有账号。使用返回的编号指定成员，不猜测用户名对应的 ID。列表通过 `limit`/`offset` 分页，JSON 中 `next_offset` 为下一页起点；历史通过 `after` 分页，`next_after` 为空表示结束。任务详情只附最近 50 条历史，完整历史用 `task events` 获取。

状态为 `open`、`active`、`review`、`done`。任务类型为 `solo` 或 `team`。查询还支持 `--q`、`--project`、`--owner-id`、`--assignee-id`、`--parent-id`。

## 发布和多人协作

```bash
mission task create --title '准备组会例题' --description '整理三道图论题' \
  --requirements '文档链接与题解' --tag 讲解 --deadline '2027-01-20T18:00:00+08:00'
mission task create --input task.json --assignee 2
mission task create --input task.json --kind team --member 2 --member 3 --team-size 4 --join-self
mission task join 15
mission task leave 15
mission task split 15 --title '准备例题' --tag 讲解 --kind standard-normal --body '三道图论题'
mission task accept 15 --credit 2 --credit 3
mission task clap 15
```

`task.json` 示例：

```json
{
  "title": "准备组会例题",
  "description": "整理三道图论题",
  "requirements": "文档链接与题解",
  "tags": ["讲解", "代码"],
  "deadline": "2027-01-20T18:00:00+08:00",
  "importance": "standard",
  "urgency": "normal"
}
```

默认发布小任务，分量 `standard`、紧急程度 `normal`；分量还可选 `light`、`major`，紧急程度还可选 `urgent`。`--input -` 从标准输入读取 JSON，显式命令参数覆盖文件中同名字段。截止时间必须包含时区，避免 AI 将本地时间当成服务器时间；支持 `Z`。示例日期按实际任务调整。

发布者不能指定自己；大任务想参与用 `--join-self`。大任务 `accept` 未传 `--credit` 时沿用网页默认发奖规则。分工的 `--kind` 为勋章类型，例如 `light-normal`、`major-urgent`；不是任务类型。没有增加任务删除、任意转派或管理员操作。

## 延期

```bash
mission task extend ask 12 --deadline '2027-01-22T18:00:00+08:00' --body '需要补充对照实验'
mission task extend approve 12 --body '可以'
mission task extend reject 12 --body '先交当前结果'
mission task extend push 12 --deadline '2027-01-23T18:00:00+08:00'
```

申请、审批、直接延期的角色与状态限制均和网页相同；不能审批自己的申请，也不会因为延期重发奖励。

## AI 和脚本约定

```bash
mission schema --json
mission mine --json
mission task show 12 --json
mission task create --input - --json < task.json
```

`--json` 可放在命令前后。成功输出 `{"ok":true,"data":...}`；失败输出 `{"ok":false,"error":{"code":"...","message":"..."}}`。stdout 只输出一个 JSON 对象；交互提示在 stderr。`--help`、`--version` 是文本帮助，不属于 JSON 数据命令。`schema` 可离线运行，包含命令参数、默认值和退出码。

| 退出码 | 含义 | 处理方式 |
| --- | --- | --- |
| 0 | 成功 | 使用返回的实际任务 ID 和状态 |
| 2 | 参数、输入文件或配置错误 | 修正输入 |
| 3 | 未登录、凭据失效或无应用权限 | 由用户登录或处理授权，不切换成他人账号 |
| 4 | 服务端拒绝操作 | 阅读原因，修正参数或业务状态 |
| 5 | 网络/服务不可用，或写入结果未知 | 写请求先查询任务及历史，不能直接重发 |

只读请求对临时网络故障最多补试一次。写请求不自动重试；超时、连接中断或服务端错误可能发生在提交之后，返回 `outcome_unknown`。按已有 ID 查详情/历史；发布结果未知时按标题、发布者等查询列表。没有为每条命令增加回执或证明系统，客户端必须避免重复发布、评论或提交。

随附 [Mission AI 技能](../skills/mission/SKILL.md)。把 `skills/mission` 文件夹安装到你使用的代理的技能目录即可；不要求安装额外 MCP 服务。本项目没有实现 MCP 协议端点。

## JSON HTTP 接口

接口前缀 `/api/v1`，所有接口需要 `Authorization: Bearer <命令行凭据>`。仅有网页 cookie 不足以调用 API；API 不使用网页 CSRF，网页表单仍保留 CSRF。请求体为 JSON 对象，无关额外字段忽略；仍受站点请求体及文本长度限制。

| 方法和路径 | 用途 |
| --- | --- |
| `GET /me`、`/mine`、`/members`、`/tags` | 身份、待办、成员、标签 |
| `GET /tasks` | 分页查询，参数见 CLI list |
| `GET /tasks/{id}`、`/tasks/{id}/events` | 详情和交付历史 |
| `POST /tasks` | 发布；字段见上面的 JSON，支持 assignee、members、team_size、join_self |
| `POST /tasks/{id}/actions` | `action` 为 claim/join/leave/submit/accept/return/comment，正文为 body，发奖名单为 credit |
| `POST /tasks/{id}/extensions/{move}` | move 为 ask/approve/reject/push，字段 deadline、body |
| `POST /tasks/{id}/pieces` | 拆分工：title、note、tag、kind，可选 deadline |
| `POST /tasks/{id}/clap` | 鼓掌 |
| `POST /logout` | 撤销当前命令行会话 |

这些接口调用现有业务服务，不改变任务角色、归属或发奖条件。身份相关失败通常为 401/403，业务拒绝为 400，未找到为 404，请求过大为 413，暂时不可用为 503；错误正文统一使用上面的 JSON 结构。
