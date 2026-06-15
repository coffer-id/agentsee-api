from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


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

    profile: str = Field(default="web-search", pattern="^(web-search|api-consumer)$")
    scope: str = Field(default="site", pattern="^(page|site)$")
    archetype: str = Field(default="claude-code", pattern="^(httpx|anthropic|claude-code)$")
    fanout: bool = False
    bare_fetch: bool = False
    urls: list[str] | None = None
    n_pages: int | None = Field(default=None, ge=1)
    breadth: int | None = Field(default=None, ge=1)
    depth: int | None = Field(default=None, ge=1)
    site_context: dict | None = None

    @model_validator(mode="after")
    def _check_combinations(self) -> AuditCreateRequest:
        if self.profile == "api-consumer":
            if self.urls:
                raise ValueError("urls is not supported with profile=api-consumer")
            if self.site_context:
                raise ValueError("site_context is not supported with profile=api-consumer")
            if self.fanout:
                raise ValueError("fanout is not supported with profile=api-consumer")
        if self.scope == "page" and self.urls:
            raise ValueError("urls requires scope=site")
        return self


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
