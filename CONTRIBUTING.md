# 参与开发

开发、权限、测试和发布规则统一见 [AGENTS.md](AGENTS.md)，当前功能边界见 [docs/FEATURES.md](docs/FEATURES.md)。

1. 从最新 `main` 建独立分支，只改本次范围。
2. 使用 Python 3.12 虚拟环境，安装 `requirements-cloud.txt`，认证测试需要其中的公共账号包。日常开发使用临时数据库，不接生产账号或业务库。
3. 修改代码时同步对应文档。新增或删除功能、调整权限和发布流程，在 PR 中明示，按维护者授权执行。
4. 本地跑受影响测试和 `git diff --check`；CI 会执行完整测试和镜像构建。纯文档改动检查事实和链接即可。
5. PR 写清具体行为、测试结果、未测范围以及必要的迁移/回退步骤。失败测试先修复，不能靠放宽断言过关。

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-cloud.txt
# 示例：此次改动涉及延期和指派
.venv/bin/python -m unittest discover -s tests -p test_extend_assign.py -v
git diff --check
```

需要完整后端验证时运行 `python -m unittest discover -s tests -v`。UI 变更可运行 `python scripts/check_motion.py`，额外需要 `websocket-client` 和 Chromium；当前脚本覆盖桌面和 390 宽度，受影响页面的 320 宽度及脚本未覆盖的新交互需要补充检查。所有浏览器测试使用临时账号和数据。

发布说明见 [deploy/README.md](deploy/README.md)。当前 CI 导出镜像制品但尚未自动部署，不能把合并完成写成已上线。不要为提交文档或普通功能修改流水线、生产服务器或身份平台。
