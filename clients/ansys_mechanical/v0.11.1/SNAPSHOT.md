# Ansys Mechanical 执行组件快照 v0.11.1

## 来源

- 用户提供文件：`Ansys力学助手_桌面版_v0.11.1(1).zip`
- 发布包 SHA-256：`5C5C2091316E79F8C2AF4B2F5C51E86FD6E41DE9E65678BE34DF01DCD9E7CCDE`
- 配套说明：用户提供的 `README.md`
- 导入日期：2026-10-30

## 已纳入

- Mechanical 固定脚本适配器与 JSON-lines 工具桥
- 载荷定义、工作流 Schema、工具 Schema
- 确定性验证规则与基准案例
- 90 条知识目录和 9 条 Ansys 252 规则映射
- 环境检查组件及配套文档

## 未纳入

- `Ansys力学助手_v0.11.1.exe`
- `_internal/` 中的 PyInstaller、Python、DLL 与第三方依赖
- `runtime_payload/` 中的嵌入式 Python 与离线 wheels
- 本机 API Token、模型密钥、用户偏好和运行输出

这些内容不适合进入 Git 历史。发布包应通过 GitHub Release 附件单独分发，并以本文件记录的 SHA-256 校验。

## 完整性边界

发布包没有包含配套 README 中列出的完整 UI 源码，例如：

- `desktop_app.py`
- `desktop_ui.py`
- `load_desktop.py`
- `environment_desktop.py`
- `desktop_features.py`
- `api_core.py`
- `api_server.py`
- `chat_setup.py`
- `visual_selection.py`
- `build_desktop.ps1`
- `build_runtime_payload.py`

因此当前目录是可审核的执行组件快照，不是可完整重建 EXE 的源码工程。

## 安全约束

- 用户输入以 JSON 数据传入固定 Mechanical 脚本，不允许模型生成任意执行代码。
- 求解必须在输出目录副本上进行，不能覆盖源 `.mechdat`。
- 任一阻断规则都必须使总体状态变为 `blocked`。
- 自动检查不能代替工程师复核和签字。
- 服务器密钥、桌面模型密钥和本机 API Token 不得提交到仓库。
