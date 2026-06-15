import asyncio
import json

from fastapi.testclient import TestClient

from app.main import app
from app.store import RedisStore


class FakeRedis:
    def __init__(self) -> None:
        self.hset_calls: list[tuple] = []
        self.xadd_calls: list[tuple[str, dict]] = []

    async def hset(self, key, mapping):
        self.hset_calls.append((key, mapping))

    async def xadd(self, stream, event):
        self.xadd_calls.append((stream, event))


def _enqueue(payload_overrides: dict) -> dict:
    return asyncio.run(_enqueue_async(payload_overrides))


async def _enqueue_async(payload_overrides: dict) -> dict:
    redis = FakeRedis()
    store = RedisStore(redis, audit_stream="audit-stream", report_stream="report-stream")
    payload = {
        "run_id": "run_x",
        "trace_id": "trace_x",
        "tenant_id": "tenant_abc",
        "seed_url": "https://example.com",
        "user_intent": "browsing",
        "auto_report": True,
        "report_format": "pdf",
        "profile": "web-search",
        "scope": "site",
        "archetype": "claude-code",
        "fanout": False,
        "bare_fetch": False,
        "urls": None,
        "n_pages": None,
        "breadth": None,
        "depth": None,
        "site_context": None,
    }
    payload.update(payload_overrides)
    await store.create_audit(payload)
    assert len(redis.xadd_calls) == 1
    _, event = redis.xadd_calls[0]
    return event


def test_defaults_emit_web_search_site_claude_code() -> None:
    event = _enqueue({})
    assert event["profile"] == "web-search"
    assert event["scope"] == "site"
    assert event["archetype"] == "claude-code"
    assert event["fanout"] == "false"
    assert event["bare_fetch"] == "false"
    # optional fields omitted when unset
    assert "urls" not in event
    assert "site_context" not in event
    assert "n_pages" not in event


def test_waterguru_shape_serializes_urls_and_site_context() -> None:
    urls = ["https://waterguru.com/a", "https://waterguru.com/b"]
    site_context = {"site": "waterguru.com", "category": "pool care"}
    event = _enqueue(
        {
            "user_intent": "competitive_intel",
            "archetype": "anthropic",
            "fanout": True,
            "urls": urls,
            "site_context": site_context,
        }
    )
    assert event["archetype"] == "anthropic"
    assert event["user_intent"] == "competitive_intel"
    assert event["fanout"] == "true"
    assert json.loads(event["urls"]) == urls
    assert json.loads(event["site_context"]) == site_context


def test_stripe_api_consumer_shape() -> None:
    event = _enqueue(
        {
            "profile": "api-consumer",
            "scope": "page",
            "archetype": "claude-code",
            "user_intent": "browsing",
        }
    )
    assert event["profile"] == "api-consumer"
    assert event["scope"] == "page"


def test_crawl_tuning_serialized_as_strings() -> None:
    event = _enqueue({"n_pages": 12, "breadth": 4, "depth": 3})
    assert event["n_pages"] == "12"
    assert event["breadth"] == "4"
    assert event["depth"] == "3"


def test_waterguru_request_accepted() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/audits",
            json={
                "tenant_id": "tenant_abc",
                "seed_url": "https://waterguru.com",
                "user_intent": "competitive_intel",
                "profile": "web-search",
                "scope": "site",
                "archetype": "anthropic",
                "fanout": True,
                "urls": ["https://waterguru.com/a"],
                "site_context": {"site": "waterguru.com"},
            },
        )
    assert resp.status_code == 202


def test_stripe_request_accepted() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/audits",
            json={
                "tenant_id": "tenant_abc",
                "seed_url": "https://docs.stripe.com/api",
                "user_intent": "browsing",
                "profile": "api-consumer",
                "scope": "page",
                "archetype": "claude-code",
                "auto_report": False,
            },
        )
    assert resp.status_code == 202


def test_api_consumer_rejects_urls() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/audits",
            json={
                "tenant_id": "tenant_abc",
                "seed_url": "https://docs.stripe.com/api",
                "profile": "api-consumer",
                "urls": ["https://docs.stripe.com/api/charges"],
            },
        )
    assert resp.status_code == 422


def test_page_scope_rejects_urls() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/audits",
            json={
                "tenant_id": "tenant_abc",
                "seed_url": "https://example.com",
                "scope": "page",
                "urls": ["https://example.com/x"],
            },
        )
    assert resp.status_code == 422


def test_invalid_archetype_rejected() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/audits",
            json={
                "tenant_id": "tenant_abc",
                "seed_url": "https://example.com",
                "archetype": "crawl4ai",
            },
        )
    assert resp.status_code == 422
