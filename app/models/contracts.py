from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    RUN_FINALIZED = "run.finalized"
    REPORT_REQUESTED = "report.requested"
    REPORT_COMPLETED = "report.completed"
    REPORT_FAILED = "report.failed"


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    COMPLETE_WITH_ERRORS = "complete_with_errors"
    FAILED = "failed"


class ReportStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class BudgetPolicyAction(str, Enum):
    NONE = "none"
    REDUCED_FANOUT = "reduced_fanout"
    DOWNGRADED_MODEL = "downgraded_model"
    SKIPPED_NON_CRITICAL_STAGE = "skipped_non_critical_stage"
    ABORTED_BUDGET_EXCEEDED = "aborted_budget_exceeded"


class TaskTotals(BaseModel):
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


class RunFinalizedPayload(BaseModel):
    run_status: RunStatus
    task_totals: TaskTotals
    auto_report: bool = False
    result_object_prefix: str


class ReportRequestedPayload(BaseModel):
    format: str = Field(pattern="^(pdf|html)$")
    template_version: str
    requested_by: str


class ReportCompletedPayload(BaseModel):
    report_status: ReportStatus = ReportStatus.COMPLETE
    format: str = Field(pattern="^(pdf|html)$")
    object_key: str
    expires_at: datetime


class ReportFailedPayload(BaseModel):
    report_status: ReportStatus = ReportStatus.FAILED
    error_code: str
    error_message: str
    dead_lettered: bool = False


class ContractEvent(BaseModel):
    # Ignore unknown fields for v1 forward compatibility.
    model_config = ConfigDict(extra="ignore")

    schema_version: str = "v1"
    event_type: EventType
    event_id: UUID
    occurred_at: datetime
    tenant_id: str
    run_id: str
    trace_id: str
    payload: dict[str, Any]

    run_fingerprint: str | None = None
    idempotency_key: str | None = None
    attempt: int | None = Field(default=None, ge=0)
    producer: str | None = None
    component_version: str | None = None
    correlation_id: str | None = None


class CostLedger(BaseModel):
    schema_version: str = "v1"
    tenant_id: str
    run_id: str
    run_fingerprint: str
    computed_at: datetime
    run_status: RunStatus
    estimated_usd: float

    tokens_in: int
    tokens_out: int
    llm_call_count: int
    pages_fetched: int
    bytes_fetched: int
    cpu_seconds: float
    memory_gb_seconds: float
    render_seconds: float
    object_store_put_count: int
    object_store_get_count: int
    redis_ops: int
    log_bytes: int

    model_breakdown: dict[str, Any] | None = None
    stage_costs: dict[str, Any] | None = None
    budget_policy_action: BudgetPolicyAction | None = None
    budget_policy_reason: str | None = None
