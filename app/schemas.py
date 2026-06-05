from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AuditStatus(str, Enum):
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


class AuditCreateRequest(BaseModel):
    tenant_id: str
    seed_url: str
    user_intent: str = "browsing"
    auto_report: bool = True
    report_format: str = Field(default="pdf", pattern="^(pdf|html)$")


class AuditCreateResponse(BaseModel):
    run_id: str
    trace_id: str
    status: AuditStatus


class AuditStatusResponse(BaseModel):
    run_id: str
    tenant_id: str
    status: AuditStatus
    trace_id: str
    created_at: datetime
    updated_at: datetime


class ReportRequest(BaseModel):
    tenant_id: str
    format: str = Field(default="pdf", pattern="^(pdf|html)$")
    template_version: str = "template-v1"
    requested_by: str = "api"


class ReportRequestResponse(BaseModel):
    run_id: str
    format: str
    status: ReportStatus
    idempotency_key: str


class ReportStatusResponse(BaseModel):
    run_id: str
    tenant_id: str
    format: str
    status: ReportStatus
    idempotency_key: str
    object_key: str | None = None
    presigned_url: str | None = None
    expires_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    updated_at: datetime
