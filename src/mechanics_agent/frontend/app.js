"use strict";

const DEMO_CASE = {
  case_id: "beam-demo-001",
  title: "简支梁强度与刚度校核",
  analysis_type: "linear_static",
  geometry_type: "beam",
  description: "跨度1200 mm的钢梁承受竖向集中载荷",
  unit_system: {
    length: "mm",
    force: "N",
    stress: "MPa",
    mass: "tonne",
  },
  material: {
    name: "结构钢",
    grade: "Q355",
    state: "示例，待确认",
    elastic_modulus: 210000,
    poisson_ratio: 0.3,
    yield_strength: 355,
    source_id: "待补充",
  },
  loads: [
    {
      name: "中点载荷",
      load_type: "concentrated_force",
      region: "MIDSPAN_LOAD_POINT",
      magnitude: 10000,
      direction: [0, -1, 0],
      unit: "N",
    },
  ],
  boundary_conditions: [
    {
      name: "左侧铰支",
      boundary_type: "pinned",
      region: "LEFT_SUPPORT",
      constrained_dofs: ["U1", "U2", "U3"],
    },
    {
      name: "右侧滚支",
      boundary_type: "roller",
      region: "RIGHT_SUPPORT",
      constrained_dofs: ["U2", "U3"],
    },
  ],
  acceptance: {
    max_displacement: 2,
    min_safety_factor: 1.5,
    max_mesh_change_ratio: 0.05,
    max_force_balance_error: 0.01,
  },
  objectives: ["满足强度和刚度约束", "最小化质量"],
  metadata: { demo_only: true },
};

const DEMO_EVIDENCE = {
  job_status: "COMPLETED",
  external_force: [0, -10000, 0],
  reaction_force: [0, 9998, 0],
  mesh_metric_coarse: 1.82,
  mesh_metric_fine: 1.88,
  max_displacement: 1.88,
  max_equivalent_stress: 210,
  high_risk_warnings: [],
};

const DEMO_INGEST = [
  {
    doc_id: "KNOW-DEMO-LOCAL-001",
    doc_type: "knowledge",
    title: "调试用梁结构检查说明",
    content:
      "本条只用于验证ES写入和检索链路。正式内容必须替换为带来源、版本、页码和审核记录的知识。",
    domain: "debug",
    analysis_types: ["linear_static"],
    tags: ["调试", "梁"],
    status: "draft",
    evidence_level: "unreviewed",
    sources: [],
    metadata: { demo_only: true },
  },
];

const state = {
  activeView: "overview",
  logs: [],
  serverCursor: 0,
  autoScroll: true,
  pollFailed: false,
};

const elements = {};

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  configureTheme();
  bindNavigation();
  bindActions();
  loadEditorState();
  renderLogs();
  checkHealth();
  pollMonitoringSnapshot();
  refreshOperationsHealth();
  loadPersistedErrorLogs();
  pollServerLogs();
  window.setInterval(pollMonitoringSnapshot, 5000);
  window.setInterval(refreshOperationsHealth, 15000);
  window.setInterval(pollServerLogs, 1800);
});

window.addEventListener("error", (event) => {
  addClientLog("ERROR", event.message || "前端运行时错误", {
    filename: event.filename,
    line: event.lineno,
    column: event.colno,
    stack: event.error?.stack,
  });
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  addClientLog("ERROR", "未处理的 Promise 异常", {
    reason: serializeError(reason),
  });
});

function cacheElements() {
  [
    "themeToggle",
    "serviceState",
    "serviceLight",
    "serviceStateText",
    "healthButton",
    "healthRaw",
    "plannerTestButton",
    "plannerTestRaw",
    "apiStatus",
    "apiDetail",
    "repositoryStatus",
    "repositoryDetail",
    "mongoStatus",
    "mongoDetail",
    "plannerStatus",
    "plannerDetail",
    "embeddingStatus",
    "embeddingDetail",
    "usageStatus",
    "usageDetail",
    "planEditor",
    "loadPlanDemo",
    "runPlan",
    "planResult",
    "verifyCaseEditor",
    "evidenceEditor",
    "verifyStage",
    "loadVerifyDemo",
    "runVerify",
    "verifyResult",
    "searchQuery",
    "searchAnalysisType",
    "searchTopK",
    "runSearch",
    "searchResult",
    "ingestEditor",
    "loadIngestDemo",
    "runIngest",
    "ingestResult",
    "logLevel",
    "logSource",
    "logSearch",
    "logStream",
    "logSummary",
    "copyLogs",
    "clearLogs",
    "autoScroll",
    "pollState",
    "toastRegion",
  ].forEach((id) => {
    elements[id] = document.getElementById(id);
  });
}

function configureTheme() {
  const saved = localStorage.getItem("mechanics-theme");
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = saved || (systemDark ? "dark" : "light");
  document.documentElement.dataset.theme = theme;
  elements.themeToggle.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("mechanics-theme", next);
    addClientLog("INFO", `主题已切换为${next === "dark" ? "深色" : "浅色"}`);
  });
}

function bindNavigation() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.view));
  });
  document.querySelectorAll("[data-jump]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.jump));
  });
  document.addEventListener("keydown", (event) => {
    if (event.target.matches("input, textarea, select")) return;
    const views = ["overview", "plan", "verify", "search", "ingest"];
    const index = Number(event.key) - 1;
    if (index >= 0 && index < views.length) showView(views[index]);
  });
}

function bindActions() {
  elements.healthButton.addEventListener("click", checkHealth);
  elements.plannerTestButton.addEventListener("click", testPlanner);
  elements.loadPlanDemo.addEventListener("click", loadPlanDemo);
  elements.loadVerifyDemo.addEventListener("click", loadVerifyDemo);
  elements.loadIngestDemo.addEventListener("click", loadIngestDemo);
  elements.runPlan.addEventListener("click", runPlan);
  elements.runVerify.addEventListener("click", runVerify);
  elements.runSearch.addEventListener("click", runSearch);
  elements.runIngest.addEventListener("click", runIngest);
  elements.copyLogs.addEventListener("click", copyVisibleLogs);
  elements.clearLogs.addEventListener("click", clearLogs);
  elements.autoScroll.addEventListener("change", () => {
    state.autoScroll = elements.autoScroll.checked;
  });
  [elements.logLevel, elements.logSource, elements.logSearch].forEach((control) => {
    control.addEventListener("input", renderLogs);
  });
  [
    ["planEditor", "mechanics-plan-request"],
    ["verifyCaseEditor", "mechanics-verify-case"],
    ["evidenceEditor", "mechanics-evidence"],
    ["ingestEditor", "mechanics-ingest"],
  ].forEach(([id, key]) => {
    elements[id].addEventListener("input", () => localStorage.setItem(key, elements[id].value));
  });
}

function loadEditorState() {
  elements.planEditor.value =
    localStorage.getItem("mechanics-plan-request") ||
    pretty({ case: DEMO_CASE, top_k: 8 });
  elements.verifyCaseEditor.value =
    localStorage.getItem("mechanics-verify-case") || pretty(DEMO_CASE);
  elements.evidenceEditor.value =
    localStorage.getItem("mechanics-evidence") || pretty(DEMO_EVIDENCE);
  elements.ingestEditor.value =
    localStorage.getItem("mechanics-ingest") || pretty(DEMO_INGEST);
}

function showView(viewName) {
  state.activeView = viewName;
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === viewName);
  });
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.viewPanel === viewName);
  });
}

function loadPlanDemo() {
  elements.planEditor.value = pretty({ case: DEMO_CASE, top_k: 8 });
  localStorage.setItem("mechanics-plan-request", elements.planEditor.value);
  addClientLog("INFO", "已载入案例规划示例");
}

function loadVerifyDemo() {
  elements.verifyCaseEditor.value = pretty(DEMO_CASE);
  elements.evidenceEditor.value = pretty(DEMO_EVIDENCE);
  localStorage.setItem("mechanics-verify-case", elements.verifyCaseEditor.value);
  localStorage.setItem("mechanics-evidence", elements.evidenceEditor.value);
  addClientLog("INFO", "已载入后处理验算示例");
}

function loadIngestDemo() {
  elements.ingestEditor.value = pretty(DEMO_INGEST);
  localStorage.setItem("mechanics-ingest", elements.ingestEditor.value);
  addClientLog("INFO", "已载入知识导入示例");
}

async function testPlanner() {
  setButtonBusy(elements.plannerTestButton, true, "测试中");
  elements.plannerStatus.textContent = "测试中";
  elements.embeddingStatus.textContent = "测试中";
  elements.plannerDetail.textContent = "后端正在主动调用规划模型";
  elements.embeddingDetail.textContent = "后端正在主动调用Embedding模型";
  try {
    const data = await apiRequest("/v1/monitoring/probe", {
      method: "POST",
      body: { targets: ["planner", "embedding"] },
      label: "后端主动探测模型",
    });
    elements.plannerTestRaw.textContent = pretty(data);
    elements.healthRaw.textContent = pretty(data.snapshot);
    renderMonitoringSnapshot(data.snapshot);
    const failed = Object.values(data.results || {}).some(
      (item) => item.status === "error",
    );
    showToast(failed ? "主动探测完成，存在失败项" : "模型主动探测完成", failed);
  } catch (error) {
    elements.plannerTestRaw.textContent = pretty(
      error.payload || serializeError(error),
    );
    elements.plannerStatus.textContent = "连接失败";
    elements.plannerDetail.textContent = error.message;
    elements.embeddingStatus.textContent = "未完成";
    elements.embeddingDetail.textContent = "主动探测请求失败";
  } finally {
    setButtonBusy(elements.plannerTestButton, false, "主动探测模型");
  }
}

async function checkHealth() {
  setButtonBusy(elements.healthButton, true, "检查中");
  setServiceState("unknown", "检查中");
  try {
    const data = await apiRequest("/v1/monitoring/status?refresh=true", {
      label: "读取后端监控快照",
    });
    elements.healthRaw.textContent = pretty(data);
    renderMonitoringSnapshot(data);
    await refreshOperationsHealth();
  } catch (error) {
    elements.healthRaw.textContent = pretty(error.payload || serializeError(error));
    elements.apiStatus.textContent = "异常";
    elements.apiDetail.textContent = error.message;
    elements.repositoryStatus.textContent = "不可用";
    elements.repositoryDetail.textContent = "请查看右侧服务端日志";
    elements.mongoStatus.textContent = "未确认";
    elements.mongoDetail.textContent = "MongoDB检查未完成";
    elements.plannerStatus.textContent = "未确认";
    elements.plannerDetail.textContent = "健康检查未完成";
    elements.embeddingStatus.textContent = "未确认";
    elements.embeddingDetail.textContent = "健康检查未完成";
    elements.usageStatus.textContent = "未确认";
    elements.usageDetail.textContent = "健康检查未完成";
    setServiceState("error", "服务异常");
  } finally {
    setButtonBusy(elements.healthButton, false, "刷新监控");
  }
}

async function refreshOperationsHealth() {
  try {
    const response = await fetch("/v1/operations/health", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    elements.mongoStatus.textContent = data.status === "ok" ? "正常" : "异常";
    elements.mongoDetail.textContent =
      data.backend === "mongodb"
        ? `MongoDB已连接：${data.database}`
        : "当前使用内存业务存储";
  } catch (error) {
    elements.mongoStatus.textContent = "不可用";
    elements.mongoDetail.textContent = "MongoDB连接失败，请查看错误日志";
  }
}

async function pollMonitoringSnapshot() {
  try {
    const response = await fetch("/health", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return;
    const snapshot = await response.json();
    elements.healthRaw.textContent = pretty(snapshot);
    renderMonitoringSnapshot(snapshot);
  } catch {
    setServiceState("error", "后端连接中断");
  }
}

function renderMonitoringSnapshot(snapshot) {
  const components = snapshot?.components || {};
  renderMonitoringComponent(components.api, elements.apiStatus, elements.apiDetail);
  renderMonitoringComponent(
    components.repository,
    elements.repositoryStatus,
    elements.repositoryDetail,
  );
  renderMonitoringComponent(
    components.planner,
    elements.plannerStatus,
    elements.plannerDetail,
  );
  renderMonitoringComponent(
    components.embedding,
    elements.embeddingStatus,
    elements.embeddingDetail,
  );
  renderMonitoringComponent(
    components.usage,
    elements.usageStatus,
    elements.usageDetail,
  );

  if (snapshot?.status === "healthy") {
    setServiceState("ok", "后端监控正常");
  } else if (snapshot?.status === "unknown") {
    setServiceState("unknown", "等待后端监控");
  } else {
    setServiceState("error", "后端监控发现异常");
  }
}

function renderMonitoringComponent(component, statusElement, detailElement) {
  if (!component) {
    statusElement.textContent = "未知";
    detailElement.textContent = "后端未返回该组件状态";
    return;
  }
  statusElement.textContent = statusText(component.status);
  detailElement.textContent = component.detail || "无详细信息";
}

async function runPlan() {
  let payload;
  try {
    payload = parseJsonEditor(elements.planEditor, "规划请求");
  } catch (error) {
    showPanelError(elements.planResult, error);
    return;
  }
  setLoading(elements.planResult);
  setButtonBusy(elements.runPlan, true, "生成中");
  try {
    const data = await apiRequest("/v1/cases/plan", {
      method: "POST",
      body: payload,
      label: "生成案例计划",
    });
    renderPlanResult(data);
  } catch (error) {
    showPanelError(elements.planResult, error);
  } finally {
    setButtonBusy(elements.runPlan, false, "生成计划");
  }
}

async function runVerify() {
  let caseData;
  let evidence;
  try {
    caseData = parseJsonEditor(elements.verifyCaseEditor, "案例");
    evidence = parseJsonEditor(elements.evidenceEditor, "验算证据");
  } catch (error) {
    showPanelError(elements.verifyResult, error);
    return;
  }
  setLoading(elements.verifyResult);
  setButtonBusy(elements.runVerify, true, "验算中");
  try {
    const data = await apiRequest("/v1/cases/verify", {
      method: "POST",
      body: {
        case: caseData,
        stage: elements.verifyStage.value,
        evidence,
      },
      label: "执行确定性验算",
    });
    renderVerificationResult(data);
  } catch (error) {
    showPanelError(elements.verifyResult, error);
  } finally {
    setButtonBusy(elements.runVerify, false, "执行验算");
  }
}

async function runSearch() {
  const query = elements.searchQuery.value.trim();
  if (!query) {
    const error = new Error("查询内容不能为空");
    addClientLog("ERROR", error.message);
    showPanelError(elements.searchResult, error);
    return;
  }
  const payload = {
    query,
    analysis_type: elements.searchAnalysisType.value.trim() || null,
    top_k: Number(elements.searchTopK.value) || 8,
  };
  setLoading(elements.searchResult);
  setButtonBusy(elements.runSearch, true, "检索中");
  try {
    const data = await apiRequest("/v1/knowledge/search", {
      method: "POST",
      body: payload,
      label: "检索力学知识",
    });
    renderSearchResult(data);
  } catch (error) {
    showPanelError(elements.searchResult, error);
  } finally {
    setButtonBusy(elements.runSearch, false, "执行检索");
  }
}

async function runIngest() {
  let payload;
  try {
    payload = parseJsonEditor(elements.ingestEditor, "知识文档");
    if (!Array.isArray(payload)) throw new Error("知识导入内容必须是JSON数组");
  } catch (error) {
    addClientLog("ERROR", error.message, { stack: error.stack });
    showPanelError(elements.ingestResult, error);
    return;
  }
  setLoading(elements.ingestResult);
  setButtonBusy(elements.runIngest, true, "写入中");
  try {
    const data = await apiRequest("/v1/knowledge/documents", {
      method: "POST",
      body: payload,
      label: "导入力学知识",
    });
    clearElement(elements.ingestResult);
    const content = node("div", "result-content");
    content.append(
      node("div", "success-callout", `已写入 ${data.indexed} 条文档`),
      rawDetails("完整响应", data),
    );
    elements.ingestResult.append(content);
  } catch (error) {
    showPanelError(elements.ingestResult, error);
  } finally {
    setButtonBusy(elements.runIngest, false, "写入 ES");
  }
}

async function apiRequest(path, options = {}) {
  const method = options.method || "GET";
  const requestId = `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
  const started = performance.now();
  addClientLog("INFO", `${options.label || path} 请求开始`, {
    request_id: requestId,
    method,
    path,
    body: options.body,
  });

  let response;
  let payload;
  try {
    response = await fetch(path, {
      method,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Request-ID": requestId,
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    const text = await response.text();
    payload = text ? safeJsonParse(text) : null;
  } catch (error) {
    addClientLog("ERROR", `${options.label || path} 网络请求失败`, {
      request_id: requestId,
      method,
      path,
      duration_ms: round(performance.now() - started),
      error: serializeError(error),
    });
    throw error;
  }

  const serverRequestId = response.headers.get("x-request-id") || requestId;
  const duration = round(performance.now() - started);
  if (!response.ok) {
    const error = new Error(extractErrorMessage(payload, response.status));
    error.status = response.status;
    error.payload = payload;
    error.requestId = serverRequestId;
    addClientLog("ERROR", `${options.label || path} 失败`, {
      request_id: serverRequestId,
      method,
      path,
      status_code: response.status,
      duration_ms: duration,
      response: payload,
    });
    showToast(`请求失败，请查看日志。请求ID ${serverRequestId}`, true);
    throw error;
  }

  addClientLog("INFO", `${options.label || path} 完成`, {
    request_id: serverRequestId,
    method,
    path,
    status_code: response.status,
    duration_ms: duration,
    response: payload,
  });
  return payload;
}

async function pollServerLogs() {
  try {
    const response = await fetch(
      `/v1/debug/logs?after=${state.serverCursor}&limit=200`,
      { headers: { Accept: "application/json" } },
    );
    if (!response.ok) throw new Error(`日志接口返回 HTTP ${response.status}`);
    const data = await response.json();
    (data.entries || []).forEach((entry) => {
      appendLog({ ...entry, key: `server-${entry.sequence}` });
      state.serverCursor = Math.max(state.serverCursor, entry.sequence || 0);
    });
    elements.pollState.textContent = "日志已同步";
    state.pollFailed = false;
    if (data.entries?.length) renderLogs();
  } catch (error) {
    elements.pollState.textContent = "日志同步失败";
    if (!state.pollFailed) {
      state.pollFailed = true;
      addClientLog("ERROR", "无法同步服务端日志", serializeError(error));
    }
  }
}

async function loadPersistedErrorLogs() {
  try {
    const response = await fetch("/v1/operations/error-logs?limit=200", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return;
    const entries = await response.json();
    entries.forEach((entry) =>
      appendLog({ ...entry, key: `persisted-${entry.log_id}` }),
    );
    if (entries.length) renderLogs();
  } catch {
    // The live in-memory log remains available if MongoDB is temporarily down.
  }
}

function logSignature(entry) {
  return [
    entry.source,
    entry.level,
    entry.request_id || "",
    entry.path || "",
    entry.message,
  ].join("|");
}

function appendLog(entry) {
  const signature = logSignature(entry);
  if (state.logs.some((item) => logSignature(item) === signature)) return;
  state.logs.push(entry);
  state.logs = state.logs.slice(-500);
}

function addClientLog(level, message, details = null) {
  const entry = {
    key: `client-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    sequence: null,
    timestamp: new Date().toISOString(),
    level,
    source: "client",
    message,
    request_id: details?.request_id || null,
    method: details?.method || null,
    path: details?.path || null,
    status_code: details?.status_code || null,
    duration_ms: details?.duration_ms || null,
    details,
    traceback: details?.stack || null,
  };
  appendLog(entry);
  renderLogs();
  if (level === "ERROR" || level === "WARNING") persistClientError(entry);
}

function persistClientError(entry) {
  fetch("/v1/operations/error-logs/client", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      timestamp: entry.timestamp,
      level: entry.level,
      message: entry.message,
      request_id: entry.request_id,
      method: entry.method,
      path: entry.path,
      status_code: entry.status_code,
      duration_ms: entry.duration_ms,
      details: entry.details,
      traceback: entry.traceback,
    }),
  }).catch(() => {
    // Do not recursively log failures of the log persistence endpoint.
  });
}

function renderLogs() {
  const level = elements.logLevel?.value || "ALL";
  const source = elements.logSource?.value || "ALL";
  const query = (elements.logSearch?.value || "").trim().toLowerCase();
  const visible = state.logs.filter((entry) => {
    if (level !== "ALL" && entry.level !== level) return false;
    if (source !== "ALL" && entry.source !== source) return false;
    if (!query) return true;
    return JSON.stringify(entry).toLowerCase().includes(query);
  });

  if (!elements.logStream) return;
  clearElement(elements.logStream);
  if (!visible.length) {
    const empty = node("div", "log-empty");
    empty.append(
      node("strong", "", state.logs.length ? "没有匹配日志" : "尚无日志"),
      node(
        "p",
        "",
        state.logs.length
          ? "调整级别、来源或筛选条件。"
          : "执行任意操作后，请求、响应和异常会显示在这里。",
      ),
    );
    elements.logStream.append(empty);
  } else {
    visible.forEach((entry) => elements.logStream.append(createLogEntry(entry)));
  }
  elements.logSummary.textContent = `${visible.length} 条可见，累计 ${state.logs.length} 条`;
  if (state.autoScroll) elements.logStream.scrollTop = elements.logStream.scrollHeight;
}

function createLogEntry(entry) {
  const article = node("article", "log-entry");
  article.dataset.level = entry.level;
  const header = node("header");
  header.append(
    node("span", "log-level", entry.level),
    node("time", "log-time", formatTime(entry.timestamp)),
  );
  article.append(header, node("p", "log-message", entry.message));

  const context = node("div", "log-context");
  const values = [
    entry.source === "server" ? "服务端" : "前端",
    entry.request_id ? `ID ${entry.request_id}` : null,
    entry.method && entry.path ? `${entry.method} ${entry.path}` : entry.path,
    entry.status_code ? `HTTP ${entry.status_code}` : null,
    entry.duration_ms != null ? `${entry.duration_ms} ms` : null,
  ].filter(Boolean);
  values.forEach((value) => context.append(node("span", "", value)));
  article.append(context);

  if (entry.details || entry.traceback) {
    const details = document.createElement("details");
    details.append(node("summary", "", "查看详情"));
    const detailPayload = {};
    if (entry.details) detailPayload.details = entry.details;
    if (entry.traceback) detailPayload.traceback = entry.traceback;
    details.append(node("pre", "", pretty(detailPayload)));
    article.append(details);
  }
  return article;
}

async function clearLogs() {
  try {
    await fetch("/v1/debug/logs", { method: "DELETE" });
  } catch (error) {
    showToast("服务端日志清理失败", true);
  }
  state.logs = [];
  state.serverCursor = 0;
  renderLogs();
  addClientLog("INFO", "日志已清空");
}

async function copyVisibleLogs() {
  const text = state.logs.map((entry) => pretty(entry)).join("\n\n");
  try {
    await navigator.clipboard.writeText(text);
    showToast("日志已复制");
  } catch (error) {
    addClientLog("ERROR", "复制日志失败", serializeError(error));
    showToast("复制失败，请查看日志", true);
  }
}

function renderPlanResult(data) {
  clearElement(elements.planResult);
  const content = node("div", "result-content");
  const titleRow = node("div", "result-title-row");
  titleRow.append(
    node("h2", "", data.plan?.summary || "分析计划"),
    statusLabel(data.precheck?.overall),
  );
  content.append(titleRow);
  content.append(
    resultListGroup("缺失输入", data.plan?.missing_inputs, "warn"),
    resultListGroup("风险提示", data.plan?.risk_flags, "warn"),
    resultListGroup("CAD动作", data.plan?.cad_actions),
    resultListGroup("有限元动作", data.plan?.fea_actions),
    verificationGroup(data.precheck?.results || []),
    knowledgeGroup(data.knowledge_hits || []),
    rawDetails("完整响应", data),
  );
  elements.planResult.append(content);
}

function renderVerificationResult(data) {
  clearElement(elements.verifyResult);
  const content = node("div", "result-content");
  const titleRow = node("div", "result-title-row");
  titleRow.append(
    node("h2", "", `${data.case_id} 验算结果`),
    statusLabel(data.overall),
  );
  content.append(titleRow, verificationGroup(data.results || []), rawDetails("完整响应", data));
  elements.verifyResult.append(content);
}

function renderSearchResult(data) {
  clearElement(elements.searchResult);
  const content = node("div", "result-content");
  const titleRow = node("div", "result-title-row");
  titleRow.append(
    node("h2", "", "检索结果"),
    node("span", "status-label", `${data.length} 条`),
  );
  content.append(titleRow);
  if (!data.length) {
    content.append(node("div", "warning-callout", "没有命中文档，请检查索引、审核状态和向量配置。"));
  } else {
    data.forEach((hit) => {
      const item = node("article", "document-result");
      const header = node("header");
      const titleWrap = node("div");
      titleWrap.append(
        node("h3", "", hit.document.title),
        node(
          "div",
          "document-meta",
          `${hit.document.doc_id} | ${hit.document.doc_type} | ${hit.document.status}`,
        ),
      );
      header.append(titleWrap, node("span", "status-label", Number(hit.score).toFixed(4)));
      item.append(header, node("p", "", hit.document.content));
      content.append(item);
    });
  }
  content.append(rawDetails("完整响应", data));
  elements.searchResult.append(content);
}

function verificationGroup(results) {
  const group = node("section", "result-group");
  group.append(node("h3", "", "规则结果"));
  const list = node("ul", "result-list");
  results.forEach((result) => {
    const item = node("li");
    item.dataset.status = result.status;
    item.append(
      node("strong", "", `${result.rule_id}  ${result.name}`),
      node("small", "", `${statusText(result.status)}：${result.message}`),
    );
    list.append(item);
  });
  if (!results.length) list.append(node("li", "", "没有适用规则"));
  group.append(list);
  return group;
}

function knowledgeGroup(hits) {
  const group = node("section", "result-group");
  group.append(node("h3", "", "检索知识"));
  const list = node("ul", "result-list");
  hits.forEach((hit) => {
    const item = node("li");
    item.append(
      node("strong", "", hit.document.title),
      node("small", "", `${hit.document.doc_id}  得分 ${Number(hit.score).toFixed(4)}`),
    );
    list.append(item);
  });
  if (!hits.length) list.append(node("li", "", "没有检索到已审核知识"));
  group.append(list);
  return group;
}

function resultListGroup(title, items, status = "") {
  const group = node("section", "result-group");
  group.append(node("h3", "", title));
  const list = node("ul", "result-list");
  (items || []).forEach((text) => {
    const item = node("li", "", text);
    if (status) item.dataset.status = status;
    list.append(item);
  });
  if (!items?.length) list.append(node("li", "", "无"));
  group.append(list);
  return group;
}

function rawDetails(title, data) {
  const details = node("details", "raw-panel");
  details.append(node("summary", "", title), node("pre", "", pretty(data)));
  return details;
}

function statusLabel(status) {
  const normalized = status || "unknown";
  const label = node("span", `status-label ${statusClass(normalized)}`, statusText(normalized));
  return label;
}

function statusClass(status) {
  if (status === "pass") return "status-pass";
  if (status === "warn" || status === "warning") return "status-warn";
  return "status-blocked";
}

function statusText(status) {
  const map = {
    pass: "通过",
    warn: "警告",
    warning: "警告",
    block: "阻断",
    not_applicable: "不适用",
    healthy: "正常",
    degraded: "降级",
    unavailable: "不可用",
    configured: "已配置",
    not_configured: "未配置",
    unknown: "未知",
  };
  return map[status] || status || "未知";
}

function setLoading(container) {
  clearElement(container);
  const loading = node("div", "loading-state");
  loading.append(
    node("div", "loading-line"),
    node("div", "loading-line"),
    node("div", "loading-line"),
  );
  container.append(loading);
}

function showPanelError(container, error) {
  clearElement(container);
  const content = node("div", "result-content");
  content.append(
    node("div", "error-callout", error.message || "操作失败"),
    rawDetails("错误详情", {
      request_id: error.requestId,
      status_code: error.status,
      response: error.payload,
      stack: error.stack,
    }),
  );
  container.append(content);
}

function parseJsonEditor(editor, label) {
  try {
    return JSON.parse(editor.value);
  } catch (error) {
    const wrapped = new Error(`${label}不是有效JSON：${error.message}`);
    wrapped.stack = error.stack;
    addClientLog("ERROR", wrapped.message, { stack: wrapped.stack });
    throw wrapped;
  }
}

function setButtonBusy(button, busy, label) {
  button.disabled = busy;
  button.textContent = label;
}

function setServiceState(kind, text) {
  elements.serviceLight.className = `state-light state-${kind}`;
  elements.serviceStateText.textContent = text;
}

function buildRepositoryDetail(repository) {
  if (!repository) return "未返回知识库信息";
  if (repository.backend === "elasticsearch") {
    return `${repository.cluster_name || "ES"} ${repository.version || ""}`.trim();
  }
  return `${repository.documents ?? 0} 条文档，${repository.runs ?? 0} 条审计`;
}

function showToast(message, isError = false) {
  const toast = node("div", `toast${isError ? " is-error" : ""}`, message);
  elements.toastRegion.append(toast);
  window.setTimeout(() => toast.remove(), 3200);
}

function node(tagName, className = "", text = null) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  if (text !== null && text !== undefined) element.textContent = String(text);
  return element;
}

function clearElement(element) {
  while (element.firstChild) element.removeChild(element.firstChild);
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function safeJsonParse(text) {
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

function serializeError(error) {
  if (error instanceof Error) {
    return { name: error.name, message: error.message, stack: error.stack };
  }
  return error;
}

function extractErrorMessage(payload, status) {
  if (typeof payload?.detail === "string") return payload.detail;
  if (Array.isArray(payload?.detail)) {
    return payload.detail
      .map((item) => `${(item.loc || []).join(".")}: ${item.msg}`)
      .join("；");
  }
  return `请求失败，HTTP ${status}`;
}

function formatTime(timestamp) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

function round(value) {
  return Math.round(value * 100) / 100;
}
