from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_audit_and_report_request_roundtrip() -> None:
    with TestClient(app) as client:
        create = client.post(
            "/audits",
            json={
                "tenant_id": "tenant_abc",
                "seed_url": "https://example.com",
                "user_intent": "browsing",
                "auto_report": True,
                "report_format": "pdf",
            },
        )
        assert create.status_code == 202
        run_id = create.json()["run_id"]

        status = client.get(f"/audits/{run_id}")
        assert status.status_code == 200
        assert status.json()["status"] == "queued"

        report = client.post(
            f"/reports/{run_id}",
            json={
                "tenant_id": "tenant_abc",
                "format": "pdf",
                "template_version": "template-v1",
                "requested_by": "api",
            },
        )
        assert report.status_code == 202
        assert report.json()["status"] == "queued"

        report_status = client.get(f"/reports/{run_id}", params={"tenant_id": "tenant_abc", "format": "pdf"})
        assert report_status.status_code == 200
        assert report_status.json()["status"] == "queued"
