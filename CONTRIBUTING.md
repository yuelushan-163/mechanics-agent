# 贡献与版本管理

## 分支

- `main`：可部署、可回滚的稳定版本。
- 功能分支：`feature/<主题>`。
- 修复分支：`fix/<主题>`。
- 发布分支：`release/<版本>`。

所有功能和修复通过 Pull Request 合入 `main`，不要直接覆盖生产分支。

## 提交前检查

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
python -m unittest discover -s tests -v
python -m compileall -q clients/ansys_mechanical/v0.11.1
```

工程规则、材料数据和知识条目必须注明来源、版本、适用范围与审核状态。模型生成内容不能直接变成可执行规则。

## 禁止提交

- `.env.server`、`deploy/secrets/` 和任何 API Key；
- 本机 API Token、浏览器凭据和 SSH 私钥；
- Ansys EXE、DLL、嵌入式 Python、离线 wheels；
- 用户 `.mechdat`、CAD、ODB、求解输出和未经授权的工程数据；
- 日志中的 Authorization、密码、Token 和个人信息。

桌面发布包通过 GitHub Release 附件分发，并在 Release 说明中记录 SHA-256。

## 审核边界

- UI、文档和非执行性知识可进行普通代码审核。
- 载荷、约束、材料、网格、求解器脚本和验算规则需要工程审核。
- 删除历史数据、变更生产凭据、迁移数据库或修改公网入口必须附回滚步骤。
