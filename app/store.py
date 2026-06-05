from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from app.schemas import AuditStatus, ReportStatus


class NotFoundError(RuntimeError):
    pass


class Store:
    async def create_audit(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def get_audit(self, run_id: str) -> dict[str, Any]:
        raise NotImplementedError

    async def request_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def get_report(self, run_id: str, format: str) -> dict[str, Any]:
        raise NotImplementedError


class InMemoryStore(Store):
    def __init__(self) -> None:
        self._audits: dict[str, dict[str, Any]] = {}
        self._reports: dict[str, dict[str, Any]] = {}

    async def create_audit(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        record = {
            "run_id": payload["run_id"],
            "tenant_id": payload["tenant_id"],
            "trace_id": payload["trace_id"],
            "status": AuditStatus.QUEUED.value,
            "created_at": now,
            "updated_at": now,
        }
        self._audits[payload["run_id"]] = record
        return record

    async def get_audit(self, run_id: str) -> dict[str, Any]:
        record = self._audits.get(run_id)
        if record is None:
            raise NotFoundError(f"audit not found: {run_id}")
        return record

    async def request_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        key = f"{payload['run_id']}:{payload['format']}"
        now = datetime.now(UTC).isoformat()
        if key in self._reports:
            return self._reports[key]

        record = {
            "run_id": payload["run_id"],
            "tenant_id": payload["tenant_id"],
            "format": payload["format"],
            "status": ReportStatus.QUEUED.value,
            "idempotency_key": payload["idempotency_key"],
            "updated_at": now,
        }
        self._reports[key] = record
        return record

    async def get_report(self, run_id: str, format: str) -> dict[str, Any]:
        key = f"{run_id}:{format}"
        record = self._reports.get(key)
        if record is None:
            raise NotFoundError(f"report not found: {key}")
        return record


class RedisStore(Store):
    def __init__(
        self,
        redis: Redis,
        *,
        audit_stream: str,
        report_stream: str,
    ) -> None:
        self.redis = redis
        self.audit_stream = audit_stream
        self.report_stream = report_stream

    @staticmethod
    def _audit_key(run_id: str) -> str:
        return f"agentsee:audit:{run_id}"

    @staticmethod
    def _report_key(run_id: str, format: str) -> str:
        return f"agentsee:report:{run_id}:{format}"

    async def create_audit(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        record = {
            "run_id": payload["run_id"],
            "tenant_id": payload["tenant_id"],
            "trace_id": payload["trace_id"],
            "status": AuditStatus.QUEUED.value,
            "created_at": now,
            "updated_at": now,
        }
        key = self._audit_key(payload["run_id"])
        await self.redis.hset(key, mapping={k: str(v) for k, v in record.items()})
        await self.redis.xadd(
            self.audit_stream,
            {
                "event_type": "run.requested",
                "tenant_id": payload["tenant_id"],
                "run_id": payload["run_id"],
                "trace_id": payload["trace_id"],
                "seed_url": payload["seed_url"],
                "user_intent": payload["user_intent"],
                "auto_report": json.dumps(payload["auto_report"]),
                "report_format": payload["report_format"],
            },
        )
        return record

    async def get_audit(self, run_id: str) -> dict[str, Any]:
        record = await self.redis.hgetall(self._audit_key(run_id))
        if not record:
            raise NotFoundError(f"audit not found: {run_id}")
        return {k.decode(): v.decode() for k, v in record.items()}

    async def request_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        key = self._report_key(payload["run_id"], payload["format"])
        existing = await self.redis.hgetall(key)
        if existing:
            return {k.decode(): v.decode() for k, v in existing.items()}

        now = datetime.now(UTC).isoformat()
        record = {
            "run_id": payload["run_id"],
            "tenant_id": payload["tenant_id"],
            "format": payload["format"],
            "status": ReportStatus.QUEUED.value,
            "idempotency_key": payload["idempotency_key"],
            "updated_at": now,
        }

        await self.redis.hset(key, mapping={k: str(v) for k, v in record.items()})
        await self.redis.xadd(
            self.report_stream,
            {
                "event_type": "report.requested",
                "tenant_id": payload["tenant_id"],
                "run_id": payload["run_id"],
                "trace_id": payload["trace_id"],
                "format": payload["format"],
                "template_version": payload["template_version"],
                "requested_by": payload["requested_by"],
                "idempotency_key": payload["idempotency_key"],
            },
        )
        return record

    async def get_report(self, run_id: str, format: str) -> dict[str, Any]:
        record = await self.redis.hgetall(self._report_key(run_id, format))
        if not record:
            raise NotFoundError(f"report not found: {run_id}:{format}")
        return {k.decode(): v.decode() for k, v in record.items()}
