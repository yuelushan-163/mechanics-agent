from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentType(StrEnum):
    KNOWLEDGE = "knowledge"
    VERIFICATION_RULE = "verification_rule"
    MATERIAL = "material"
    BENCHMARK = "benchmark"
    SOLVER_ERROR = "solver_error"


class ReviewStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    RETIRED = "retired"


class VerificationStage(StrEnum):
    PRE = "pre"
    POST = "post"


class RuleSeverity(StrEnum):
    WARNING = "warning"
    BLOCK = "block"


class RuleEvaluator(StrEnum):
    REQUIRED_FIELD = "required_field"
    VECTOR_BALANCE = "vector_balance"
    RELATIVE_CHANGE = "relative_change"
    UPPER_BOUND = "upper_bound"
    RATIO_MIN = "ratio_min"
    EQUALS = "equals"
    EMPTY_COLLECTION = "empty_collection"
    FINITE_NUMBER = "finite_number"


class CheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"
    NOT_APPLICABLE = "not_applicable"


class OverallStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


class SourceReference(StrictModel):
    title: str
    locator: str
    version: str | None = None
    page_or_section: str | None = None


class VerificationRule(StrictModel):
    rule_id: str
    name: str
    description: str
    stage: VerificationStage
    analysis_types: list[str] = Field(default_factory=lambda: ["*"])
    evaluator: RuleEvaluator
    severity: RuleSeverity
    config: dict[str, Any]
    enabled: bool = True
    explanation_template: str | None = None


class KnowledgeDocument(StrictModel):
    doc_id: str
    doc_type: DocumentType
    title: str
    content: str
    domain: str
    analysis_types: list[str] = Field(default_factory=lambda: ["*"])
    tags: list[str] = Field(default_factory=list)
    status: ReviewStatus = ReviewStatus.DRAFT
    evidence_level: Literal["authoritative", "reviewed", "internal", "unreviewed"] = "unreviewed"
    sources: list[SourceReference] = Field(default_factory=list)
    rule: VerificationRule | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_rule_document(self) -> "KnowledgeDocument":
        if self.doc_type == DocumentType.VERIFICATION_RULE and self.rule is None:
            raise ValueError("verification_rule documents must include rule")
        if self.doc_type != DocumentType.VERIFICATION_RULE and self.rule is not None:
            raise ValueError("rule is only valid for verification_rule documents")
        return self


class UnitSystem(StrictModel):
    length: str
    force: str
    stress: str
    mass: str | None = None
    time: str | None = None
    temperature: str | None = None


class MaterialSpec(StrictModel):
    name: str
    grade: str | None = None
    state: str | None = None
    elastic_modulus: float | None = None
    poisson_ratio: float | None = None
    density: float | None = None
    yield_strength: float | None = None
    ultimate_strength: float | None = None
    allowable_stress: float | None = None
    allowable_basis: str | None = None
    thermal_expansion_coefficient: float | None = None
    thermal_reference_temperature: float | None = None
    temperature_dependent: bool = False
    plastic_stress_strain: list[list[float]] = Field(default_factory=list)
    temperature_properties: dict[str, list[list[float]]] = Field(default_factory=dict)
    source_id: str | None = None


class LoadSpec(StrictModel):
    name: str
    load_type: str
    region: str
    magnitude: float | None = None
    direction: list[float] | None = None
    vector: list[float] | None = None
    unit: str | None = None
    time_variation: str | None = None
    initial_value: float | None = None
    final_value: float | None = None
    reference_value: float | None = None
    description: str | None = None


class BoundaryConditionSpec(StrictModel):
    name: str
    boundary_type: str
    region: str
    constrained_dofs: list[str] = Field(default_factory=list)
    description: str | None = None


class AcceptanceCriteria(StrictModel):
    max_displacement: float | None = None
    max_equivalent_stress: float | None = None
    max_relative_slip: float | None = None
    max_benchmark_error: float | None = None
    min_safety_factor: float | None = None
    max_mesh_change_ratio: float = 0.05
    max_force_balance_error: float = 0.01
    target_mass: float | None = None
    additional: dict[str, float | str | bool] = Field(default_factory=dict)


class GeometryInput(StrictModel):
    input_mode: Literal["text", "cad_part", "cad_assembly"] = "text"
    cad_filename: str | None = None
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    assembly_inventory: dict[str, int] = Field(default_factory=dict)


class IdealizationSpec(StrictModel):
    model_dimension: Literal["beam", "shell", "solid", "mixed"] | None = None
    element_types: list[str] = Field(default_factory=list)
    section_orientation: str | None = None
    symmetry: str | None = None
    rationale: str | None = None
    preserved_features: list[str] = Field(default_factory=list)
    removed_features: list[str] = Field(default_factory=list)


class ContactSpec(StrictModel):
    name: str
    primary_region: str
    secondary_region: str
    normal_behavior: str = "hard_contact"
    tangential_behavior: str | None = None
    friction_coefficient: float | None = Field(default=None, ge=0)
    clearance: float | None = Field(default=None, ge=0)
    clearance_unit: str | None = None


class AnalysisStepSpec(StrictModel):
    name: str
    procedure: str
    sequence: int = Field(ge=1)
    nonlinear_geometry: bool = False
    actions: list[str] = Field(default_factory=list)


class MeshStrategy(StrictModel):
    global_size: float | None = Field(default=None, gt=0)
    refined_size: float | None = Field(default=None, gt=0)
    unit: str | None = None
    convergence_outputs: list[str] = Field(default_factory=list)
    target_element_count: int | None = Field(default=None, ge=1)


class BenchmarkSpec(StrictModel):
    name: str
    equation: str
    expected_value: float
    unit: str
    tolerance_ratio: float = Field(default=0.05, ge=0)
    assumptions: list[str] = Field(default_factory=list)


class CaseSpec(StrictModel):
    case_id: str
    title: str
    analysis_type: str = "linear_static"
    geometry_type: str | None = None
    description: str | None = None
    unit_system: UnitSystem | None = None
    material: MaterialSpec | None = None
    geometry: GeometryInput | None = None
    idealization: IdealizationSpec | None = None
    loads: list[LoadSpec] = Field(default_factory=list)
    boundary_conditions: list[BoundaryConditionSpec] = Field(default_factory=list)
    contacts: list[ContactSpec] = Field(default_factory=list)
    analysis_steps: list[AnalysisStepSpec] = Field(default_factory=list)
    mesh: MeshStrategy | None = None
    benchmarks: list[BenchmarkSpec] = Field(default_factory=list)
    required_confirmations: list[str] = Field(default_factory=list)
    acceptance: AcceptanceCriteria = Field(default_factory=AcceptanceCriteria)
    objectives: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseTemplateStatus(StrEnum):
    PENDING_CONFIRMATION = "pending_confirmation"
    APPROVED = "approved"


class CaseTemplate(StrictModel):
    template_id: str
    version: str
    title: str
    capability_tags: list[str]
    status: CaseTemplateStatus = CaseTemplateStatus.PENDING_CONFIRMATION
    case: CaseSpec
    expected_results: dict[str, float | int | str | bool]
    abnormal_scenario: dict[str, Any]
    engineering_corrections: list[str] = Field(default_factory=list)
    required_confirmations: list[str] = Field(default_factory=list)


class RuleResult(StrictModel):
    rule_id: str
    name: str
    status: CheckStatus
    message: str
    observed: dict[str, Any] = Field(default_factory=dict)
    source_doc_id: str | None = None


class VerificationSummary(StrictModel):
    case_id: str
    stage: VerificationStage
    overall: OverallStatus
    results: list[RuleResult]
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VerificationRequest(StrictModel):
    case: CaseSpec
    stage: VerificationStage
    evidence: dict[str, Any] = Field(default_factory=dict)


class AnalysisPlan(StrictModel):
    case_id: str
    summary: str
    assumptions: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    cad_actions: list[str] = Field(default_factory=list)
    fea_actions: list[str] = Field(default_factory=list)
    applicable_rule_ids: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    approval_required: list[str] = Field(default_factory=list)


class SearchHit(StrictModel):
    score: float
    document: KnowledgeDocument


class PlanRequest(StrictModel):
    case: CaseSpec
    top_k: int = Field(default=8, ge=1, le=30)
    query_vector: list[float] | None = None


class PlanResponse(StrictModel):
    plan: AnalysisPlan
    precheck: VerificationSummary
    knowledge_hits: list[SearchHit]
    planner: str


class KnowledgeSearchRequest(StrictModel):
    query: str
    analysis_type: str | None = None
    domain: str | None = None
    document_types: list[DocumentType] = Field(default_factory=list)
    top_k: int = Field(default=8, ge=1, le=50)
    query_vector: list[float] | None = None


class IngestResponse(StrictModel):
    indexed: int
    index_name: str


class AuditRecord(StrictModel):
    run_id: str
    case_id: str
    event_type: str
    overall: OverallStatus | None = None
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelUsageStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


class ModelUsageRecord(StrictModel):
    usage_id: str
    provider: str
    model: str
    model_key: str
    operation: str
    request_id: str | None = None
    provider_request_id: str | None = None
    status: ModelUsageStatus
    http_status: int | None = None
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    uncached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    usage_reported: bool
    pricing_found: bool
    currency: str = "CNY"
    input_rate_per_k_tokens: float = Field(default=0.0, ge=0)
    cached_input_rate_per_k_tokens: float = Field(default=0.0, ge=0)
    output_rate_per_k_tokens: float = Field(default=0.0, ge=0)
    input_cost: float = Field(default=0.0, ge=0)
    cached_input_cost: float = Field(default=0.0, ge=0)
    output_cost: float = Field(default=0.0, ge=0)
    total_cost: float = Field(default=0.0, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    error_type: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ModelUsageSummaryRow(StrictModel):
    provider: str
    model: str
    request_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    usage_missing_count: int = Field(ge=0)
    pricing_missing_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    uncached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    total_cost: float = Field(ge=0)
    currency: str = "CNY"


class ModelUsageSummary(StrictModel):
    rows: list[ModelUsageSummaryRow]
    request_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    uncached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    total_cost: float = Field(ge=0)
    currency: str = "CNY"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MonitoringState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"
    UNKNOWN = "unknown"


class MonitoringComponent(StrictModel):
    component: str
    label: str
    status: MonitoringState
    detail: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MonitoringSnapshot(StrictModel):
    status: MonitoringState
    components: dict[str, MonitoringComponent]
    usage: ModelUsageSummary | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ActiveProbeRequest(StrictModel):
    targets: list[Literal["planner", "embedding"]] = Field(
        default_factory=lambda: ["planner", "embedding"]
    )


class ActiveProbeResponse(StrictModel):
    results: dict[str, dict[str, Any]]
    snapshot: MonitoringSnapshot


class UserRole(StrEnum):
    ADMIN = "admin"
    ENGINEER = "engineer"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class UserCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    role: UserRole = UserRole.ENGINEER
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserRecord(UserCreate):
    user_id: str = Field(default_factory=lambda: str(uuid4()))
    status: UserStatus = UserStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    owner_user_id: str
    description: str | None = Field(default=None, max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectRecord(ProjectCreate):
    project_id: str = Field(default_factory=lambda: str(uuid4()))
    status: ProjectStatus = ProjectStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TaskStatusEvent(StrictModel):
    status: TaskStatus
    changed_by: str | None = None
    comment: str | None = Field(default=None, max_length=2000)
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TaskCreate(StrictModel):
    project_id: str
    title: str = Field(min_length=1, max_length=240)
    task_type: Literal[
        "planning",
        "solidworks",
        "abaqus",
        "verification",
        "animation",
        "other",
    ] = "other"
    assigned_user_id: str | None = None
    input_data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskRecord(TaskCreate):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    status_history: list[TaskStatusEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TaskStatusUpdate(StrictModel):
    status: TaskStatus
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    changed_by: str | None = None
    comment: str | None = Field(default=None, max_length=2000)


class ApprovalCreate(StrictModel):
    project_id: str
    task_id: str
    subject: str = Field(min_length=1, max_length=240)
    requested_by: str
    reviewer_user_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalRecord(ApprovalCreate):
    approval_id: str = Field(default_factory=lambda: str(uuid4()))
    decision: ApprovalDecision = ApprovalDecision.PENDING
    decided_by: str | None = None
    decision_comment: str | None = None
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decided_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApprovalDecisionUpdate(StrictModel):
    decision: Literal[ApprovalDecision.APPROVED, ApprovalDecision.REJECTED]
    decided_by: str
    comment: str | None = Field(default=None, max_length=2000)


class PersistedErrorLog(StrictModel):
    log_id: str = Field(default_factory=lambda: str(uuid4()))
    sequence: int | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: str
    source: str = "server"
    message: str
    request_id: str | None = None
    method: str | None = None
    path: str | None = None
    status_code: int | None = None
    duration_ms: float | None = None
    details: Any = None
    traceback: str | None = None


class ClientErrorLogCreate(StrictModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: Literal["ERROR", "WARNING"]
    message: str = Field(min_length=1, max_length=4000)
    request_id: str | None = None
    method: str | None = None
    path: str | None = None
    status_code: int | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    details: Any = None
    traceback: str | None = None
