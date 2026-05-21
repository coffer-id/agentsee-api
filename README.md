# agentsee-api

The hosted service layer for [AgentSee](https://github.com/hypositivist/agent_friction_score_impl). Provides a REST API for submitting site audits, tracking their status, and retrieving generated reports.

## What this repo contains

| Path | What it is |
|---|---|
| `app/` | FastAPI application |
| `infra/k8s/agentsee/` | Kubernetes manifests for all AgentSee components |

Terraform infrastructure lives in `agent-intel-mvp` alongside the existing modules. See [Terraform changes](#terraform-changes) below.

## Related repos

| Repo | Role |
|---|---|
| [`agent_friction_score_impl`](https://github.com/hypositivist/agent_friction_score_impl) | Audit engine — runs site audits, produces `result.json` |
| [`ReportGenerator`](https://github.com/hypositivist/ReportGenerator) | Report renderer — consumes audit results, produces PDF/HTML |
| [`agent-intel-mvp`](https://github.com/hypositivist/agent-intel-mvp) | Shared AWS/GCP infrastructure (EKS cluster, VPC, ECR, Secrets Manager) |

## Architecture

See [AgentSeeHostedArchitecture.md](AgentSeeHostedArchitecture.md) for the full design.

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
pip install -e ".[dev]"

# Run API locally (requires Redis running)
docker run -p 6379:6379 redis:7-alpine
uvicorn app.main:app --reload
```

## Deployment

AgentSee deploys into the `agentsee` namespace on the existing `agent-intel-{env}` EKS cluster. It does not create a new cluster.

### 1. Provision storage

Storage modules live in `agent-intel-mvp`. From that repo:

```bash
cd terraform/envs/aws
terraform apply -target=module.agentsee_storage
```

### 2. Apply Kubernetes manifests

```bash
kubectl apply -k infra/k8s/agentsee/
```

### 3. Build and push images

Images are pushed to the existing ECR registry from `agent-intel-mvp`:

```bash
# audit-worker image is built from agent_friction_score_impl
# report-worker image is built from ReportGenerator
# agentsee-api and claude-code-fetcher are built from this repo
```

### 4. Verify

```bash
kubectl -n agentsee get pods
kubectl -n agentsee get ingress
```

## Terraform changes

All Terraform lives in `agent-intel-mvp` to avoid cross-state dependencies — the AgentSee storage modules need the OIDC provider ARN, VPC ID, and EKS security group IDs that are already outputs of that state.

What gets added there:
- `terraform/modules/aws/agentsee-storage/` — S3 runs + reports buckets, IRSA roles
- `terraform/modules/gcp/agentsee-storage/` — GCS equivalents, Workload Identity bindings
- 4 service names added to the existing `registry` module `for_each`
- New `agentsee/{env}/app` entry in the existing `secrets` module

## Secrets

Secrets are managed via External Secrets Operator (already installed on the cluster) reading from AWS Secrets Manager path `agentsee/{environment}/app`.

Required keys:

| Key | Value |
|---|---|
| `anthropic-api-key` | Anthropic API key for audit and report workers |
| `agentsee-s3-runs-bucket` | S3 bucket name for audit run JSON |
| `agentsee-s3-reports-bucket` | S3 bucket name for rendered reports |
