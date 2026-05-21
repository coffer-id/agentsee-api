---

## AgentSee Hosted Architecture

### Stack decisions

| Concern | Decision | Reason |
|---|---|---|
| Cluster | Existing `agent-intel-{env}` EKS, new `agentsee` namespace | No new cluster |
| Queue | Redis Streams, StatefulSet on k8s | Cloud-agnostic; runs identically on EKS and GKE |
| Object storage | S3 (AWS module) / GCS (GCP module) | Mirrors existing `modules/aws` + `modules/gcp` pattern |
| Container registry | Existing ECR via `modules/aws/registry` `for_each` | Add 4 service names |
| Secrets | Existing Secrets Manager + ESO pattern | New `agentsee/{env}/app` path |
| Networking | Existing VPC, ALB, LB Controller, IngressGroup | No new load balancer |
| Archetypes | All four including `claude-code` | `claude-code-fetcher` sidecar deployed |
| Report generation | Auto (after every audit) + on-demand API | Both supported |

---

### Component diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  Namespace: agentsee  (on existing agent-intel-{env} EKS cluster)    │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  agentsee-api   Deployment (2 replicas)                      │    │
│  │  FastAPI                                                      │    │
│  │  POST /audits            → enqueue, return run_id             │    │
│  │  GET  /audits/{run_id}   → status + scores                   │    │
│  │  POST /reports/{run_id}  → on-demand report trigger          │    │
│  │  GET  /reports/{run_id}  → status + presigned download URL   │    │
│  └───────────────┬──────────────────────────────────────────────┘    │
│                  │ Redis Streams publish/poll                         │
│                  ▼                                                    │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  Redis   StatefulSet (1 replica)                             │    │
│  │  Streams:  audit-queue, report-queue                         │    │
│  │  Hashes:   job:{run_id}  (status, started_at, error,         │    │
│  │                           report_status, report_url)         │    │
│  └────┬─────────────────────────────────┬────────────────────────┘    │
│       │ consume                         │ consume                     │
│       ▼                                 ▼                             │
│  ┌───────────────────────────┐  ┌──────────────────────────────┐     │
│  │  audit-worker             │  │  report-worker               │     │
│  │  Deployment               │  │  Deployment (2 replicas)     │     │
│  │  HPA via KEDA             │  │  Python + Node 18            │     │
│  │  (1–10 replicas)          │  │                              │     │
│  │  agent_friction_score_impl│  │  ReportGenerator             │     │
│  │                           │  │                              │     │
│  │  on success:              │  │  download run JSON ← S3      │     │
│  │  · upload run → S3        │  │  render PDF/HTML             │     │
│  │  · auto-publish to        │  │  upload report → S3          │     │
│  │    report-queue           │  │  write presigned URL → Redis │     │
│  └──────────┬────────────────┘  └──────────────────────────────┘     │
│             │ HTTP :8080                                              │
│             ▼                                                         │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  claude-code-fetcher   Deployment (2 replicas)               │    │
│  │  ClusterIP Service: claude-code-fetcher:8080                 │    │
│  │  (existing Dockerfile, unchanged)                            │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘

               ┌──────────────────────────────────────┐
               │  Object Storage                       │
               │  AWS:  S3 buckets                     │
               │  GCP:  GCS buckets (same code,        │
               │        boto3/S3-compat interface)     │
               │                                       │
               │  agentsee-{env}-runs-{account_id}/    │
               │    {run_id}/result.json               │
               │    {run_id}/pages/...                 │
               │                                       │
               │  agentsee-{env}-reports-{account_id}/ │
               │    {run_id}/{slug}.pdf                │
               │    {run_id}/{slug}.html               │
               └──────────────────────────────────────┘

Existing infrastructure (no changes):
  VPC / private subnets / NAT
  ALB + AWS Load Balancer Controller  ← agentsee-api Ingress uses IngressGroup
  ECR (registry module, for_each)     ← 4 new service names added
  Secrets Manager + ESO               ← new agentsee/{env}/app secret path
  OIDC provider                       ← new IRSA roles on top of it
```

---

### Job state machine

```
audit:   queued → running → complete ──► (auto) report: queued → running → complete
                          └──────────► (on-demand) POST /reports/{run_id}
                          └─ failed
```

State in Redis hash `job:{run_id}`:

```
status          queued | running | complete | failed
started_at      ISO timestamp
completed_at    ISO timestamp
error           string | null
report_status   queued | running | complete | failed | null
report_url      presigned S3 URL (24h TTL) | null
report_expires  ISO timestamp | null
```

---

### API contract

```
POST /audits
  { url, archetype, profile, company, industry, competitors[], auto_report }
  → 202 { run_id, status: "queued" }

GET /audits/{run_id}
  → { run_id, status, scores?, error? }

POST /reports/{run_id}          ← idempotent; no-op if already queued/complete
  { format: "pdf"|"html", company, industry }
  → 202 { run_id, report_status }

GET /reports/{run_id}
  → { run_id, report_status, url?, expires_at? }
```

---

### KEDA scaler for audit-worker

```yaml
# ScaledObject — scales on Redis Streams consumer group lag
triggers:
  - type: redis-streams
    metadata:
      address: redis.agentsee.svc.cluster.local:6379
      stream: audit-queue
      consumerGroup: audit-workers
      pendingEntriesCount: "5"    # 1 new replica per 5 pending jobs
minReplicaCount: 1
maxReplicaCount: 10
```

---

### Terraform changes

**Leverage — extend existing modules:**

```hcl
# modules/aws/registry/variables.tf — add to services list
services = [
  "migrate", "ingest", "worker", "api", "web", "flink",
  "agentsee-api", "agentsee-audit-worker",
  "agentsee-report-worker", "agentsee-claude-code-fetcher"
]

# modules/aws/secrets — add to agentsee/{env}/app secret
"anthropic-api-key"              = var.anthropic_api_key
"agentsee-s3-runs-bucket"        = aws_s3_bucket.runs.bucket
"agentsee-s3-reports-bucket"     = aws_s3_bucket.reports.bucket
```

**Add — new modules in `agent-intel-mvp` (mirrored AWS + GCP):**

```
terraform/modules/aws/agentsee-storage/    ← S3 runs + reports buckets, IRSA roles
terraform/modules/gcp/agentsee-storage/    ← GCS equivalents, Workload Identity bindings
```

Terraform lives in `agent-intel-mvp` rather than `agentsee-api` to avoid cross-state dependencies — the storage modules reference the OIDC provider ARN, VPC ID, and EKS node security group IDs that are already outputs of the `agent-intel-mvp` state.

AWS module resources:
- `aws_s3_bucket.runs` — `agentsee-{env}-runs-{account_id}`
- `aws_s3_bucket.reports` — `agentsee-{env}-reports-{account_id}`
- `aws_iam_role.audit_worker` — `s3:PutObject` on runs bucket (IRSA)
- `aws_iam_role.report_worker` — `s3:GetObject` on runs, `s3:PutObject` on reports (IRSA)

---

### Kubernetes manifests layout

Redis is k8s-only (no Terraform) — runs identically on EKS and GKE:

```
infra/k8s/agentsee/
  namespace.yaml
  redis/
    statefulset.yaml        ← bitnami/redis, 1 replica, PVC 10Gi
    service.yaml            ← ClusterIP :6379
  agentsee-api/
    deployment.yaml
    service.yaml
    ingress.yaml            ← alb.ingress.kubernetes.io/group.name: agent-intel
  audit-worker/
    deployment.yaml
    scaledobject.yaml       ← KEDA Redis Streams scaler
  report-worker/
    deployment.yaml
  claude-code-fetcher/
    deployment.yaml         ← existing Dockerfile, promoted from services/
    service.yaml            ← ClusterIP :8080
  secrets/
    external-secret.yaml    ← ESO: reads agentsee/{env}/app from Secrets Manager
```

---

### Code changes required in existing repos

**`agent_friction_score_impl`** — 3 additions, pipeline untouched:
1. `storage/object_store.py` — boto3 upload of `data/runs/{run_id}/` tree; bucket name from env var
2. `auth.py` — env var already supported; make it primary path (Keychain fallback for local dev only)
3. `worker/audit_consumer.py` — Redis Streams consumer, calls existing `run_site_audit()`, then uploads, then publishes to `report-queue` if `auto_report=true`

**`ReportGenerator`** — 2 additions, orchestrator untouched:
1. `storage/object_store.py` — download run JSON tree from S3 to temp dir; upload finished report
2. `worker/report_consumer.py` — Redis Streams consumer, calls existing `orchestrator.run()`, uploads result, writes presigned URL to Redis

**New: `agentsee-api`** — this repo:
- FastAPI app (thin: enqueue, status reads from Redis, presigned URL generation)
- `infra/k8s/agentsee/` manifests live here