# 14 · Deploying Agentic AI to Production — Architectures, Steps, Operations

> **Using Azure OpenAI + Azure + Langfuse?** Read [15-azure-openai-langfuse-deployment.md](15-azure-openai-langfuse-deployment.md) for the concrete stack (Bicep/Container Apps, managed identity, Langfuse). This file stays provider-neutral; its Kubernetes/Docker material applies to AKS.

Artifacts you can use right now (all in `project/`): `src/supportops/api.py` (FastAPI service), `Dockerfile`, `docker-compose.yml`, `k8s/deployment.yaml`, `.github/workflows/ci.yml` (repo root), `requirements-prod.txt`.

> **Verification status:** API layer = 10 passing tests + a live local smoke test (health, auth, validation, metrics). YAML files parse. **Not verified here:** the Docker image build (Docker daemon wasn't running), Kubernetes apply (no cluster), the CI pipeline (needs GitHub), and any real-model traffic. Treat them as a solid starting point to run and adjust.

---
## 1. The key idea: an agent service is a *stateless web service with unusual dependencies*

What you deploy = a normal API container. What's unusual:
| Property | Consequence for deployment |
|---|---|
| Each request is **slow** (5–60 s) and **I/O-bound** (waiting on the LLM) | Scale on *concurrency*, not CPU; long timeouts; graceful shutdown; consider streaming/async |
| **External provider with rate limits** | More pods ≠ more capacity; need a gateway, quotas, backoff, fallback |
| **Cost per request is variable and unbounded without caps** | Budgets, caps, per-tenant quotas, alerts |
| **Non-deterministic behaviour** | Evals gate releases; canary/shadow; trace everything |
| **Side effects through tools** | Idempotency, approvals, least privilege, audit |
| **State** (conversations, memory, tickets, vectors) | Externalise to DB/Redis/vector store; never local disk/memory |

---
## 2. Pick a deployment path

| Path | Good for | Watch out |
|---|---|---|
| **Serverless containers** (Cloud Run, AWS App Runner/Fargate, Azure Container Apps) | Small/medium teams, fastest path, scale-to-zero, simple ops | Request timeout limits; cold starts; concurrency tuning; VPC/egress control |
| **Kubernetes** (EKS/GKE/AKS) | Many services, strict networking/security, custom scaling (KEDA), platform team exists | Operational overhead; you own upgrades, policies |
| **Functions** (Lambda/Cloud Functions) | Short tools, webhooks, glue; *not* the agent loop if runs exceed limits | 15-min cap (Lambda), cold starts, no persistent connections |
| **Queue + workers** (SQS/Pub/Sub + containers, Celery, Temporal) | Long-running/async agents, approvals, retries | Result delivery (webhook/poll), idempotency |
| **Provider-managed agent runtime** | You want the provider to host loop + sandbox + sessions | Vendor lock-in, less control over infra; check compliance/regions |
| **VM + systemd/Docker Compose** | Prototypes, single-tenant internal tools | Manual scaling/HA/patching |

**Rule of thumb:** start with serverless containers (or the compose file) → move to Kubernetes when you need the control. Keep the *container* identical across all of them.

---
## 3. Reference architectures

### A. Small / startup (one region, minimal ops)
```
 Users ─► HTTPS (managed LB + WAF) ─► Cloud Run / App Runner / Container Apps  (agent API, 2..N instances)
                                           ├─► LLM provider (HTTPS egress)
                                           ├─► Managed Postgres  (conversations, tickets, refund ledger, audit)
                                           ├─► Managed Redis     (rate limit, idempotency keys, cache)
                                           ├─► Secrets Manager   (API keys)
                                           └─► Logs/metrics/traces → Datadog / Grafana Cloud / Langfuse
```

### B. Production on Kubernetes (the architecture implied by `k8s/`)
```
                      ┌────────────── monitoring ns ──────────────┐
                      │ Prometheus ─ Grafana ─ Alertmanager        │
                      │ OTel Collector ─► Tempo/Jaeger/Langfuse    │
                      └─────────▲─────────────────────────────────┘
 Users ─► CDN/WAF ─► Ingress (TLS, authN, global rate limit)
                      │
                      ▼
              Service ─► Pods: supportops-agent x3..20  (stateless, non-root, read-only FS)
                      │        │  HPA/KEDA • PDB • topology spread • rolling update
                      │        ├─► LLM GATEWAY ─► Provider A (primary) / Provider B (fallback)
                      │        ├─► Tool services (orders, payments) — each with its OWN authZ, idempotency
                      │        ├─► Postgres (HA, PITR backups)    Redis (HA)
                      │        └─► Approval service / ticketing (humans) ◄── ops UI
                      └─ NetworkPolicy: default-deny; egress only DNS + gateway
 Secrets: External Secrets Operator ◄─ Cloud secret manager      Images: signed, scanned, immutable tags
```

### C. Async / long-running agents (research, coding, batch jobs)
```
 Client ─► API ─► enqueue(job) ─► QUEUE ─► Worker pool (agent loops, autoscale on queue depth)
   ▲         │ 202 + job_id                     │ checkpoint after every tool call
   │         ▼                                   ▼
   └── poll / SSE / webhook ◄── Job store (status, result)  ◄── Checkpoint DB (resume after crash)
                                                 ├─► Sandbox service (code/browser tools; ephemeral microVMs)
                                                 └─► Human approval queue (pause/resume via event)
 Durable-execution alternative: Temporal/Step Functions run the loop as a workflow; LLM/tool calls = retryable activities.
```

### D. RAG platform (project 2 in production)
```
INGESTION (async):  Sources (S3, Drive, Confluence, DB) ─► change events ─► parse/OCR ─► chunk ─► embed (batch)
                    ─► Vector+keyword index (pgvector / OpenSearch / Qdrant)  +  metadata store (ACLs, versions)
                    ─► index version alias (blue/green re-index; rollback)
QUERY (sync):       API ─► authN → user groups ─► Supervisor agent ─► Researcher sub-agents (parallel)
                         ─► Retrieval service (hybrid + ACL filter on caller identity + reranker) ─► LLM
                         ─► citation verifier ─► answer + sources
OFFLINE:            retrieval evals (recall@k) on every index/chunking change; online sampling → judge → human review
MCP:                expose retrieval as MCP server over streamable HTTP + OAuth, behind gateway; read-only
```

### E. Multi-agent runtime considerations
- Sub-agents are **function calls within one process** until you need isolation; split into separate services only for different permissions/teams (then use A2A/HTTP + trace-context headers).
- Fan-out multiplies concurrent LLM calls → size rate limits for `requests × fan-out`.
- Per-run budget object passed to all sub-agents (tokens, time, delegations).

### F. High availability / multi-region
- Stateless API in ≥2 zones (topology spread). Active-active across regions for the API; **data stores** are the hard part (Postgres cross-region replica with failover, or region-pinned tenants for data residency).
- LLM fallback: second model/provider/region behind the gateway; test failover regularly.
- Define RTO/RPO; back up Postgres (PITR), vector index snapshots; rebuild-from-source runbook for indexes.

---
## 4. Step-by-step: deploy Project 1 (SupportOps)

### Step 0 — Run locally
```powershell
cd project
pip install -r requirements-prod.txt
$env:ANTHROPIC_API_KEY="sk-ant-..."; $env:API_KEYS='{"dev-key-1":"C-1"}'; $env:PYTHONPATH="src"
uvicorn supportops.api:app --port 8080
curl -X POST localhost:8080/v1/chat -H "x-api-key: dev-key-1" -H "content-type: application/json" -d '{"message":"Refund ORD-1001, cable broke"}'
```
Note: customer identity = the API key's owner. The body cannot override it (tested).

### Step 1 — Container
```bash
docker build -t supportops-agent:dev project/
docker compose -f project/docker-compose.yml up --build      # needs ANTHROPIC_API_KEY in env
```
Hardening already in the files: non-root user, read-only root FS, dropped capabilities, no-new-privileges, memory limit, healthcheck, no docs UI, immutable tags in k8s.

### Step 2 — Registry
Push to GHCR/ECR/Artifact Registry/ACR tagged with the **git SHA**. Scan (Trivy/Grype), generate SBOM, sign (cosign). Never deploy `:latest`.

### Step 3 — Secrets
Create the cloud secret (`ANTHROPIC_API_KEY`, API-key table). Sync into the cluster via External Secrets Operator / CSI driver. Separate keys per environment; set provider-side spend limits; rotate on schedule.

### Step 4 — Deploy
```bash
kubectl create namespace support && kubectl -n support apply -f project/k8s/secret.example.yaml   # edit first!
# edit the image tag in k8s/deployment.yaml
kubectl -n support apply -f project/k8s/deployment.yaml
kubectl -n support rollout status deploy/supportops-agent
kubectl -n support port-forward svc/supportops-agent 8080:80    # smoke test
```
Then add an **Ingress** with TLS (cert-manager / cloud cert), WAF, and request-size limits.

### Step 5 — Replace the in-memory parts (must-do before real traffic)
| In the project now | Production replacement |
|---|---|
| `ConversationStore` (memory) | Postgres/Redis with TTL, same interface (`get_history`, `append`) |
| Refund ledger & tickets (`ToolContext`) | Postgres tables; refunds via the payment API with an **idempotency key** (e.g. `order_id + request_id`); tickets to Zendesk/Jira/approval service |
| Token bucket per pod | Redis-based (shared) limiter, or limit at the gateway/ingress; also per-tenant daily token budgets |
| `API_KEYS` env | OIDC/JWT from your IdP or hashed keys in DB with rotation/revocation |
| JSONL trace files | OpenTelemetry export + log shipping to stdout; PII redaction stays |
| `orders.json` / KB files | Real order service (with its own authZ) and a retrieval service/index |
| Synchronous only | Add streaming (SSE) for UX; queue for long jobs |

### Step 6 — Observability
Scrape `/metrics` (annotations provided). Dashboards + alerts below. Ship traces to Tempo/Jaeger/Langfuse via OTel.

### Step 7 — Release
CI runs tests (free) → optional live evals gate → build → staging → smoke → manual approval → prod rolling update with automatic `rollout undo`. Use canary (Argo Rollouts/Flagger) once you have traffic.

---
## 5. Step-by-step: deploy Project 2 (Research agent)
1. **Services:** `research-api` (supervisor + researchers), `retrieval` (index + search; can live in the same process at first), `ingestion` (cron/worker), optional `mcp-server`.
2. **Replace** the hash-vector with a real embedding model; store vectors in **pgvector** (simplest) or OpenSearch/Qdrant; keep BM25 (Postgres `tsvector` / OpenSearch) for hybrid; add a reranker.
3. **ACLs:** chunks carry `allowed_groups`; `search(..., user_groups)` filters *inside the query*. The identity comes from the authenticated session, as in project 1.
4. **Ingestion:** scheduled/event-driven; content-hash to skip unchanged docs; delete propagation; write to a **new index version** then flip an alias (blue/green) so you can roll back a bad chunking change.
5. **Concurrency:** supervisor fan-out of N × workers → size LLM rate limits, set `max_delegations`, per-run token budget; keep thread pool bounded.
6. **MCP server:** for remote use run streamable-HTTP transport behind the gateway with OAuth/API-key auth, TLS, per-client rate limits, read-only credentials; stdio for local only.
7. **Tracing:** keep `parent_span` propagation; export spans via OTel; alert on cost per run and delegation-cap hits.
8. **Evals in CI:** retrieval eval (recall@k) must not regress; live multi-agent evals on a schedule.

---
## 6. State & data stores (what goes where)
| Data | Store | Notes |
|---|---|---|
| Conversations / checkpoints | Postgres (JSONB) or Redis w/ TTL | Owner column + index; retention policy; encrypt at rest |
| Rate limits, idempotency keys, short caches | Redis | Atomic ops (INCR/Lua) |
| Business records (refunds, tickets, approvals) | Postgres | Transactions; unique constraint on idempotency key |
| Vectors + keyword index | pgvector / OpenSearch / Qdrant | Versioned indexes; ACL metadata |
| Files/media/documents | Object storage (S3/GCS/Blob) | Signed URLs; virus scan; lifecycle rules |
| Traces/logs/metrics | OTel backend / Prometheus / Loki | Redact PII; retention & sampling |
| Prompts/tool schemas/policies | Git (+ registry) | Version id stamped on each trace |
| Secrets | Cloud secret manager/Vault | Never in images/env files/git |

---
## 7. Scaling & capacity
1. **Little CPU, lots of waiting** → keep CPU request small, no CPU limit; scale on **in-flight requests / queue depth** (KEDA + Prometheus or SQS), not CPU alone.
2. **Provider limits are the real ceiling:** measure RPM/TPM; implement client-side token bucket + exponential backoff with jitter (in `llm.py`); priority lanes (interactive > batch); request higher limits/priority capacity; use Batch API for offline work.
3. **Concurrency per pod:** uvicorn workers × thread pool (sync endpoints use a threadpool, default ~40) — tune against pod memory; or move to async clients.
4. **Graceful shutdown:** `terminationGracePeriodSeconds: 90` + `preStop` sleep so in-flight agent runs finish; return 503 on new work while draining.
5. **Timeouts everywhere:** client→gateway, gateway→app (> longest agent run), app→LLM (SDK timeout), tool calls; per-run wall-clock cap.
6. **Load testing:** replay *realistic multi-turn traces* with a fake/mocked or budget-capped LLM; measure p95 latency vs concurrency, memory, error rates; test provider 429s and outages.
7. **Backpressure:** bounded queues, 429 with `Retry-After`, shed low-priority work first.
8. **Caching:** prompt caching (stable prefix first), tool-result caching for deterministic reads, answer caching only where safe (no personalised data).

---
## 8. Observability stack (what to deploy)
- **Metrics (exposed by `/metrics`):** `agent_requests_total{outcome}`, `agent_stop_reason_total`, `agent_tokens_total{kind}`, `agent_guardrail_flags_total`, `agent_tickets_total`, `agent_request_seconds` histogram.
- **Starter alerts (PromQL):**
  ```
  # error ratio > 5% for 10m
  sum(rate(agent_requests_total{outcome="error"}[5m])) / sum(rate(agent_requests_total[5m])) > 0.05
  # p95 latency > 30s
  histogram_quantile(0.95, sum(rate(agent_request_seconds_bucket[5m])) by (le)) > 30
  # token burn 2x baseline (compare to same hour last week)
  sum(rate(agent_tokens_total[1h])) > 2 * sum(rate(agent_tokens_total[1h] offset 1w))
  # loop caps hit
  sum(rate(agent_stop_reason_total{reason=~"max_turns|budget"}[15m])) > 0.02
  # model refusals
  sum(rate(agent_stop_reason_total{reason="refusal"}[15m])) > 0.01
  # claimed action without tool call (should be ~0) -> page
  sum(increase(agent_guardrail_flags_total{flag=~"claimed_.*"}[15m])) > 0
  ```
- **Traces:** OTel Collector (DaemonSet/sidecar) → Tempo/Jaeger/Datadog/Langfuse. Propagate `traceparent`; tag spans with prompt/model/tool-set versions.
- **Logs:** structured JSON to stdout → Loki/CloudWatch/Cloud Logging; redact PII at source.
- **Dashboards:** traffic & outcomes • latency percentiles • tokens/cost per run & per tenant • turns per run • tool error rates • guardrail/injection flags • escalation & approval queue age • eval canary score.
- **Synthetic canary:** a scheduled scripted conversation (fixed customer, known answer) every few minutes → alerts on quality regressions or provider outages.

---
## 9. Security hardening checklist (deployment-time)
**Network:** TLS everywhere • WAF + DDoS protection • request-size limits • NetworkPolicy default-deny • egress allow-list/proxy to the LLM endpoint only • `/metrics` internal-only • private endpoints/VPC peering to cloud-hosted model APIs if used.
**Identity:** workload identity (no static cloud keys) • least-privilege IAM per service • separate service accounts for agent vs tool services • short-lived tokens • per-tool credentials, never the user's broad token.
**Containers:** non-root • read-only FS • drop caps • seccomp • image scan/SBOM/signing • pinned base image • no secrets in layers.
**Application:** authN on every endpoint • identity from session • input validation (done) • per-key rate limits (done) • owner checks on conversations (done) • safe error messages (done) • audit log of every tool action.
**Data:** encryption at rest/in transit • PII redaction in traces (done) • retention + deletion across DB/cache/vector/logs • tenant isolation tests • provider data-handling terms (retention/zero-retention options, regions).
**Agent-specific:** approvals for irreversible actions • sandbox for code/browser tools • kill switch & per-tool flags • spend limits at the provider and gateway • red-team suite in CI (see file 10).
**Supply chain:** dependency pinning/audit • review MCP servers/plugins • signed releases.

---
## 10. CI/CD & release strategy
```
PR:      lint → unit + scripted-LLM + API tests (free) → [retrieval eval for RAG changes]
main:    build image (tag = git SHA) → scan/sign → deploy STAGING → smoke + synthetic canary
manual:  live evals (budget-capped key) for prompt/tool/model changes — block on regression
promote: manual approval → PROD rolling/canary 5% → watch error rate, latency, cost/run, guardrail flags, eval canary → ramp → auto-rollback on breach
```
- **Everything versioned:** code, prompts, tool schemas, policy thresholds, model id/effort. Put `app_version` and `prompt_version` on every trace.
- **Feature flags** per tool/agent/model route; **kill switch** that returns "handing off to a human".
- **Shadow mode** for risky new behaviours: run new agent alongside, don't act, compare.
- **Model upgrade runbook:** pin new id in staging → run eval suite + cost/latency comparison → fix prompts tuned for the old model → canary → ramp; keep rollback id.
- **DB migrations:** backward-compatible (expand → migrate → contract) so rolling deploys and rollbacks work.

---
## 11. Reliability & operations
- **SLOs (examples):** availability 99.9%; p95 first useful response < 8 s (streaming) / < 30 s (full); incorrect-action rate < 0.5%; resolution without escalation ≥ target; cost per resolution ≤ budget.
- **Failure handling:** provider 429/5xx → retry with backoff → fallback model/provider → safe handoff to human; DB down → read-only/degrade; tool down → agent explains and escalates.
- **Chaos / game days:** kill pods, inject 429s, block the provider, slow a tool, corrupt a retrieval result, send injection payloads.
- **Backups & DR:** Postgres PITR; index rebuild runbook; restore drills; documented RTO/RPO.
- **On-call runbooks:** (1) cost spike → check tokens/run, cache hit-rate, loop caps, abusive tenant → throttle/kill flag; (2) provider outage → switch route, enable degraded mode; (3) bad deploy → rollback, replay failing traces; (4) suspected injection/exfiltration → disable tools via flag, revoke tokens, preserve traces; (5) data-subject deletion → purge across stores.
- **Capacity & cost reviews** weekly: top-10 costliest runs, per-tenant spend, cache ratio, escalation reasons.

---
## 12. Cloud service mapping
| Need | AWS | GCP | Azure |
|---|---|---|---|
| Containers (simple) | App Runner / ECS Fargate | Cloud Run | Container Apps |
| Kubernetes | EKS | GKE | AKS |
| Queue / events | SQS / EventBridge | Pub/Sub / Cloud Tasks | Service Bus |
| Workflows (durable) | Step Functions | Workflows | Durable Functions |
| Postgres / Redis | RDS-Aurora / ElastiCache | Cloud SQL-AlloyDB / Memorystore | Azure DB for PostgreSQL / Cache for Redis |
| Vector search | OpenSearch / pgvector | Vertex Vector Search / pgvector | AI Search / pgvector |
| Secrets | Secrets Manager | Secret Manager | Key Vault |
| Object storage | S3 | GCS | Blob |
| Gateway / WAF | API Gateway + WAF / CloudFront | API Gateway + Cloud Armor | API Mgmt + Front Door/WAF |
| Observability | CloudWatch + X-Ray / Managed Prometheus & Grafana | Cloud Monitoring/Trace | Azure Monitor / App Insights |
| Hosted model access | Bedrock | Vertex AI | Foundry |
| IaC | Terraform/CDK | Terraform | Terraform/Bicep |
Use Infrastructure-as-Code (Terraform/Pulumi) for repeatable environments.

---
## 13. Honest gaps: what this repo does NOT yet do (so you can discuss them)
- State is in memory (conversations, ledger, tickets, rate limits) → must move to Postgres/Redis before >1 replica.
- No payments/ERP integration, no real approval UI/queue.
- No OpenTelemetry export, no streaming responses, no async job API.
- API-key auth is a minimal stand-in for OIDC/JWT.
- No multi-region, no IaC (Terraform), no load test, no canary controller.
- Image build, Kubernetes apply and CI pipeline are **unverified here**.

## 14. Go-live checklist
- [ ] State externalised; migrations tested; backups + restore drill done
- [ ] Secrets in a manager; provider spend limits set; keys rotated per env
- [ ] AuthN/Z on every endpoint; tenant isolation tested
- [ ] Rate limits + per-tenant budgets + loop caps verified
- [ ] Policy/approval flows tested end-to-end (incl. rejection)
- [ ] Eval suite green (incl. injection, cross-tenant, negative cases); thresholds in CI
- [ ] Dashboards, alerts, synthetic canary, on-call runbooks ready
- [ ] Load test with realistic traces; provider-429 and outage behaviour verified
- [ ] Fallback model/human handoff path tested; kill switch tested
- [ ] PII handling, retention, deletion process; vendor terms reviewed; legal sign-off if regulated
- [ ] Canary plan + rollback rehearsed; owner and on-call named

## 15. Self-check / interview questions
1. Why is CPU a poor autoscaling signal for agents? What would you scale on?
2. Walk through deploying this agent from laptop to production on Kubernetes.
3. What must change before running more than one replica?
4. How do you do a zero-downtime rollout when requests last 60 s?
5. Design the async architecture for a 30-minute research agent that must survive crashes.
6. How do you roll out a new model version safely?
7. The LLM provider has a 40-minute outage. What happens in your system?
8. How would you deploy the RAG index update without downtime and with rollback?
9. Which controls make a compromised model low-impact at the infrastructure level?
10. How do you keep cost bounded in production?
