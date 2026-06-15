# agentsee-api

The hosted service layer for [AgentSee](https://github.com/hypositivist/agent_friction_score_impl). Provides a REST API for submitting site audits, tracking their status, and retrieving generated reports.

## What this repo contains

| Path | What it is |
|---|---|
| `app/` | FastAPI application |

Infrastructure (Terraform + Kubernetes manifests) lives in [`agentsee-infra`](https://github.com/shaolin-shen/agentsee-infra).

## Related repos

| Repo | Role |
|---|---|
| [`agentsee-infra`](https://github.com/coffer-id/agentsee-infra) | Terraform + Kubernetes manifests for AgentSee |
| [`agent_friction_score_impl`](https://github.com/hypositivist/agent_friction_score_impl) | Audit engine — runs site audits, produces `result.json` |
| [`ReportGenerator`](https://github.com/hypositivist/ReportGenerator) | Report renderer — consumes audit results, produces PDF/HTML |
| [`agent-intel-mvp`](https://github.com/hypositivist/agent-intel-mvp) | Shared AWS/GCP infrastructure (EKS cluster, VPC, ECR, Secrets Manager) |

## Architecture

See [AgentSeeHostedArchitecture.md](https://github.com/coffer-id/agentsee-infra/blob/main/AgentSeeHostedArchitecture.md) in `agentsee-infra` for the full design.

The short version:

```
Client → agentsee-api → Redis Streams → audit-worker (agent_friction_score_impl)
                                               ↓
                                         S3 (run JSON)
                                               ↓
                                       report-worker (ReportGenerator)
                                               ↓
                                         S3 (PDF/HTML) → presigned URL → Client
```

## API

```
POST /audits                      Submit a site audit
GET  /audits/{run_id}             Poll audit status + scores
POST /reports/{run_id}            Request a report (on-demand; idempotent)
GET  /reports/{run_id}            Poll report status + presigned download URL
```

Full request/response shapes are in [AgentSeeHostedArchitecture.md](AgentSeeHostedArchitecture.md#api-contract).

### `POST /audits` parameters

The audit request exposes the friction-engine knobs so any of the documented
customer runs can be reproduced as a single call. All fields beyond `tenant_id`
and `seed_url` are optional; the defaults reproduce the prior behavior.

| Field | Default | Notes |
|---|---|---|
| `tenant_id` | — | Required |
| `seed_url` | — | Required; seed/target URL |
| `user_intent` | `browsing` | e.g. `competitive_intel`, `shopping`, `comparison` |
| `profile` | `web-search` | `web-search` or `api-consumer` (API-docs audit) |
| `scope` | `site` | `site` (multi-page) or `page` (single URL); web-search only |
| `archetype` | `claude-code` | `httpx`, `anthropic`, or `claude-code` |
| `fanout` | `false` | Web-search only; improves findability confidence |
| `bare_fetch` | `false` | Skip search/synthesis stages |
| `urls` | — | Explicit URL list (scope=site); skips discovery/sampling |
| `n_pages` / `breadth` / `depth` | — | Crawl tuning when discovering pages |
| `site_context` | — | Inline site profile (grounds seed queries); web-search only |
| `auto_report` | `true` | Auto-request a report on finalize (web-search only) |
| `report_format` | `pdf` | `pdf` or `html` |

`api-consumer` rejects `urls`, `site_context`, and `fanout`; `scope=page` rejects `urls`.

Example — reproduce the WaterGuru run:

```json
{
  "tenant_id": "tenant_abc",
  "seed_url": "https://waterguru.com",
  "user_intent": "competitive_intel",
  "archetype": "anthropic",
  "fanout": true,
  "urls": ["https://waterguru.com/...", "..."],
  "site_context": {"site": "waterguru.com", "category": "..."}
}
```

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | API service |
| kubectl + Helm | Deploying to the existing EKS cluster |
| Terraform | Provisioning storage modules |
| AWS CLI | Authenticated to the same account as `agent-intel-mvp` |
| KEDA | Installed on the cluster for audit-worker autoscaling |

## Local development

```bash
# Install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run API locally (requires Redis running)
docker run -p 6379:6379 redis:7-alpine
uvicorn app.main:app --reload

# Run tests
pytest
```

## Deployment

All infrastructure (VPC, EKS, k8s manifests) lives in [`agentsee-infra`](https://github.com/coffer-id/agentsee-infra). See that repo for deployment steps.

### Build and push images

Images are pushed to the existing ECR registry from `agent-intel-mvp`:

```bash
# agentsee-api image is built from this repo and pushed to ECR
```

### Verify

```bash
kubectl -n agentsee get pods
kubectl -n agentsee get ingress
```

## Secrets

Secrets are managed via External Secrets Operator reading from AWS Secrets Manager path `agentsee/{environment}/app`. See [`agentsee-infra`](https://github.com/coffer-id/agentsee-infra) for the ESO manifests.

Required keys:

| Key | Value |
|---|---|
| `anthropic-api-key` | Anthropic API key for audit and report workers |
| `agentsee-s3-runs-bucket` | S3 bucket name for audit run JSON |
| `agentsee-s3-reports-bucket` | S3 bucket name for rendered reports |
