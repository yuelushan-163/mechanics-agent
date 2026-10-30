# Ansys Mechanical 2025 R2 力学助手 · Windows 桌面版

**当前版本：v0.11.1**（源码工程 `outputs/ansys-agent-mvp`，发布包 `outputs/Ansys力学助手_桌面版_v0.11.1.zip`）

一个面向 Ansys Mechanical 2025 R2 的本地力学助手：原生 Windows 窗口、统一模型 API 配置、独立对话助手，以及一个受控的线性静力分析工作流。它不通过浏览器操作 Mechanical，也不修改任何 Ansys 二进制。

大模型侧使用 Chat Completions 兼容协议，真实的供应商地址、模型名与密钥由使用者在本机填写。程序本身不内置任何凭证。

> 三条始终有效的前提：
> 1. 程序只做**已声明范围的自动检查与求解**，工程验收恒为人工复核；
> 2. 用户输入只以 JSON 数据进入 Mechanical 脚本，不拼接可执行代码；
> 3. 求解在**输出目录的副本**上进行，源 `.mechdat` 不会被覆盖。

---

## 1. 快速开始（使用发布包）

1. 完整解压 `Ansys力学助手_桌面版_v0.11.1.zip`，保留 `.exe`、`_internal`、`runtime_payload` 及全部随附文件。
2. 双击 `Ansys力学助手_v0.11.1/Ansys力学助手_v0.11.1.exe`。
3. 右上角「模型 API 设置」→ 填写 API 根地址、模型名、密钥 → **保存 API 配置**。
4. 程序自动进入「环境检查」页，检查并按需用内置离线包配置本机专用 Python 环境。
5. 点「检查 Ansys 连接」确认 Mechanical 可实际启动响应。
6. 按左侧三步：**模型 → 约束与外力 → 网格与求解**。

运行要求：Windows x64；本机已安装 Ansys Mechanical 2025 R2 及有效求解许可；至少 512 MB 可用磁盘空间。**无需单独安装 Python**，内置 Python 3.12.10 与 41 个固定版本离线依赖包随发布包提供。详见 [内置环境与首次配置说明](内置环境与首次配置说明.md)。

---

## 2. 目录结构

```
ai+力学/
├─ outputs/
│  ├─ ansys-agent-mvp/           源码工程（本目录，README 所在位置）
│  ├─ Ansys力学助手_v0.11.1/      打包产物目录（exe + _internal + runtime_payload）
│  └─ Ansys力学助手_桌面版_v0.11.1.zip   发布压缩包
└─ work/
   ├─ ansys-venv/                打包用 Python 3.12 虚拟环境（PyInstaller）
   └─ pyinstaller/               PyInstaller 中间产物
```

源码工程内的主要文件：

| 文件 | 作用 |
|---|---|
| `desktop_app.py` | 桌面应用入口；组合各 UI 混入类，持有工作流状态机。`--smoke-test` 可无界面自检 |
| `desktop_ui.py` | 主窗口布局、主题、结果页与运行记录 |
| `load_desktop.py` | 「约束与外力」页：载荷类型控件与几何对象选择 |
| `environment_desktop.py` | 「环境检查」页：首次配置引导 |
| `desktop_features.py` | 可视化选面、聊天草案应用、结果云图展示 |
| `api_core.py` | 模型传输层 + 有界、受校验的工具调用循环 |
| `api_server.py` | 回环 HTTP API 与本地设置页 |
| `chat_setup.py` | 聊天端参数草案工具（只生成草案，不执行求解） |
| `adapter.py` | 结构化 Mechanical 适配器：注入固定脚本 + JSON 请求 |
| `mechanical_loads.py` / `mechanical_tools.py` | 运行于 Mechanical 内部的 IronPython 片段 |
| `loads.py` | **载荷类型唯一数据源**（类别、单位、值字段、作用对象、JSON Schema） |
| `verification.py` | 确定性检查规则（求解前/后、收敛、支反力平衡） |
| `environment_manager.py` | 环境证据采集与离线修复；SHA256、Ansys 路径探测 |
| `knowledge.py` | 本地知识表只读检索（不执行规则代码） |
| `visual_selection.py` / `selection_worker.py` | 可视化选面客户端与其私有的 Mechanical 选择副本 |
| `tool_bridge.py` | 供宿主使用的 JSON-lines 工具桥 |
| `build_desktop.ps1` | 打包脚本：校验离线包 → PyInstaller → 拷贝数据文件 → 压缩 |
| `build_runtime_payload.py` | 生成内置离线运行时（CPython 嵌入包 + wheels + 清单） |
| `tools.schema.json` / `workflow.schema.json` / `openapi.json` | 工具、工作流与 HTTP 接口的契约 |
| `rules.ansys252.json` / `knowledge_catalog.json` / `benchmark_cases.json` | 规则映射、知识条目、基准用例 |
| `test_*.py` | 单元测试与回归测试（52 项） |

---

## 3. 桌面端使用流程

### 3.1 环境检查与首次配置

- 「检查并自动配置」：重新检查，可修复项用内置包恢复；「仅重新检查」：只收集状态。
- 「选择 Ansys 安装」：自动识别失败时手动指定 `aisol/Bin/winx64/AnsysWBU.exe`。
- 环境展开在 `%LOCALAPPDATA%/AnsysMechanicalAssistant/runtimes/`，不改系统 Python 与 PATH，不需要管理员权限。
- 状态含义：可自动配置 / 内置环境就绪 / 需手动处理 / 阻断 / 软件连接通过。**「软件连接通过」不等于求解许可或工程结果已验证。**
- 密钥只保存在内存，关闭程序后需重新输入；API 地址与模型名存在本机偏好中。

### 3.2 三步分析

1. **模型** — 选择已配置好的独立 `.mechdat`（几何与材料须在 Mechanical 中准备好）。程序读取几何面/边/顶点清单与分析名称，并默认打开一个 Mechanical 选择副本用于可视化选面。
2. **约束与外力** — 用面过滤器选择固定支撑面（读取固定面），选择载荷类型与作用范围（读取载荷范围），填写数值。
3. **网格与求解** — 设置全局网格尺寸，可选启用 2–4 档网格收敛；人工确认后求解。

聊天助手可生成参数草案，但**草案应用后仍需人工核对再求解**。

### 3.3 载荷类型（一次求解一个主载荷）

| 类型 | 选择对象 | 输入单位与含义 |
|---|---|---|
| 面上总力 | 几何面，可多选 | 全局 Fx/Fy/Fz，N（所选范围的总力） |
| 均布面压力 | 几何面，可多选 | Pa（正值压入，负值吸出） |
| 力矩 | 几何面，可多选 | 全局 Mx/My/Mz，N·mm |
| 重力 | 无需选择，作用于全部活动实体 | 全局 gx/gy/gz，m/s²（要求密度有效） |
| 远程力 | 耦合面，可多选 | 力 N + 作用点 X/Y/Z（mm）+ deformable/rigid |
| 顶点集中力 | 单个几何顶点 | 全局力 N（非任意节点力） |
| 沿边均布力 | 几何边，可多选 | 全局 qx/qy/qz，N/mm（总力 = 线密度 × 总边长） |

新增载荷类型只需在 `loads.py` 中登记，IronPython 片段通过注入 JSON 获取类别/单位/值字段，无需改动 Mechanical 侧脚本。详见 [载荷类型使用说明](载荷类型使用说明.md)。

### 3.4 网格与收敛

- 最多 2–4 档，每档在 `mesh_01`、`mesh_02`… 独立目录求解，`report.json` 汇总比较。
- 收敛阈值与依据由操作者填写。**位移收敛不代表应力收敛，也不代表工程验收。**
- 收敛判定不通过时整体结果标记为 `blocked`，而不是给出"合格"假象。

### 3.5 结果与复核

结果页显示应力、位移、载荷约束云图与数值卡片；报告同时写入 JSON 与 CSV。自动检查项见 [validation.md](validation.md)。

---

## 4. 输出物

每次运行在工作目录生成：

```
<输出目录>/
├─ request.json        本次请求快照（含载荷、约束、网格、收敛设置）
├─ report.json         汇总报告：各档结果、比较、规则状态、告警
├─ comparison.csv      带单位的逐档对比
├─ mesh_0N/            每档独立副本：case.mechdat、结果云图
└─ 模型人工复核.md      人工复核清单
```

`report.json` 关键字段：`state`、`levels[]`（每档 `mesh_size_mm` / `state` / 结果）、`result`（最大总变形 mm、最大等效应力 MPa、支反力）、`verification.rules[]`（`rule_id` / `status` / `reason`）、`convergence`、`warnings`。规则版本标识为 `RULE_VERSION`。

已存在的输出目录会被拒绝，不会覆盖历史结果。

---

## 5. 命令行与接口

### 5.1 适配器 CLI（`adapter.py`）

```powershell
& $pythonExe adapter.py smoke
& $pythonExe adapter.py inspect 'D:\models\cantilever.mechdat' --out 'D:\models\inspection.json'
& $pythonExe adapter.py plan cases.example.json
& $pythonExe adapter.py review cases.example.json
& $pythonExe adapter.py run cases.example.json --out 'D:\models\runs\first-run'
```

`plan` 只校验 JSON 配置，不启动 Ansys；`review` 启动 Mechanical 做只读求解前复核；`run` 会实际求解并占用本机许可。`--exe` 可显式指定 `AnsysWBU.exe`。

### 5.2 工具桥（`tool_bridge.py`）

标准输入每行一个 JSON，标准输出每行一个 JSON，错误以 `ok:false` 返回，不向模型开放任意脚本执行：

```json
{"id":"1","name":"inspect_project","arguments":{"project":"D:/models/cantilever.mechdat"}}
```

可用工具：`mechanical_status`、`inspect_project`、`review_static_model`、`validate_static_plan`、`run_static_workflow`、`run_static_cases`、`search_engineering_knowledge`，另有环境类 `environment_status`、`prepare_environment`。这是本地 JSON 行协议，不是 MCP 服务。

### 5.3 HTTP API（`api_server.py` / `start_api.ps1`）

提供回环 HTTP 服务与 `openapi.json` 描述的接口，用于本地集成测试。详见 [API使用说明.md](API使用说明.md)。

---

## 6. 工程红线与安全设计

- **输入即数据**：Mechanical 侧执行的是固定脚本，用户数值以 JSON 传入，不做字符串拼接生成代码。
- **单载荷 + 单固定支撑**：存在未声明的活动载荷/接触时会阻断，避免产生未确认的叠加工况。
- **副本求解**：每个工况重新打开基准文件，先另存再修改；记录源文件 SHA-256，校验源未被改动。
- **失败即留痕**：求解失败、图片导出失败、检查不通过都写入报告，不静默跳过。
- **任一 block 即整体 blocked**：支反力平衡、收敛、严重告警只要有一项阻断，整体状态即为 blocked。
- **模型权限受限**：对话模型只能调用固定工具（含环境检查与离线配置），不能生成任意命令或安装未打包的依赖；环境检查不发送密钥或系统环境变量。
- **人工复核恒定**：`review` 输出 `human_review_required` 是正常状态，表示自动项无阻断但仍需人工签核。

---

## 7. 已知限制

- 只支持线性静力、小变形、单载荷步、无活动接触。**不支持**接触、塑性、大变形、模态、屈曲、多载荷步与 Workbench 系统编排。
- 不自动建模、不自动导入 CAD、不猜测材料：材料参数必须由人工核实。
- 只检查到实体已分配材料，不会仅凭材料名称认定参数或线弹性假设正确。
- 压力工况的 CAD 面积与有限元离散面积可能不同，合力为估算并标记"待复核"。
- 点/边载荷的局部峰值应力不能直接作为强度验收依据；远程力的附加力矩与参考点须人工复核。
- 重力通过惯性加速度载荷等效实现，Mechanical 中加速度箭头方向与输入重力向量相反。
- 跨机器部署需另行配置认证与传输；本机 2025 R2 使用 `127.0.0.1` + `transport_mode="insecure"`，该配置仅用于本机原型。

---

## 8. 开发者指南

### 8.1 环境

```powershell
py -3.12 -m venv ..\..\work\ansys-venv            # 打包与测试统一用 Python 3.12 x64
.\..\..\work\ansys-venv\Scripts\python.exe -m pip install -r requirements-dev.txt pyinstaller pytest pyflakes
```

运行时依赖见 `requirements.txt`（`ansys-mechanical-core`、`fastapi`、`uvicorn`、`jsonschema`、`requests`、`Pillow`）。

### 8.2 测试与静态检查

```powershell
& $pythonExe -m pytest -q                          # 52 项，单个无界面解释器一次跑完
& $pythonExe -m pyflakes *.py                      # 排除 mechanical_*.py（IronPython 片段，符号由宿主提供）
& $pythonExe desktop_app.py --smoke-test           # GUI 冒烟：构建界面后退出，退出码 0 为通过
```

`mechanical_loads.py` / `mechanical_tools.py` 运行在 Mechanical 内部，`ExtAPI`、`Quantity` 等名字由宿主提供，pyflakes 报未定义名属预期，故排除。

### 8.3 打包

```powershell
powershell -ExecutionPolicy Bypass -File .\build_desktop.ps1
```

流程：校验离线运行时 → PyInstaller `--onedir --windowed` → 拷贝数据文件（`tools.schema.json`、`mechanical_*.py`、`loads.py`、`knowledge_catalog.json` 等）→ 写 `runtime.json` / `使用说明.txt` → 压缩为 `Ansys力学助手_桌面版_v0.11.1.zip`。

打包前请先同步版本号：`build_desktop.ps1` 中的 exe 名、输出目录名与 zip 名必须一致。

### 8.4 代码约定

- 载荷类型只在 `loads.py` 定义，其他模块一律引用，不得复制表。
- 需要文件哈希时用 `environment_manager.digest`，不要重复实现。
- 新增 Mechanical 侧能力写在 `mechanical_*.py` 的固定脚本中，通过 `action` 分派；不要动态生成脚本文本。
- 大文件（知识库 JSON、Mechanical 脚本文本）按 mtime 缓存，避免每次调用重读。

---

## 9. 版本历史

| 版本 | 主要变化 |
|---|---|
| v0.9 | Mechanical 可视化选面与回传、聊天参数草案、结果页应力/位移/载荷约束图 |
| v0.10 | 新增压力、力矩、重力、远程力、顶点集中力、沿边均布力；手动与聊天共用载荷结构 |
| v0.11 | 内置 Python 3.12.10 与 41 个固定版本离线依赖；保存 API 后自动检查配置环境，模型经固定工具读取检查结果 |
| **v0.11.1** | 维护性优化与回归测试补齐（详见下节），发布包与源码同步 |

### v0.11.1 变更（本次）

- **载荷类型收敛为单一数据源**：原先在 `loads.py` 与 `mechanical_loads.py`（4 张硬编码表）重复维护，现由 `loads.py` 定义、adapter 以 JSON 注入；注入值经单测逐项比对与原值一致。
- **删除死代码 49 行**：`DesktopUI._build_load_page` 被 `LoadDesktop` 在 MRO 中完全覆盖，永不执行。
- **消除重复实现**：三份 SHA256 实现合并为 `environment_manager.digest`；Mechanical 脚本文本与 133 KB 知识库 JSON 按 mtime 缓存；移除 adapter 导入期的文件系统扫描。
- **修复潜在缺陷**：`selection_worker.signature()` 对"边+顶点"混合排序时 `float` 与 `None` 比较会抛 `TypeError`（已改为字符串键排序并加回归测试）。
- **健壮性**：`verification` 缺位移数据时改为 `block` 而非 `KeyError`；`run_static_workflow` 无结果时给出可读错误。
- **可测性**：`environment_desktop` 惰性导入 tkinter，测试可在无界面解释器完成；`SelectionClient.terminate()` 公开化并修复日志句柄泄漏；Ansys 探测支持 `ProgramFiles` 环境变量。
- **质量门**：单测 44 → 52 项（新增 8 项回归），`pyflakes` 告警 6 → 0；真实 Mechanical 端到端复测通过（顶点集中力、重力两工况，支反力平衡，收敛闸门正确阻断）。

完整测试与优化记录见 [代码优化与测试报告_v0.11.1.md](代码优化与测试报告_v0.11.1.md)。

---

## 10. 文档索引

| 文档 | 内容 |
|---|---|
| [API使用说明.md](API使用说明.md) | 模型 API 配置、工具调用协议、HTTP 接口 |
| [载荷类型使用说明.md](载荷类型使用说明.md) | 七类载荷的选择对象、单位、聊天示例与复核规则 |
| [内置环境与首次配置说明.md](内置环境与首次配置说明.md) | 内置 Python 离线包、首次配置流程、状态含义 |
| [可视化与聊天使用说明.md](可视化与聊天使用说明.md) | Mechanical 选面回传、聊天草案、结果云图 |
| [知识规则接入说明.md](知识规则接入说明.md) | 本地知识检索、规则映射、受控网格收敛 |
| [validation.md](validation.md) | 自动检查项定义与实测验证记录 |
| [代码优化与测试报告_v0.11.1.md](代码优化与测试报告_v0.11.1.md) | 本次测试结果与优化明细 |

参考：
- https://mechanical.docs.pyansys.com/version/stable/user_guide/remote_session/grpc_security.html
- https://examples.mechanical.docs.pyansys.com/examples/00_basic/example_01_simple_structural_solve.html
- https://examples.workbench.docs.pyansys.com/version/stable/examples/pymechanical-integration/main.html
