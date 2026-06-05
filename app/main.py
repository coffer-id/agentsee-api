from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from redis.asyncio import Redis

from app.config import settings
from app.schemas import (
    AuditCreateRequest,
    AuditCreateResponse,
    AuditStatus,
    AuditStatusResponse,
    ReportRequest,
    ReportRequestResponse,
    ReportStatus,
    ReportStatusResponse,
)
from app.store import InMemoryStore, NotFoundError, RedisStore, Store


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis: Redis | None = None
    store: Store
    try:
        redis = Redis.from_url(settings.redis_url)
        await redis.ping()
        store = RedisStore(
            redis,
            audit_stream=settings.audit_stream,
            report_stream=settings.report_stream,
        )
        app.state.redis_ready = True
    except Exception:
        if settings.redis_required:
            raise
        store = InMemoryStore()
        app.state.redis_ready = False

    app.state.store = store
    try:
        yield
    finally:
        if redis is not None:
            await redis.aclose()


app = FastAPI(title="agentsee-api", version="0.1.0", lifespan=lifespan)


def get_store() -> Store:
    return app.state.store


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    if getattr(app.state, "redis_ready", False):
        return {"status": "ready"}
    if settings.redis_required:
        raise HTTPException(status_code=503, detail="redis_unavailable")
    return {"status": "degraded"}


@app.post("/audits", response_model=AuditCreateResponse, status_code=202)
async def create_audit(req: AuditCreateRequest, store: Store = Depends(get_store)) -> AuditCreateResponse:
    run_id = f"run_{uuid4().hex[:12]}"
    trace_id = f"trace_{uuid4().hex[:16]}"

    await store.create_audit(
        {
            "run_id": run_id,
            "trace_id": trace_id,
            "tenant_id": req.tenant_id,
            "seed_url": req.seed_url,
            "user_intent": req.user_intent,
            "auto_report": req.auto_report,
            "report_format": req.report_format,
        }
    )

    return AuditCreateResponse(run_id=run_id, trace_id=trace_id, status=AuditStatus.QUEUED)


@app.get("/audits/{run_id}", response_model=AuditStatusResponse)
async def get_audit(run_id: str, store: Store = Depends(get_store)) -> AuditStatusResponse:
    try:
        record = await store.get_audit(run_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return AuditStatusResponse(
        run_id=record["run_id"],
        tenant_id=record["tenant_id"],
        status=AuditStatus(record["status"]),
        trace_id=record["trace_id"],
        created_at=datetime.fromisoformat(record["created_at"]),
        updated_at=datetime.fromisoformat(record["updated_at"]),
    )


@app.post("/reports/{run_id}", response_model=ReportRequestResponse, status_code=202)
async def request_report(
    run_id: str,
    req: ReportRequest,
    store: Store = Depends(get_store),
) -> ReportRequestResponse:
    trace_id = f"trace_{uuid4().hex[:16]}"
    idempotency_key = f"{req.tenant_id}:{run_id}:{req.format}:{req.template_version}"

    record = await store.request_report(
        {
            "run_id": run_id,
            "trace_id": trace_id,
            "tenant_id": req.tenant_id,
            "format": req.format,
            "template_version": req.template_version,
            "requested_by": req.requested_by,
            "idempotency_key": idempotency_key,
        }
    )

    return ReportRequestResponse(
        run_id=record["run_id"],
        format=record["format"],
        status=ReportStatus(record["status"]),
        idempotency_key=record["idempotency_key"],
    )


@app.get("/reports/{run_id}", response_model=ReportStatusResponse)
async def get_report(
    run_id: str,
    tenant_id: str = Query(...),
    format: str = Query(default="pdf", pattern="^(pdf|html)$"),
    store: Store = Depends(get_store),
) -> ReportStatusResponse:
    try:
        record = await store.get_report(run_id, format)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ReportStatusResponse(
        run_id=record["run_id"],
        tenant_id=tenant_id,
        format=record["format"],
        status=ReportStatus(record["status"]),
        idempotency_key=record["idempotency_key"],
        object_key=record.get("object_key"),
        presigned_url=record.get("presigned_url"),
        expires_at=datetime.fromisoformat(record["expires_at"]) if record.get("expires_at") else None,
        error_code=record.get("error_code"),
        error_message=record.get("error_message"),
        updated_at=datetime.fromisoformat(record.get("updated_at", datetime.now(UTC).isoformat())),
    )
