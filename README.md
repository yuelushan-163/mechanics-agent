# Mechanics Agent

这是一个面向工程仿真的可信 Agent 系统。服务器端负责知识检索、模型规划、任务状态、审批、日志与成本审计；Windows 执行端负责连接本机 CAE 软件并执行受控工作流。

- 提供面向工程用户的结构化工作台，不需要直接编辑 JSON；
- 提供独立的开发管理台，可操作案例规划、结果验算、知识检索和知识导入；
- 开发管理台集中展示浏览器错误、请求响应、服务端异常堆栈和请求ID；
- 后端统一监测API、Elasticsearch、规划模型、Embedding和用量账本；
- Elasticsearch 存储力学知识、材料、错误案例和可执行验算规则；
- MongoDB 持久化用户、项目、任务状态历史、审批记录和脱敏错误日志；
- 支持全文检索、结构化过滤和 `dense_vector` 混合检索；
- SiliconFlow、Kimi等OpenAI兼容模型根据案例与已审核知识生成结构化CAD/CAE计划；
- 确定性规则引擎执行前处理和后处理验算；
- 每次规划与验算写入独立审计索引；
- 记录每次聊天与Embedding调用的Token、缓存命中、耗时和人民币成本；
- 未配置在线模型时自动切换到本地确定性规划器，便于离线开发。

示例知识只用于演示数据结构，不能直接作为工程结论。

## 架构边界

```text
用户任务
  → ES 检索已审核知识与规则
  → 规划模型生成分析计划（不负责判定合格）
  → 前处理规则检查
  → 本机执行端（当前纳入 Ansys Mechanical 2025 R2 v0.11.1 组件快照）
  → 求解器结果与日志提取结构化证据
  → 后处理规则引擎判定
  → ES 保存审计记录
```

## Ansys Mechanical Windows 执行端

`clients/ansys_mechanical/v0.11.1/` 保存从用户提供的 v0.11.1 发布包中提取并审查的可维护组件：

- 七类载荷的单一数据源与 JSON Schema；
- Mechanical 2025 R2 固定脚本适配器；
- 线性静力求解前后确定性检查；
- 90 条本地工程知识、9 条规则映射与 7 个白名单工具；
- JSON-lines 工具桥、基准案例和使用文档。

该目录不包含 EXE、DLL、内置 Python 和离线 wheels。二进制发布包应作为 GitHub Release 附件管理，不能进入 Git 历史。用户提供的发布 ZIP SHA-256 为
`5C5C2091316E79F8C2AF4B2F5C51E86FD6E41DE9E65678BE34DF01DCD9E7CCDE`。

需要注意：发布 ZIP 不是完整的桌面源码工程，缺少 `desktop_app.py`、`desktop_ui.py`、`api_server.py` 等文件。当前纳入的是可审计执行组件快照，不能仅凭该目录重新构建桌面 EXE。完整边界见 [快照说明](clients/ansys_mechanical/v0.11.1/SNAPSHOT.md)。

数据库规则不会作为 Python 代码执行。当前只允许以下白名单计算器：

- `required_field`
- `vector_balance`
- `relative_change`
- `upper_bound`
- `ratio_min`
- `equals`
- `empty_collection`
- `finite_number`

## 目录

```text
src/mechanics_agent/
  api.py                    FastAPI 接口
  debug_logs.py             服务端内存日志、堆栈和敏感字段脱敏
  frontend/                 无构建依赖的用户工作台与开发管理台
  planner.py                SiliconFlow、Kimi与本地规划器
  service.py                用例编排
  embeddings.py             可选的兼容 OpenAI 协议的向量接口
  knowledge/elasticsearch.py ES 存储与混合检索
  rules/engine.py           确定性验算引擎
data/seed_knowledge.jsonl    演示知识与规则
examples/                    示例案例和后处理证据
scripts/ingest_seed.py       ES 初始化数据导入
tests/                       离线测试
clients/ansys_mechanical/    Ansys Mechanical Windows 执行端组件快照
```

## 运行

### 1. 安装

```powershell
python -m pip install -e .
```

### 2. 配置

复制 `.env.example` 中需要的变量到系统环境。最少需要一个可访问的 Elasticsearch：

```powershell
$env:ES_URL = "http://127.0.0.1:9200"
$env:ES_INDEX_PREFIX = "mechanics-agent"
```

首次使用SiliconFlow的DeepSeek V4 Flash测试：

```powershell
$env:PLANNER_MODE = "siliconflow"
$env:SILICONFLOW_API_KEY = "你的服务端密钥"
$env:SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
$env:SILICONFLOW_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
```

首测默认不发送 `enable_thinking`。如果SiliconFlow模型页面确认当前版本支持该参数，可显式设置：

```powershell
$env:SILICONFLOW_ENABLE_THINKING = "true"
```

切换到Kimi：

```powershell
$env:PLANNER_MODE = "kimi"
$env:MOONSHOT_API_KEY = "你的服务端密钥"
$env:KIMI_MODEL = "kimi-k2.6"
```

`PLANNER_MODE=auto` 会依次选择已配置的Kimi、SiliconFlow或本地规划器。密钥只通过环境变量配置，不要写进源码、前端或提交到版本库。修改环境变量后需要重启服务。

服务器部署后可用隐藏输入方式一次配置 SiliconFlow 规划模型与 Embedding：

```powershell
ssh -t -i "$env:USERPROFILE\.ssh\aliyun_mechanics" root@8.145.63.176 "cd /opt/mechanics-agent && ./deploy/configure-models.sh"
```

脚本把同一个 Key 分别保存为规划模型与 Embedding 的只读 Docker Secret，启用
`deepseek-ai/DeepSeek-V4-Flash` 和 `Qwen/Qwen3-Embedding-0.6B`，重启 API 后主动检测两个接口。
Key 不会写入 `.env.server`、镜像、前端或命令历史。

服务启动后，可在前端“运行概览”点击“主动探测模型”。请求由后端统一执行，会分别验证规划模型和Embedding模型，并记录实际Token与费用。

### 3. 导入演示知识

```powershell
python scripts/ingest_seed.py
```

会创建：

- `mechanics-agent-knowledge-v1`
- `mechanics-agent-runs-v1`
- `mechanics-agent-model-usage-v1`

### 4. 启动

```powershell
python -m mechanics_agent.main
```

用户工作台概览：`http://127.0.0.1:8000/`

验收案例库：`http://127.0.0.1:8000/cases`

新建分析：`http://127.0.0.1:8000/analysis/new`

最近分析结果：`http://127.0.0.1:8000/analysis/result`

开发管理台：`http://127.0.0.1:8000/admin/`

接口文档：`http://127.0.0.1:8000/docs`

用户工作台按“概览、案例选择、分步输入、结果审核”拆分为独立页面，不要求直接编辑 JSON。草稿和最近一次分析结果保存在当前浏览器。开发管理台保留模型探测、知识检索与导入、确定性验算、Token 费用和实时日志。即使 Elasticsearch 初始化失败，用户页面与管理台仍然可以打开，启动与监控异常会显示在开发管理台的“实时日志”中。

### 5. 提交示例规划

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/v1/cases/plan" `
  -ContentType "application/json" `
  -InFile "examples/plan_request.json"
```

## API

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 返回后端缓存的统一监控快照，不触发付费模型调用 |
| `GET` | `/health/live` | 只检查FastAPI进程是否存活 |
| `GET` | `/v1/monitoring/status` | 获取监控快照；`refresh=true`立即执行一次免费依赖检查 |
| `POST` | `/v1/monitoring/probe` | 由后端主动探测规划和Embedding模型，会产生Token费用 |
| `GET` | `/v1/operations/health` | 检查MongoDB业务存储 |
| `POST/GET` | `/v1/users` | 创建或列出工程用户（不存密码） |
| `POST/GET` | `/v1/projects` | 创建或列出项目 |
| `POST/GET` | `/v1/tasks` | 创建或列出任务 |
| `PATCH` | `/v1/tasks/{task_id}/status` | 更新任务状态并追加不可丢失的状态历史 |
| `POST/GET` | `/v1/approvals` | 发起或列出审批 |
| `PATCH` | `/v1/approvals/{approval_id}/decision` | 批准或拒绝；决定作出后禁止覆盖 |
| `GET` | `/v1/operations/error-logs` | 查询MongoDB中的持久化错误日志 |
| `POST` | `/v1/operations/error-logs/client` | 保存经过服务端脱敏的前端错误 |
| `POST` | `/v1/knowledge/documents` | 批量写入力学知识或规则 |
| `POST` | `/v1/knowledge/search` | 全文/向量混合检索 |
| `POST` | `/v1/cases/plan` | 检索知识、前检并生成分析计划 |
| `POST` | `/v1/cases/verify` | 对结构化证据执行确定性验算 |
| `GET` | `/v1/cases/templates` | 读取待确认的版本化工程验收案例；不会调用模型或求解器 |
| `GET` | `/v1/cases/templates/{template_id}` | 读取单个验收案例、理论基准、异常场景和修订说明 |
| `GET` | `/v1/debug/logs` | 增量读取服务端调试日志 |
| `DELETE` | `/v1/debug/logs` | 清空服务端调试日志 |
| `POST` | `/v1/debug/planner/test` | 兼容旧调试流程，仅测试规划模型；新前端使用统一主动探测 |
| `GET` | `/v1/usage/events` | 按模型、操作和时间读取逐次用量 |
| `GET` | `/v1/usage/summary` | 按模型汇总Token、失败次数和费用 |
| `GET` | `/v1/usage/pricing` | 查看当前生效的模型价格配置 |

## 前端与日志

用户工作台负责多页面案例选择、五步结构化输入和按分类展示分析计划。用户页面不提供开发管理台入口。开发管理台包含五个工作区：

- 运行概览：只读取后端统一监控快照，显示API、ES、规划模型、Embedding和费用账本；
- 案例规划：编辑JSON并调用完整规划链路；
- 结果验算：分别编辑案例和ODB/日志证据；
- 知识检索：检查ES检索结果、得分和原始响应；
- 知识导入：批量写入知识或验算规则。

右侧日志区会合并：

- 前端请求开始、完成、网络失败和JSON解析错误；
- 服务端校验错误、ES/规划模型/向量服务错误及未处理异常；
- HTTP状态、耗时、请求ID、响应内容和Python异常堆栈。

实时日志在当前进程内存中最多保留500条；其中 `ERROR` 和 `WARNING` 会在服务端脱敏后写入 MongoDB，前端启动时会读取最近200条持久化错误。常见密钥、Authorization、密码和Token会被脱敏。当前业务接口依赖Nginx Basic Auth和SSH隧道保护，不能把API 8000端口直接暴露到公网。

## MongoDB业务数据

MongoDB使用五个业务集合：

| 集合 | 内容 |
|---|---|
| `users` | 用户名称、邮箱、角色和状态；不保存登录密码 |
| `projects` | 项目负责人、状态、说明和扩展元数据 |
| `tasks` | 规划、SolidWorks、Abaqus、验算和动画任务及完整状态历史 |
| `approvals` | 载荷、约束、材料、接触等人工审批；决定作出后不可覆盖 |
| `error_logs` | 已脱敏的前端和服务端错误、请求ID与异常堆栈 |

ES与MongoDB职责保持分离：ES负责语义检索、知识、规则、模型用量和仿真审计；MongoDB负责任务工作流与操作性数据。大体积的SLDPRT、CAE、ODB和MP4不存入MongoDB，后续应保存到对象存储，只在任务中记录文件ID、校验值和版本。

## 后端统一监控

监控逻辑全部由 `BackendMonitor` 在服务端执行。默认每30秒进行一次被动检查：

- FastAPI进程状态；
- Elasticsearch连接和版本；
- Token与费用索引是否可查询；
- 规划模型和Embedding模型是否已配置；
- 两个模型最近一次真实调用的状态、耗时、Token和费用。

被动检查不会调用任何付费模型。前端每5秒只读取 `/health` 的缓存快照，不再自行组合ES、模型和Embedding探测请求。

需要真实验证模型连接时，使用后端主动探测：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/v1/monitoring/probe" `
  -ContentType "application/json" `
  -Body '{"targets":["planner","embedding"]}'
```

主动探测会真实调用供应商API，因此产生的Token和费用同样写入用量账本。ES不可用、监控超时和用量写入失败会进入后端调试日志；相同故障在状态不变时只记录一次，避免周期监控刷屏。

## 向量检索

规划模型与向量模型分开配置。系统接受任意兼容OpenAI `/embeddings` 协议的向量服务：

```powershell
$env:EMBEDDING_BASE_URL = "https://你的向量服务/v1"
$env:EMBEDDING_API_KEY = "服务端密钥"
$env:EMBEDDING_PROVIDER = "siliconflow"
$env:EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
$env:EMBEDDING_DIMS = "1024"
$env:ES_VECTOR_DIMS = "1024"
$env:EMBEDDING_SEND_DIMENSIONS = "true"
```

导入和查询必须使用相同向量模型、版本、切分方法和维度。未配置向量服务时，系统自动使用 ES 全文检索；也可以在 API 请求中直接提供 `embedding` 或 `query_vector`。

## Token与成本监测

系统只使用模型供应商响应中的 `usage` 字段记账，不通过字符串长度猜测Token。聊天模型分别记录普通输入、缓存命中输入和输出；Embedding记录输入Token。每条事件保存调用时的价格快照，因此以后修改价格配置不会改变历史账单。

当前默认价格来自用户提供的硅基流动截图，单位为人民币/千Token：

| 模型 | 普通输入 | 缓存输入 | 输出 |
|---|---:|---:|---:|
| `deepseek-ai/DeepSeek-V4-Flash` | ¥0.001000 | ¥0.000020 | ¥0.002000 |
| `Qwen/Qwen3-Embedding-0.6B` | ¥0.000070 | ¥0 | ¥0 |

价格环境变量位于 `.env.example`。价格只与完全一致的模型ID匹配；如果调用了没有配置价格的模型，系统仍保存Token，但把 `pricing_found` 标记为 `false`，不会用其他模型价格代算。供应商没有返回 `usage` 时，会保存调用事件并把 `usage_reported` 标记为 `false`，不会伪造Token或费用。

查看总用量：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/v1/usage/summary"
```

按模型和时间过滤：

```powershell
Invoke-RestMethod (
  "http://127.0.0.1:8000/v1/usage/events" +
  "?model=deepseek-ai%2FDeepSeek-V4-Flash&limit=100"
)
```

## 测试

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
python -m unittest discover -s tests -v
```

测试不访问真实SiliconFlow、Kimi或Elasticsearch，外部边界使用受控传输进行验证。

## 生产服务器部署

生产部署使用根目录的 `compose.yaml`，执行顺序为：服务器基础环境、MongoDB/ES、API 与 Nginx。

安全边界：

- 只发布 Nginx 的 `80` 端口；MongoDB `27017`、Elasticsearch `9200` 和 API `8000` 均不映射到宿主机；
- MongoDB 强制认证，root 与应用账户使用不同的随机密码；应用账户只拥有 `mechanics_agent` 数据库的 `readWrite` 权限；
- Secret 文件权限为 `0600`，被 `.gitignore` 与 `.dockerignore` 排除；
- 数据网络设置为 Docker `internal` 网络，MongoDB 与 ES 不能直接访问公网；
- 全站通过 Nginx Basic Auth 保护，`/health/live` 除外；
- 每日 03:30 自动执行 MongoDB 备份，本机保留 14 天。正式运行还应将备份复制到独立的阿里云 OSS Bucket。

首次部署：

```bash
sudo bash deploy/server-bootstrap.sh
cd /opt/mechanics-agent
cp .env.server.example .env.server
sudo bash deploy/prepare-secrets.sh
sudo bash deploy/release.sh 0.1.0
sudo bash deploy/install-backup-timer.sh
sudo bash deploy/verify.sh
```

发布新版本与回滚：

```bash
sudo bash deploy/release.sh 0.1.1
sudo bash deploy/rollback.sh 0.1.0
```

阿里云安全组只需允许可信来源访问 `22`，并按需要开放 `80/443`。不要添加 `27017` 或 `9200` 的公网入方向规则。

## 当前尚未接入

- SolidWorks COM/API 适配器；
- Abaqus Python 建模、提交作业和 ODB 提取适配器；
- Ansys 桌面执行端与服务器任务/审批 API 的身份认证和双向任务同步；
- Ansys v0.11.1 完整 UI 源码（当前发布包未提供）；
- 用户现有 ES 索引映射和向量模型；
- 经工程师审核的正式规则、材料和基准案例；
- 项目级用户权限与正式 HTTPS 域名证书。

这些接口需要根据实际软件版本、许可证、现有 ES mapping 和知识来源确定。
