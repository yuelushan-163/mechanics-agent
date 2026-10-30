# Ansys 力学助手 · Windows 桌面版

## 现在怎么用

双击 `outputs/Ansys力学助手/Ansys力学助手.exe`，使用 Windows 桌面窗口操作；不依赖 Codex Harness 或浏览器。

1. 在“模型 API”区域填写供应商 API 根地址、模型名称和密钥，点击“应用配置”。
2. 点击“测试 API”，确认模型和工具调用协议可用。
3. 在“静力分析流程”区域选择已有 `.mechdat`，读取几何面，指定固定面、受力面、全局力分量和网格尺寸。
4. 人工核对材料、面 ID、力方向与单位后勾选确认，再点击“生成网格并求解”。结果副本、JSON 报告和云图保存在指定新目录。

右侧“助手对话”可使用大模型自然语言交互；左侧也可单独检查 Mechanical 连接状态。

模型 API 地址和模型名保存在当前 Windows 用户配置目录，密钥只保存在程序内存，关闭程序后需重新填写。桌面程序通过本机 Python/PyMechanical 工具环境启动 Mechanical。

桌面发行包：`outputs/Ansys力学助手_桌面版_v0.4.zip`。要求本机安装 Ansys Mechanical 2025 R2，并将程序放在能找到 `work/ansys-venv` 的工作区中；跨电脑使用需准备 Python 3.12 环境并安装 `requirements.txt`。

首版输入为已有独立 `.mechdat` 模型，要求几何和材料已经准备好。不支持任意 CAD 格式直接导入、接触、塑性、大变形或多载荷步；材料参数、边界面和网格收敛仍由工程人员确认。

当前使用 Chat Completions 工具协议；支持程度取决于供应商与具体模型。
API 根地址填写供应商文档中的根地址，例如带 `/v1` 的地址；程序会追加 `/chat/completions`。
也可以输入完整的 `/chat/completions` 地址，程序会规范化。
尚未实现 Responses 或 Anthropic Messages 的原生协议。

密钥只存在当前服务内存中，不写入项目文件、配置响应或访问日志。服务重启后需要重新填写。
也可在启动前设置 ANSYS_AGENT_BASE_URL、ANSYS_AGENT_MODEL、ANSYS_AGENT_API_KEY 环境变量。
切换根地址而没有填写新密钥时，程序清空旧密钥，避免发到新供应商。

## 开发版本机网页 API（可选）

PowerShell 中运行：

```powershell
.\start_api.ps1
```

网页 API 仅供开发和其他本地程序集成；桌面版不依赖该服务。

启动信息在工作目录的 `work/ansys-api-state-v2/` 中，包含：

- `browser-url.txt`：首次进入页面的本机链接。
- `api-token.txt`：HTTP API 访问令牌，和模型供应商密钥是两个不同的东西。

当前工作目录：`C:\Users\ohppv\Documents\Codex\2026-10-23\new-chat`。
打包交付不包含这些运行时文件或密钥。

## HTTP 接口

除首页、健康检查和接口结构文档外，接口需携带 `Authorization: Bearer <本机访问令牌>`。
本机页面首次验证后使用同站 HttpOnly Cookie 保持访问。

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | /health | 服务存活检查，不启动 Ansys |
| POST | /api/session | 为本机页面建立浏览器会话 |
| GET | /api/config | 返回模型地址、模型名和密钥是否配置，不返回密钥 |
| PUT | /api/config | 更新当前进程中的模型配置 |
| POST | /api/config/clear | 清除模型配置 |
| POST | /api/llm/test | 测试模型工具调用与工具结果回传（修复版使用 auto / none） |
| POST | /api/ansys/test | 启动独立 Mechanical 并读取真实状态 |
| GET | /api/tools | 查询工具定义 |
| POST | /api/tools/call | 按工具名与参数执行工具 |
| POST | /api/chat | 执行一次带工具循环的对话 |
| DELETE | /api/chat/{session_id} | 删除空闲的内存对话 |
| GET | /openapi.json | OpenAPI 接口定义 |
| GET | /docs | 交互式接口文档 |

配置请求结构：

```json
{
  "base_url": "https://供应商地址/v1",
  "model": "供应商提供的完整模型名称",
  "api_key": "在本机填写真实密钥",
  "timeout": 120
}
```

聊天请求结构：

```json
{"message": "连接本机 Ansys，读取状态。", "session_id": null}
```

响应包含 reply、session_id 和 trace。后续对话带回 session_id；对话只保存在服务内存中。
工具结果会作为 tool 消息回传模型，因此通过模型读取工程时，工程摘要将发往用户配置的模型服务。
对话循环最多 6 轮、单次请求最多实际执行 16 个工具调用；Ansys 操作串行执行。
达到循环上限后关闭工具，让模型总结当前状态；不会无限执行或自动重试。
超时或上游失败时会返回错误及已完成的工具记录，不应把错误当作“软件未发生任何操作”。

独立调用 Ansys 工具：

```json
{"name": "mechanical_status", "arguments": {}}
```

```json
{"name": "inspect_project", "arguments": {"project": "D:/models/cantilever.mechdat"}}
```

其他工具：validate_static_plan、review_static_model、run_static_cases。`review_static_model` 只读检查模板；若返回 `blocked`，禁止继续求解；若返回 `human_review_required`，请按返回的人工检查项核对模型。运行报告中的支反力平衡自动检查通过，也不代表工程验收通过。静力模板要求见 README.md。
没有开放任意 Python、系统命令或任意文件读取工具。

## 已验证与未验证

18 项自动测试通过。另用本机模型协议测试端，实测了“HTTP API → 工具调用 → 真实 Mechanical 2025 R2 → 工具结果回传”。
协议测试端不是实际大模型；真实供应商的联网验证需要用户填写 API 配置。
实际工程的静力求解和工程正确性验收仍需要经过人工验证的 `.mechdat` 基准模型。

参考协议：https://developers.openai.com/api/docs/guides/function-calling

## DeepSeek 兼容修复

`https://api.deepseek.com/v1` 和 `deepseek-flash` 均可使用。
DeepSeek 默认开启思考模式，不支持强制指定某个工具；原版 `/api/llm/test` 因此返回 HTTP 400。
源代码已修正为自动选择工具，并保留 reasoning_content 以完成上下文回传。
当前运行进程中的旧后端测试路由要在下次启动服务后更新；页面按钮已改用兼容的对话接口，刷新页面即时生效，不丢失内存密钥。
已用真实 DeepSeek API 验证普通对话和 mechanical_status 工具调用，成功连接本机 Mechanical 252；未打开工程或求解。

官方规则：https://api-docs.deepseek.com/api/create-chat-completion/
