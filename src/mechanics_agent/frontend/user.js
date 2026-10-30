"use strict";

const DRAFT_KEY = "mechanics-agent-user-draft-v2";
const TEMPLATE_KEY = "mechanics-agent-selected-template-v1";
const RESULT_KEY = "mechanics-agent-analysis-result-v1";

const DEFAULT_DRAFT = {
  analysisType: "linear_static", geometryType: "beam",
  lengthUnit: "mm", forceUnit: "N", stressUnit: "MPa", massUnit: "tonne",
  directionX: "0", directionY: "-1", directionZ: "0",
  maxMeshChangeRatio: "0.05", maxForceBalanceError: "0.01",
};

document.addEventListener("DOMContentLoaded", () => {
  checkHealth();
  const page = document.documentElement.dataset.page;
  if (page === "home") initHome();
  if (page === "cases") initCases();
  if (page === "analysis-new") initAnalysisForm();
  if (page === "analysis-result") initResult();
});

function initHome() {
  const summary = document.querySelector("#draftSummary");
  const meta = document.querySelector("#draftMeta");
  const saved = readStorage(DRAFT_KEY);
  if (!saved || !saved.caseTitle) {
    summary.textContent = "还没有保存的分析草稿。";
    meta.replaceChildren(metaItem("建议", "从验收案例或空白案例开始"));
    document.querySelector("#continueDraftLink").textContent = "开始新分析";
    return;
  }
  summary.textContent = saved.caseTitle;
  meta.replaceChildren(
    metaItem("分析类型", formatAnalysisType(saved.analysisType)),
    metaItem("几何模型", formatGeometryType(saved.geometryType)),
  );
}

let templateCatalog = [];
let selectedTemplate = null;

function initCases() {
  document.querySelector("#retryTemplates").addEventListener("click", loadCaseTemplates);
  loadCaseTemplates();
}

async function loadCaseTemplates() {
  const list = document.querySelector("#caseTemplateList");
  const retry = document.querySelector("#retryTemplates");
  retry.hidden = true;
  try {
    templateCatalog = await requestJson("/v1/cases/templates");
    document.querySelector("#templateCount").textContent = `${templateCatalog.length} 个验收场景`;
    renderTemplateList();
    if (templateCatalog.length) selectTemplate(templateCatalog[0].template_id);
  } catch (error) {
    document.querySelector("#templateCount").textContent = "案例读取失败";
    retry.hidden = false;
    list.replaceChildren(emptyBlock("暂时无法读取案例", readableError(error)));
  }
}

function renderTemplateList() {
  const list = document.querySelector("#caseTemplateList");
  const fragment = document.createDocumentFragment();
  templateCatalog.forEach((template) => {
    const button = node("button", "", "template-row");
    button.type = "button";
    button.dataset.templateId = template.template_id;
    button.setAttribute("aria-pressed", String(selectedTemplate?.template_id === template.template_id));
    const copy = node("span", "", "template-row-copy");
    copy.append(node("strong", template.title), node("small", template.capability_tags.slice(0, 3).map(formatCapability).join(" / ")));
    const outcome = expectedOutcome(template);
    button.append(copy, node("span", outcome.label, `template-outcome outcome-${outcome.kind}`));
    button.addEventListener("click", () => selectTemplate(template.template_id));
    fragment.append(button);
  });
  list.replaceChildren(fragment);
}

function selectTemplate(templateId) {
  selectedTemplate = templateCatalog.find((item) => item.template_id === templateId) || null;
  renderTemplateList();
  renderTemplateDetail(selectedTemplate);
}

function renderTemplateDetail(template) {
  const target = document.querySelector("#caseTemplateDetail");
  if (!template) {
    target.replaceChildren(emptyBlock("未找到案例", "请重新选择一个验收场景。"));
    return;
  }
  const outcome = expectedOutcome(template);
  const header = node("header", "", "template-detail-header");
  const title = node("div");
  title.append(node("span", outcome.label, `template-outcome outcome-${outcome.kind}`), node("h2", template.title));
  header.append(title, node("span", formatInputMode(template.case.geometry?.input_mode), "input-mode"));

  const metrics = node("dl", "", "template-metrics");
  Object.entries(template.expected_results || {}).slice(0, 4).forEach(([key, value]) => {
    const item = node("div");
    item.append(node("dt", formatMetric(key)), node("dd", formatValue(value)));
    metrics.append(item);
  });

  const content = node("div", "", "template-detail-content");
  content.append(node("p", template.case.description || "该案例未提供说明。", "template-description"));
  if (metrics.children.length) content.append(metrics);
  content.append(detailGroup("异常流程", [template.abnormal_scenario?.trigger || "没有额外异常场景"]));
  const gates = [...new Set([...(template.required_confirmations || []), ...(template.case.required_confirmations || [])])];
  content.append(detailGroup("求解前需要确认", gates.length ? gates : ["没有额外审批项"]));

  const action = node("button", "载入此案例并继续", "button button-primary template-load-button");
  action.type = "button";
  action.addEventListener("click", () => {
    sessionStorage.setItem(TEMPLATE_KEY, JSON.stringify(template));
    window.location.href = "/analysis/new";
  });
  target.replaceChildren(header, content, action);
}

let form;
let currentStep = 0;
let maxVisitedStep = 0;
let saveTimer;
let activeTemplateCase = null;
const stepNames = ["基本信息", "材料与单位", "载荷", "边界条件", "验收目标"];

function initAnalysisForm() {
  form = document.querySelector("#caseForm");
  const blankRequested = new URLSearchParams(window.location.search).get("blank") === "1";
  if (blankRequested) {
    localStorage.removeItem(DRAFT_KEY);
    sessionStorage.removeItem(TEMPLATE_KEY);
  }
  const selected = readStorage(TEMPLATE_KEY, sessionStorage);
  if (selected?.case && !blankRequested) {
    activeTemplateCase = structuredClone(selected.case);
    applyCaseToForm(activeTemplateCase);
    document.querySelector("#activeTemplateNotice").hidden = false;
    document.querySelector("#activeTemplateTitle").textContent = selected.title;
    setDraftState("已载入验收案例");
    sessionStorage.removeItem(TEMPLATE_KEY);
  } else {
    const draft = readStorage(DRAFT_KEY);
    applyDraft({ caseId: newCaseId(), ...DEFAULT_DRAFT, ...(draft || {}) });
    setDraftState(draft ? "已恢复本机草稿" : "已建立空白草稿");
  }

  form.addEventListener("input", formChanged);
  form.addEventListener("change", formChanged);
  form.addEventListener("submit", submitPlan);
  document.querySelector("#previousStepButton").addEventListener("click", () => showStep(currentStep - 1));
  document.querySelector("#nextStepButton").addEventListener("click", nextStep);
  document.querySelector("#resetDraftButton").addEventListener("click", resetDraft);
  document.querySelector("#clearTemplateButton").addEventListener("click", clearTemplate);
  document.querySelector("#forceUnit").addEventListener("change", updateLoadUnit);
  document.querySelectorAll("[data-step-button]").forEach((button) => button.addEventListener("click", () => {
    const target = Number(button.dataset.stepButton);
    if (target <= maxVisitedStep) showStep(target);
  }));
  updateLoadUnit();
  showStep(0);
}

function formChanged() {
  if (activeTemplateCase) clearTemplate(false);
  setDraftState("正在保存草稿");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveDraft, 320);
  if (currentStep === 4) renderReviewSummary();
}

function nextStep() {
  if (!validateStep(currentStep)) return;
  maxVisitedStep = Math.max(maxVisitedStep, currentStep + 1);
  showStep(Math.min(currentStep + 1, 4));
}

function showStep(index) {
  currentStep = Math.max(0, Math.min(4, index));
  document.querySelectorAll("[data-step]").forEach((step) => {
    const active = Number(step.dataset.step) === currentStep;
    step.hidden = !active;
    step.classList.toggle("is-active", active);
  });
  document.querySelectorAll("[data-step-button]").forEach((button) => {
    const indexValue = Number(button.dataset.stepButton);
    button.classList.toggle("is-active", indexValue === currentStep);
    button.classList.toggle("is-complete", indexValue < maxVisitedStep);
    button.disabled = indexValue > maxVisitedStep;
  });
  document.querySelector("#progressTitle").textContent = stepNames[currentStep];
  document.querySelector("#progressCount").textContent = `${currentStep + 1} / 5`;
  document.querySelector("#progressBar").style.transform = `scaleX(${(currentStep + 1) / 5})`;
  document.querySelector("#previousStepButton").disabled = currentStep === 0;
  document.querySelector("#nextStepButton").hidden = currentStep === 4;
  document.querySelector("#submitPlanButton").hidden = currentStep !== 4;
  document.querySelector("#stepHint").textContent = currentStep === 4 ? "提交前请检查摘要" : `下一项：${stepNames[currentStep + 1]}`;
  hideFormError();
  if (currentStep === 4) renderReviewSummary();
  document.querySelector(".analysis-heading").scrollIntoView({ behavior: scrollMode(), block: "start" });
}

function validateStep(index) {
  clearInvalid();
  const step = document.querySelector(`[data-step="${index}"]`);
  const invalid = [...step.querySelectorAll("input, select, textarea")].find((item) => !item.checkValidity());
  let message = invalid ? "请先补齐当前页面带星号的字段。" : stepEngineeringIssue(index);
  if (message) {
    if (invalid) invalid.setAttribute("aria-invalid", "true");
    showFormError("当前信息还不能继续", message);
    invalid?.focus();
    return false;
  }
  saveDraft();
  return true;
}

function stepEngineeringIssue(index) {
  if (index === 0 && !objectives().length) return "至少需要提供一个设计目标。";
  if (index === 2 && [num("directionX"), num("directionY"), num("directionZ")].every((value) => value === 0)) return "载荷方向向量不能全部为 0。";
  if (index === 3 && !checked("supportADof").length) return "支承 A 至少需要选择一个受限自由度。";
  if (index === 3 && !checked("supportBDof").length) return "支承 B 至少需要选择一个受限自由度。";
  return "";
}

async function submitPlan(event) {
  event.preventDefault();
  for (let index = 0; index < 5; index += 1) {
    if (!validateStep(index)) {
      maxVisitedStep = Math.max(maxVisitedStep, index);
      showStep(index);
      return;
    }
  }
  const button = document.querySelector("#submitPlanButton");
  const hint = document.querySelector("#stepHint");
  button.disabled = true;
  button.textContent = "正在生成";
  hint.textContent = "正在检索知识并执行前置检查，可能需要约一分钟";
  hideFormError();
  const requestId = makeRequestId();
  try {
    const data = await requestJson("/v1/cases/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Request-ID": requestId },
      body: JSON.stringify({ case: caseSpec(), top_k: 8 }),
    });
    localStorage.setItem(RESULT_KEY, JSON.stringify({ data, requestId, createdAt: new Date().toISOString() }));
    window.location.href = "/analysis/result";
  } catch (error) {
    showFormError("分析计划生成失败", readableError(error), error.requestId || requestId);
    button.disabled = false;
    button.textContent = "生成分析计划";
    hint.textContent = "输入仍保留在当前浏览器";
  }
}

function renderReviewSummary() {
  const target = document.querySelector("#reviewSummary");
  const items = [
    ["案例", val("caseTitle") || "未填写"],
    ["分析", `${formatAnalysisType(val("analysisType"))} / ${formatGeometryType(val("geometryType"))}`],
    ["材料", [val("materialName"), val("materialGrade")].filter(Boolean).join(" ") || "未填写"],
    ["载荷", `${val("loadMagnitude") || "未填写"} ${val("forceUnit") || ""}`.trim()],
    ["支承", `${formatBoundaryType(val("supportAType"))} / ${formatBoundaryType(val("supportBType"))}`],
  ];
  const list = node("dl", "", "review-grid");
  items.forEach(([label, value]) => list.append(metaItem(label, value)));
  target.replaceChildren(node("h3", "提交摘要"), list);
}

function resetDraft() {
  if (!window.confirm("确定清空当前草稿吗？")) return;
  localStorage.removeItem(DRAFT_KEY);
  activeTemplateCase = null;
  form.reset();
  applyDraft({ caseId: newCaseId(), ...DEFAULT_DRAFT });
  document.querySelector("#activeTemplateNotice").hidden = true;
  maxVisitedStep = 0;
  showStep(0);
  setDraftState("已建立空白草稿");
}

function clearTemplate(reset = true) {
  activeTemplateCase = null;
  document.querySelector("#activeTemplateNotice").hidden = true;
  if (reset) resetDraft();
}

function initResult() {
  const saved = readStorage(RESULT_KEY);
  if (!saved?.data?.plan) {
    document.querySelector("#resultEmpty").hidden = false;
    return;
  }
  document.querySelector("#resultContent").hidden = false;
  const { data, requestId } = saved;
  const plan = data.plan;
  const check = data.precheck || {};
  const overall = check.overall || "warn";
  const status = document.querySelector("#precheckStatus");
  status.className = `result-status status-${overall}`;
  status.textContent = ({ pass: "前检通过", warn: "需要关注", block: "存在阻断" })[overall] || "已完成";
  document.querySelector("#planSummary").textContent = plan.summary || "分析计划已生成";
  document.querySelector("#planProvenance").textContent = `规划器：${data.planner || "未知"}，引用 ${(data.knowledge_hits || []).length} 条知识依据`;
  setText("#precheckCount", (check.results || []).length);
  setText("#missingCount", (plan.missing_inputs || []).length);
  setText("#cadCount", (plan.cad_actions || []).length);
  setText("#feaCount", (plan.fea_actions || []).length);
  setText("#precheckTabCount", (check.results || []).length);
  setText("#missingTabCount", (plan.missing_inputs || []).length);
  setText("#cadTabCount", (plan.cad_actions || []).length);
  setText("#feaTabCount", (plan.fea_actions || []).length);
  setText("#reviewTabCount", (plan.risk_flags || []).length + (plan.approval_required || []).length);
  document.querySelector("#outputMeta").textContent = `请求 ID：${requestId}`;
  document.querySelector("#copyRequestId").addEventListener("click", async (event) => {
    await navigator.clipboard.writeText(requestId);
    event.currentTarget.textContent = "已复制";
  });
  document.querySelectorAll("[data-result-tab]").forEach((button) => button.addEventListener("click", () => selectResultTab(button.dataset.resultTab, data)));
  selectResultTab("precheck", data);
}

function selectResultTab(name, data) {
  document.querySelectorAll("[data-result-tab]").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.resultTab === name)));
  const target = document.querySelector("#resultPanel");
  const plan = data.plan || {};
  const check = data.precheck || {};
  const titles = { precheck: "前置检查", missing: "需要补充", cad: "CAD 准备动作", fea: "Abaqus 分析动作", review: "风险与人工审核" };
  const header = node("header", "", "result-panel-heading");
  header.append(node("h2", titles[name]));
  let content;
  if (name === "precheck") content = ruleList(check.results || []);
  if (name === "missing") content = orderedList(plan.missing_inputs || [], "没有发现明确缺项");
  if (name === "cad") content = orderedList(plan.cad_actions || [], "暂无 CAD 准备动作");
  if (name === "fea") content = orderedList(plan.fea_actions || [], "暂无 Abaqus 动作");
  if (name === "review") {
    content = node("div", "", "review-sections");
    content.append(detailGroup("必须由工程师确认", plan.approval_required || []), detailGroup("风险", plan.risk_flags || []), detailGroup("分析假设", plan.assumptions || []));
  }
  target.replaceChildren(header, content);
}

function ruleList(items) {
  if (!items.length) return emptyBlock("暂无可执行规则", "当前知识检索没有返回前置规则。");
  const list = node("ol", "", "rule-result-list");
  items.forEach((item) => {
    const row = node("li", "", `rule-result rule-${item.status || "warn"}`);
    row.append(node("span", ({ pass: "通过", warn: "关注", block: "阻断" })[item.status] || "检查"), node("div", ""));
    row.lastChild.append(node("strong", item.name || item.rule_id), node("p", item.message || "已完成检查"));
    list.append(row);
  });
  return list;
}

function orderedList(items, emptyText) {
  if (!items.length) return emptyBlock("当前没有项目", emptyText);
  const list = node("ol", "", "action-list");
  items.forEach((item, index) => {
    const row = node("li");
    row.append(node("span", String(index + 1)), node("p", String(item)));
    list.append(row);
  });
  return list;
}

function applyDraft(draft) {
  Object.entries(draft).forEach(([name, stored]) => {
    if (Array.isArray(stored)) {
      form.querySelectorAll(`[name="${name}"]`).forEach((input) => { input.checked = stored.includes(input.value); });
    } else {
      const input = form.elements.namedItem(name);
      if (input && "value" in input) input.value = stored ?? "";
    }
  });
}

function readDraft() {
  const output = {};
  new FormData(form).forEach((stored, name) => { if (!name.endsWith("Dof")) output[name] = stored; });
  output.supportADof = checked("supportADof");
  output.supportBDof = checked("supportBDof");
  return output;
}

function saveDraft() {
  localStorage.setItem(DRAFT_KEY, JSON.stringify(readDraft()));
  setDraftState("草稿已保存");
}

function caseSpec() {
  if (activeTemplateCase) return structuredClone(activeTemplateCase);
  return {
    case_id: val("caseId"), title: val("caseTitle"), analysis_type: val("analysisType"), geometry_type: val("geometryType"), description: val("caseDescription") || null,
    unit_system: { length: val("lengthUnit"), force: val("forceUnit"), stress: val("stressUnit"), mass: val("massUnit") || null },
    material: { name: val("materialName"), grade: val("materialGrade") || null, state: val("materialState") || null, elastic_modulus: num("elasticModulus"), poisson_ratio: num("poissonRatio"), density: num("density"), yield_strength: num("yieldStrength"), ultimate_strength: null, source_id: val("materialSource") || null },
    loads: [{ name: val("loadName"), load_type: val("loadType"), region: val("loadRegion"), magnitude: num("loadMagnitude"), direction: [num("directionX"), num("directionY"), num("directionZ")], vector: null, unit: val("forceUnit"), description: null }],
    boundary_conditions: [
      { name: val("supportAName"), boundary_type: val("supportAType"), region: val("supportARegion"), constrained_dofs: checked("supportADof"), description: null },
      { name: val("supportBName"), boundary_type: val("supportBType"), region: val("supportBRegion"), constrained_dofs: checked("supportBDof"), description: null },
    ],
    acceptance: { max_displacement: num("maxDisplacement"), min_safety_factor: num("minSafetyFactor"), max_mesh_change_ratio: num("maxMeshChangeRatio") ?? 0.05, max_force_balance_error: num("maxForceBalanceError") ?? 0.01, target_mass: null, additional: {} },
    objectives: objectives(), metadata: { source: "user-workbench", connector_execution_requested: false },
  };
}

function applyCaseToForm(caseData) {
  const load = caseData.loads?.[0] || {};
  const supportA = caseData.boundary_conditions?.[0] || {};
  const supportB = caseData.boundary_conditions?.[1] || {};
  const direction = load.direction || [0, 0, 0];
  applyDraft({
    caseId: caseData.case_id, caseTitle: caseData.title, analysisType: caseData.analysis_type, geometryType: caseData.geometry_type,
    caseDescription: caseData.description || "", objectives: (caseData.objectives || []).join("，"),
    lengthUnit: caseData.unit_system?.length || "mm", forceUnit: caseData.unit_system?.force || "N", stressUnit: caseData.unit_system?.stress || "MPa", massUnit: caseData.unit_system?.mass || "tonne",
    materialName: caseData.material?.name || "", materialGrade: caseData.material?.grade || "", materialState: caseData.material?.state || "", materialSource: caseData.material?.source_id || "", elasticModulus: caseData.material?.elastic_modulus ?? "", poissonRatio: caseData.material?.poisson_ratio ?? "", yieldStrength: caseData.material?.yield_strength ?? "", density: caseData.material?.density ?? "",
    loadName: load.name || "", loadType: load.load_type || "", loadRegion: load.region || "", loadMagnitude: load.magnitude ?? load.final_value ?? "", directionX: direction[0] ?? 0, directionY: direction[1] ?? 0, directionZ: direction[2] ?? 0,
    supportAName: supportA.name || "", supportAType: supportA.boundary_type || "", supportARegion: supportA.region || "", supportADof: supportA.constrained_dofs || [], supportBName: supportB.name || "", supportBType: supportB.boundary_type || "", supportBRegion: supportB.region || "", supportBDof: supportB.constrained_dofs || [],
    maxDisplacement: caseData.acceptance?.max_displacement ?? "", minSafetyFactor: caseData.acceptance?.min_safety_factor ?? "", maxMeshChangeRatio: caseData.acceptance?.max_mesh_change_ratio ?? 0.05, maxForceBalanceError: caseData.acceptance?.max_force_balance_error ?? 0.01,
  });
}

async function checkHealth() {
  const box = document.querySelector("#serviceStatus");
  const text = document.querySelector("#serviceStatusText");
  if (!box || !text) return;
  try {
    const data = await requestJson("/health");
    const healthy = ["healthy", "configured"].includes(data.status);
    box.className = `service-status ${healthy ? "status-healthy" : "status-degraded"}`;
    text.textContent = healthy ? "服务正常" : "部分服务异常";
  } catch (error) {
    box.className = "service-status status-unavailable";
    text.textContent = "服务未连接";
    box.title = readableError(error);
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const type = response.headers.get("content-type") || "";
  const body = type.includes("application/json") ? await response.json() : { detail: await response.text() };
  if (!response.ok) {
    const error = new Error(typeof body.detail === "string" ? body.detail : `请求失败，状态码 ${response.status}`);
    error.payload = body;
    error.requestId = body.request_id || response.headers.get("x-request-id");
    throw error;
  }
  return body;
}

function readableError(error) {
  const detail = error?.payload?.detail;
  if (Array.isArray(detail)) return detail.map((item) => `${(item.loc || []).slice(1).join(".") || "输入"}: ${item.msg || "格式不正确"}`).join("；");
  if (typeof detail === "string" && /Elasticsearch/i.test(detail)) return "知识库暂时不可用。请稍后重试，并把请求 ID 交给开发人员。";
  if (typeof detail === "string" && detail) return detail;
  if (error instanceof TypeError && /fetch/i.test(error.message)) return "无法连接服务，请稍后重试。";
  return error?.message || "发生未知错误。";
}

function showFormError(title, message, requestId) {
  const panel = document.querySelector("#formError");
  panel.hidden = false;
  panel.replaceChildren(node("strong", title), node("p", message));
  if (requestId) panel.append(node("small", `请求 ID：${requestId}`));
  panel.scrollIntoView({ behavior: scrollMode(), block: "center" });
}

function hideFormError() {
  const panel = document.querySelector("#formError");
  if (!panel) return;
  panel.hidden = true;
  panel.replaceChildren();
}

function detailGroup(title, items) {
  const section = node("section", "", "detail-group");
  section.append(node("h3", title), orderedList(items || [], "当前没有项目"));
  return section;
}

function emptyBlock(title, text) {
  const block = node("div", "", "detail-empty");
  block.append(node("strong", title), node("p", text));
  return block;
}

function metaItem(label, value) {
  const item = node("div");
  item.append(node("dt", label), node("dd", value));
  return item;
}

function expectedOutcome(template) {
  const expected = template.expected_results || {};
  if (expected.expected_acceptance === "fail") return { kind: "fail", label: "预期不合格" };
  if (String(expected.expected_precheck || "").startsWith("block")) return { kind: "block", label: "预期阻断" };
  if (expected.expected_acceptance === "pass" || String(expected.expected_acceptance || "").startsWith("pass")) return { kind: "pass", label: "正常基准" };
  return { kind: "review", label: "工程审核" };
}

function formatCapability(value) {
  const labels = { text_to_geometry: "文字建模", beam: "梁", analytical_benchmark: "解析对标", expected_failure: "不合格判定", cad_part: "CAD 零件", shell: "壳", symmetry: "对称", closed_end: "封闭端", cad_assembly: "装配体", contact: "接触", pretension: "预紧", nonlinear: "非线性", thermal_load: "温度载荷", restraint: "约束", material_nonlinearity: "材料非线性", expected_block: "阻断门" };
  return labels[value] || value;
}

function formatInputMode(value) { return ({ text: "文字输入", cad_part: "CAD 零件", cad_assembly: "CAD 装配体" })[value] || "结构化输入"; }
function formatAnalysisType(value) { return ({ linear_static: "线性静力", nonlinear_static: "非线性静力", dynamic_implicit: "隐式动力", dynamic_explicit: "显式动力", thermal_stress: "热应力", buckling: "屈曲" })[value] || value || "未选择"; }
function formatGeometryType(value) { return ({ beam: "梁", shell: "壳", solid: "实体", mixed: "混合" })[value] || value || "未选择"; }
function formatBoundaryType(value) { return ({ fixed: "固支", pinned: "铰支", roller: "滚动支承", elastic: "弹性支承", symmetry: "对称" })[value] || value || "未填写"; }

function formatMetric(value) {
  const labels = { analytical_displacement_mm: "理论位移", analytical_bending_stress_mpa: "理论弯曲应力", yield_safety_factor: "屈服安全系数", expected_acceptance: "预期结论", analytical_hoop_stress_mpa: "环向应力", analytical_axial_stress_mpa: "轴向应力", analytical_mises_stress_mpa: "Mises 应力", assembly_part_count: "装配零件数", initial_friction_capacity_upper_bound_n: "初始摩擦上界", external_load_n: "外载", analytical_free_end_displacement_mm: "自由端位移", far_field_axial_stress_mpa: "远场轴向应力", elastic_screening_stress_mpa: "线弹性筛查应力", yield_strength_mpa: "屈服强度", expected_precheck: "预期前检" };
  return labels[value] || value.replaceAll("_", " ");
}

function formatValue(value) {
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(Math.round(value * 1000) / 1000);
  const labels = { pass: "合格", fail: "不合格", pass_if_local_boundary_peak_is_excluded: "排除局部边界峰值后合格", block_until_plastic_curve_is_supplied: "补齐塑性曲线前阻断" };
  return labels[value] || String(value);
}

function val(name) { const input = form.elements.namedItem(name); return input && "value" in input ? input.value.trim() : ""; }
function num(name) { const raw = val(name); const parsed = Number(raw); return raw !== "" && Number.isFinite(parsed) ? parsed : null; }
function checked(name) { return [...form.querySelectorAll(`[name="${name}"]:checked`)].map((input) => input.value); }
function objectives() { return val("objectives").split(/[，,;；\n]/).map((item) => item.trim()).filter(Boolean); }
function setDraftState(text) { document.querySelector("#draftState").textContent = text; }
function updateLoadUnit() { document.querySelector("#loadUnitLabel").textContent = activeTemplateCase?.loads?.[0]?.unit || val("forceUnit") || "N"; }
function clearInvalid() { form.querySelectorAll("[aria-invalid]").forEach((input) => input.removeAttribute("aria-invalid")); }
function setText(selector, value) { document.querySelector(selector).textContent = String(value); }
function node(tag, text = "", className = "") { const element = document.createElement(tag); element.textContent = text; if (className) element.className = className; return element; }
function readStorage(key, storage = localStorage) { try { return JSON.parse(storage.getItem(key)); } catch { storage.removeItem(key); return null; } }
function makeRequestId() { return `user-${crypto.randomUUID ? crypto.randomUUID().slice(0, 12) : Date.now().toString(36)}`; }
function newCaseId() { const date = new Date(); return `case-${date.getFullYear()}${String(date.getMonth() + 1).padStart(2, "0")}${String(date.getDate()).padStart(2, "0")}-001`; }
function scrollMode() { return matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"; }
