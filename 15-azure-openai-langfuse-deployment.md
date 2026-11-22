# 15 · Azure OpenAI + Azure Deployment + Langfuse (the concrete stack)

This file replaces the "generic" choices in file 14 with your stack:
**LLM = Azure OpenAI · Hosting = Azure Container Apps (AKS as alternative) · Observability = Langfuse (+ Azure Monitor for infrastructure).**

Code: `project/src/supportops/{llm_azure,llm_factory,observer,state,api}.py` · `project/infra/{main.bicep,deploy.ps1,deploy.sh}` · `.github/workflows/ci.yml` · `project2-research-agent/src/research/{llm_azure,langfuse_tracer}.py`

> **Verification status (be honest in interviews):**
> ✅ Verified here: adapter translation + full agent runs against a fake Azure client (tool calls, errors, content filter, invalid JSON args, multimodal parts); Langfuse spans captured with an in-memory OpenTelemetry exporter (nesting, one trace for parallel sub-agents, user/session, usage, error level, PII masked); Redis state with fakeredis; feedback endpoint; Bicep **compiles** (`az bicep build`); deploy scripts and workflow **parse**.
> ❌ NOT verified: real Azure OpenAI calls, real Langfuse ingestion, `az deployment` against a subscription, image build (no Docker daemon), Container Apps runtime behaviour, CI. Run `what-if` first and expect to adjust model/region/quota values.

---
## 1. Target architecture

```
                         Internet
                            │ HTTPS
              (optional) Azure Front Door + WAF   ← custom domain, DDoS, geo rules
                            │
        ┌───────────────────▼────────────────────────────────────────────────────────┐
        │ Azure Container Apps environment  (Log Analytics for platform logs)         │
        │   supportops-agent  (2..20 replicas, scale on concurrent requests)          │
        │     /v1/chat  /v1/feedback  /healthz  /readyz  /metrics                     │
        │     user-assigned MANAGED IDENTITY  ───────────────┐                        │
        └──────┬──────────────┬───────────────┬──────────────┼────────────────────────┘
               │              │               │              │ (Entra ID tokens; no keys)
               ▼              ▼               ▼              ▼
        Azure OpenAI      Redis (shared    Key Vault      Azure Container
        (chat deployment, state: convs,    (API keys,     Registry (image pull,
         Entra-only auth) rate limits)     Langfuse keys)  AcrPull)
               │
               └── content filters / quotas (TPM)               Business systems: orders/payments APIs, Postgres (ledger, tickets)

        Every request ──► Langfuse (traces, generations, tools, usage, scores)   [Cloud, or self-hosted on AKS]
        CI/CD: GitHub Actions ─OIDC─► az acr build ─► az containerapp update (rolling revision)
```

**Why Container Apps first:** managed Kubernetes-without-the-ops (KEDA scaling, revisions, ingress, managed identity, Key Vault secret refs) — the right default for one agent service. Move to **AKS** when you need many services, custom networking/policies, GPU, or a platform team (the `k8s/` manifests apply with the changes in §8).

---
## 2. Azure OpenAI — what a senior engineer must know

### Resources & vocabulary
- **Azure OpenAI resource (account)** → contains **deployments**. You call a *deployment name* (not the model name). Keep the deployment name stable (`support-agent`) and change the underlying model version behind it.
- **Microsoft Foundry / Azure AI Foundry** is the umbrella portal/project model; Azure OpenAI models are also reachable there. Check current naming/endpoints in docs — it changes.
- **Deployment types** (names evolve; verify): *Global Standard* (best default availability/quota, global routing), *Data Zone Standard* (stay within US/EU data zone), *Standard/regional* (single-region), *Provisioned (PTU)* (reserved throughput, predictable latency — for steady high volume), *Batch* (async, discounted).
- **Quota = TPM (tokens/min) per region per model per subscription**, enforced as RPM too. Request increases early; spread across deployments/regions.
- **Model versions & retirement:** models are retired on a schedule. Set `versionUpgradeOption: NoAutoUpgrade` (done in Bicep), track retirement dates, upgrade **deliberately after running evals** (CI live-evals job).
- **API versions:** data-plane `api-version` (GA, e.g. `2024-10-21`) vs the newer "v1" API surface. The code reads `AZURE_OPENAI_API_VERSION`. Pin it; test before bumping.

### Authentication (do this, not API keys)
- **Entra ID + managed identity:** `DefaultAzureCredential` → bearer token for scope `https://cognitiveservices.azure.com/.default`. Role: **Cognitive Services OpenAI User** (inference only). The Bicep sets `disableLocalAuth: true` so *keys can't be used at all* → nothing to leak/rotate.
- Local dev: `az login` works with the same code (`DefaultAzureCredential`), or set `AZURE_OPENAI_API_KEY` for quick tests.
- With a *user-assigned* identity, set `AZURE_CLIENT_ID` (Bicep does).

### Networking & data protection
- Public endpoint + identity is acceptable for many workloads; regulated ones use **private endpoints**, VNet-integrated Container Apps environment, `publicNetworkAccess: Disabled`, private DNS zones.
- **Data handling:** by default prompts/completions are processed under Azure terms (not used to train base models); some abuse-monitoring retention exists unless you obtain approval for modified abuse monitoring / zero data retention. **Verify current Microsoft terms for your compliance needs** and region/data-zone residency.
- **Content filters:** on by default (hate, sexual, violence, self-harm; plus jailbreak / protected-material categories configurable). A blocked *prompt* returns HTTP 400 `code=content_filter`; a blocked *completion* returns `finish_reason="content_filter"`. The adapter maps **both to `refusal`** → agent returns the safe fallback and escalates (tested). Tune filters per deployment; track false positives. **Prompt Shields** (Azure AI Content Safety) detect direct/indirect injection — a useful extra layer, *not* a replacement for tool-layer controls (file 10).

### Chat Completions function-calling vs the Messages-style dialect (why the adapter exists)
| Concern | Dialect used by `agent.py` | Azure OpenAI Chat Completions | Adapter does |
|---|---|---|---|
| System prompt | `system=` param | first message `role: system` | prepends |
| Tool schema | `input_schema` | `tools:[{type:function,function:{parameters}}]` | wraps; adds `strict:true` |
| Model wants a tool | content block `tool_use` | `message.tool_calls[]` (arguments = JSON **string**) | parses; invalid JSON → readable tool error |
| Tool result | user message with `tool_result` blocks | separate `role: tool` messages with `tool_call_id`, **must directly follow** the assistant `tool_calls` message | splits & orders; `is_error` → `ERROR:` prefix |
| Stop reason | `end_turn/tool_use/max_tokens/refusal` | `finish_reason: stop/tool_calls/length/content_filter` | maps |
| Usage | `input_tokens/output_tokens` | `prompt_tokens/completion_tokens` (+ `cached_tokens`) | maps |
| Output limit param | `max_tokens` | `max_completion_tokens` (required for reasoning models) | uses new name |
| Images | `image` blocks | `image_url` content parts (data URL) | converts |
**Limits of the adapter:** PDF `document` blocks (project 2 `pdf_block`) are *not* supported by Chat Completions — it raises a clear error. Extract text first (Azure AI Document Intelligence / pypdf) or rasterise pages to images. Anthropic-only features (thinking blocks, server-side fallbacks, `cache_control`) don't apply.
**Lesson:** isolate the provider behind one `create()` method + translation layer; agent logic, policy, guardrails, tests stay unchanged. Same trick lets you A/B providers or fail over.

### Provider-specific features worth using
- **Strict function calling / structured outputs** (`strict: true`, JSON-schema response format): guarantees arguments match the schema (requires `additionalProperties:false` and all properties `required` — our tools comply). Set `AZURE_OPENAI_STRICT_TOOLS=0` if a deployment rejects it.
- **Automatic prompt caching:** repeated prompt prefixes (≥ ~1,024 tokens, check docs) are cached automatically; see `usage.prompt_tokens_details.cached_tokens`. So: stable system prompt + tool list **first**, volatile content last (same rule as everywhere).
- **Reasoning models (o-series / newer):** use `max_completion_tokens`, `reasoning_effort` (`AZURE_OPENAI_REASONING_EFFORT`), no temperature/top_p; slower and costlier per call — use for hard routes only.
- **Parallel tool calls** are on by default: the agent executes all and returns all results (ordering handled).
- **429 handling:** SDK retries with backoff and honours `Retry-After` (`max_retries=3`). Beyond that: gateway-level load balancing across deployments/regions, queueing, and graceful degradation.

### Capacity planning (TPM)
`TPM needed ≈ peak requests/min × turns/request × (avg input + output tokens per turn)`. Agents multiply: 100 req/min × 3 turns × 2,500 tokens ≈ 750K TPM. Prompt-cached tokens still count against TPM for rate-limit purposes in some configurations — verify. Load-test with real multi-turn traces; request quota before launch; consider PTU for steady load.

### Azure API Management as an "AI gateway" (recommended at scale)
Put **APIM** in front of Azure OpenAI for: per-client **token-rate limiting** and quotas, **load balancing/failover** across multiple deployments or regions (retry on 429), central logging/metrics of token usage, optional semantic caching, key-less backend auth with APIM's managed identity. The app then calls the APIM endpoint instead of Azure OpenAI directly (change `AZURE_OPENAI_ENDPOINT`; keep scope/roles consistent per your APIM policy). Check current APIM GenAI-gateway policy names in docs.

---
## 3. Langfuse — what it gives you and how it's wired in

### What Langfuse is
Open-source LLM engineering platform: **traces** (tree of observations), **sessions** (group a conversation), **users**, **scores** (numeric/boolean/categorical quality signals), **datasets & experiments** (offline evals), **LLM-as-judge evaluators**, **prompt management**, **cost & latency analytics**, dashboards. Python SDK ≥3 is built on **OpenTelemetry**.

### How a request appears (what `observer.py` produces)
```
Trace "support-agent"   user=hash(customer)  session=conversation_id  tags=[env]  release=git-sha
└─ agent  support-agent             input=user message → output=final answer   metadata: model, provider, prompt_version, stop_reason, turns, flags
   ├─ generation llm               model=gpt-4o  usage={input,output}  input=messages  output=content/tool calls
   ├─ tool lookup_order            input=args → output=result            (level=ERROR if the tool failed)
   ├─ generation llm
   ├─ tool issue_refund
   └─ generation llm
Scores on the trace: guardrail_violation (0/1) · escalated (0/1) · tool_error_rate (0..1) · user_feedback (-1/0/1 via /v1/feedback)
```
Multi-agent (project 2): `run → delegate(agent) → researcher:llm_call (generation) / tool` with the same trace id for parallel sub-agents.

### Design decisions & gotchas (good interview material)
1. **PII masking inside the SDK** (`mask=` callback → `redact_deep`): data is scrubbed *before it leaves the process*. Tested: emails/card numbers never appear in exported spans.
2. **Hashed user id** (salted SHA-256, `LANGFUSE_USER_HASH_SALT` from Key Vault) — per-user analytics without storing identities.
3. **Session = conversation id** → whole chats viewable together; the API returns `trace_id` so the UI can attach feedback.
4. **Explicit parent observations, not thread-locals.** OpenTelemetry's "current span" is a context variable that does **not** propagate into `ThreadPoolExecutor` workers → naive instrumentation creates *orphan traces* for parallel sub-agents. We call `parent.start_as_current_observation(...)` explicitly (test proves one trace, correct parents).
5. **`release` = git sha, `environment` = dev/staging/prod, `prompt_version`** in metadata → compare quality/cost across deployments and prompt changes.
6. **Flush on shutdown** (`lifespan` calls `observer.flush()`): events are batched asynchronously; without flush you lose the last events on SIGTERM / scale-in. Container Apps `terminationGracePeriodSeconds: 90` gives time.
7. **Cost tracking needs a recognisable model name.** Azure calls use the *deployment* name (`support-agent`), which Langfuse can't price. We set `TRACE_MODEL_NAME=gpt-4o` so generations carry the base model name (tested) — or define a custom model/price in Langfuse. Verify the resulting cost against the Azure bill.
8. **Sampling:** `LANGFUSE_SAMPLE_RATE` (e.g. 0.1) for very high volume; keep 100% of errors/escalations if you add custom sampling.
9. **Fail-open observability:** Langfuse down must never break chats — the SDK exports in the background; the observer is optional (`NullObserver` when no keys).
10. **Test isolation gotcha:** the SDK keeps one client per public key; tests use a unique key each so exporters don't get shared/starved. (A vacuous-pass PII test taught me this — assert spans exist.)

### Using Langfuse day-to-day
- **Debug:** filter traces by `session`, user hash, tag, release, `escalated=1`, `guardrail_violation=1`, error level; open the tree to the first wrong decision; copy the exact generation input to reproduce.
- **Quality loop:** collect low `user_feedback` and escalated traces → add to a **dataset** → run **experiments** against new prompt/model versions (also wired to `evals/run_evals.py`, which sends traces with `APP_ENV=ci`) → promote only if scores hold.
- **LLM-as-judge evaluators** (configured in Langfuse) on sampled production traces: faithfulness, tone, policy-compliance; calibrate against human labels first.
- **Cost/latency dashboards** by model, release, user, session; spot context bloat (input tokens/turn rising) and cache effectiveness.
- **Alerts:** Langfuse is analytics-oriented; for paging use Azure Monitor/Prometheus on infrastructure and metrics (`agent_*` counters) and periodically query Langfuse's API for score regressions. Check current Langfuse alerting features before promising any.

### Cloud vs self-hosted (Azure)
| | **Langfuse Cloud** | **Self-hosted on Azure** |
|---|---|---|
| Effort | Minutes; set 3 env vars | Real platform work |
| Data location | Their region (EU/US) — traces leave your tenant (we mask PII, but check policy) | Stays in your tenant/VNet |
| Components | — | Langfuse **web** + **worker** containers, **Postgres** (Azure Database for PostgreSQL Flexible Server), **ClickHouse** (self-managed on AKS or ClickHouse Cloud), **Redis** (Azure Managed Redis/Cache), **blob storage** (Azure Blob; S3-compatible config—verify current Azure Blob support in docs) |
| Deploy | — | Official **Helm chart on AKS** (recommended), or containers on Container Apps/VMs (docker-compose is for dev only) |
| Ops | none | upgrades, backups, ClickHouse sizing, retention, auth (SSO/Entra via OIDC), TLS, network isolation |
**Recommendation:** start on Cloud with masking; self-host if data-residency/compliance requires it, and size ClickHouse for retention × trace volume.

---
## 4. Deploying to Azure — step by step

### Prerequisites
`az login` → `az account set -s <sub>` · Azure OpenAI access approved for the subscription · quota for your model/region · Langfuse project keys · (for >1 replica) a Redis URL.

### Run it
```powershell
cd project\infra
$env:API_KEYS='{"prod-key-abc":"C-1"}'                   # replace with Entra ID auth for real users (see §6)
$env:LANGFUSE_PUBLIC_KEY='pk-lf-...'; $env:LANGFUSE_SECRET_KEY='sk-lf-...'; $env:LANGFUSE_HOST='https://cloud.langfuse.com'
$env:REDIS_URL='rediss://:<key>@<host>:6380/0'           # omit => app is forced to exactly 1 replica (in-memory state)
./deploy.ps1 -ResourceGroup rg-supportops-prod -Location swedencentral
```
What happens (`deploy.ps1` / `deploy.sh`):
1. **Phase 1** `main.bicep` (`deployApp=false`) → managed identity, Log Analytics, ACR, Key Vault (+secrets), Azure OpenAI account + model deployment (`GlobalStandard`, `NoAutoUpgrade`, **local auth disabled**), RBAC (AcrPull, Key Vault Secrets User, Cognitive Services OpenAI User), Container Apps environment. A `what-if` is shown first.
2. `az acr build` builds the image **in Azure** (no local Docker needed), tag = git sha.
3. **Phase 2** (`deployApp=true`, `image=…`) → Container App with HTTPS ingress, probes (`/healthz`, `/readyz`), env vars, Key Vault secret references via identity, HTTP-concurrency autoscaling.
4. Smoke test `/readyz`.

Test it:
```bash
curl -X POST https://<fqdn>/v1/chat -H "x-api-key: prod-key-abc" -H "content-type: application/json" \
     -d '{"message":"Refund ORD-1001, the cable broke"}'
# -> {"answer": "...", "conversation_id": "...", "trace_id": "...", ...}  then open the trace in Langfuse
curl -X POST https://<fqdn>/v1/feedback -H "x-api-key: prod-key-abc" -H "content-type: application/json" \
     -d '{"trace_id":"<trace_id>","rating":1,"comment":"helpful"}'
```
**Known operational wrinkles:** (a) RBAC role assignments can take minutes to propagate — if the first phase-2 deploy fails on Key Vault/ACR access, re-run it. (b) Key Vault has purge protection: deleting + redeploying with the same name needs care. (c) Model/version/SKU availability varies by region — adjust the `openAI*` parameters. (d) The first run may need quota requests.

### Image/Container notes
Dockerfile = non-root, read-only-friendly, healthcheck. `requirements-prod.txt` now holds `openai`, `azure-identity`, `langfuse`, `redis`, FastAPI stack (Anthropic SDK optional).

---
## 5. State, scaling & networking on Azure

| Topic | What to do |
|---|---|
| **Shared state** | Set `REDIS_URL` → conversations (TTL), trace ownership, and rate limits are shared across replicas (tested with fakeredis). Use **Azure Managed Redis** or **Azure Cache for Redis** (check Microsoft's current recommendation/retirement notices), TLS port 6380, store the URL in Key Vault. Without Redis the Bicep **forces 1 replica** — a deliberate safety. |
| **Business state** | Refund ledger/tickets/approvals still live in memory in the demo → move to **Azure Database for PostgreSQL – Flexible Server** (idempotency key = unique constraint) + payments API; approvals via ticketing/Logic Apps/Teams. |
| **Autoscaling** | `http` rule: scale out when concurrent requests per replica > 10 (agent calls are slow & I/O-bound). KEDA scalers (Service Bus/Storage queue) for async job workers. Keep `minReplicas ≥ 2` for availability. **Provider quota (TPM) is the real ceiling** — more replicas don't create capacity. |
| **Revisions** | `Single` mode = rolling update; new revision must pass readiness before traffic moves; old one keeps serving otherwise. For canary: `Multiple` mode + traffic weights (e.g. 95/5), then promote. Rollback = point traffic to the previous revision. |
| **Ingress/edge** | Built-in HTTPS ingress; add **Front Door + WAF** for custom domain, WAF rules, rate limiting, geo filters; restrict direct access to the app. |
| **Private networking** | VNet-integrated environment, **private endpoints** for Azure OpenAI, Key Vault, ACR, Redis, Postgres; disable public access; private DNS zones; egress via NAT/Firewall allow-listing Langfuse host. |
| **Metrics** | `/metrics` (Prometheus) is exposed but Container Apps doesn't scrape it by default. Options: OpenTelemetry Collector → Azure Monitor; use **Azure Managed Prometheus/Grafana on AKS**; or rely on Langfuse + Log Analytics + built-in platform metrics (requests, replicas, CPU/memory). Keep `/metrics` internal-only. |
| **Logs** | Console logs → Log Analytics. Example KQL: `ContainerAppConsoleLogs_CL \| where ContainerAppName_s == "supportops-agent" \| where Log_s contains "agent run failed" \| order by TimeGenerated desc` (table/column names vary by plan—check). |

---
## 6. Security on Azure (checklist)
- **Identity everywhere:** user-assigned managed identity; **no** Azure OpenAI keys (`disableLocalAuth`), **no** ACR admin; Key Vault with RBAC + purge protection.
- **Least privilege:** the app identity has only *OpenAI User*, *AcrPull*, *Key Vault Secrets User*. Separate identities for separate services/tools.
- **User authentication:** replace the demo `x-api-key` with **Entra ID (Easy Auth / JWT validation)** or your IdP; derive `customer_id` from verified token claims — still *never* from the body.
- **Network:** HTTPS only, WAF, private endpoints, egress allow-list, `/metrics` internal.
- **LLM layer:** content filters tuned; **Prompt Shields**/Content Safety for injection signals; policy-in-code and tool authZ remain the real defence (file 10).
- **Governance:** **Azure Policy** (deny public network on AI resources, require tags/CMK), **Defender for Cloud** (containers, Key Vault, AI workload protection), Activity Log + diagnostic settings to Log Analytics, resource locks on Key Vault/Azure OpenAI.
- **Data:** PII masked before Langfuse (tested) and in local traces; retention policies in Redis (TTL), Langfuse, Log Analytics; deletion process across stores.
- **Supply chain:** image scanning (Defender / Trivy), pinned base image, signed images, OIDC for CI (no stored cloud secrets).
- **Cost safety:** Azure **Budgets + alerts**, quota (TPM) as a natural cap, per-key rate limits, loop/turn/token caps (in code), APIM token limits.

---
## 7. CI/CD (`.github/workflows/ci.yml`)
`PR`: pytest (46 + 19 tests, free) + `az bicep build` → `main`: **build in ACR** (tag = sha) → **staging** deploy + smoke → **production** behind a manual approval (GitHub environment reviewers) → smoke → watch Langfuse/Azure Monitor. **OIDC** `azure/login` (federated credential; no secrets). Optional **live evals** job (manual dispatch) runs `evals/run_evals.py --runs 3` against Azure OpenAI using the runner's `az login` identity, tracing into a separate Langfuse *ci* project. Use `deployment slots`-style canary via revision traffic weights when you have traffic.
Model upgrade runbook: new deployment (or new version behind same name in staging) → live evals + Langfuse experiment compare (quality, tokens, latency, cost) → canary → ramp → keep rollback deployment.

---
## 8. AKS alternative (when to choose it)
Use the manifests in `project/k8s/` with these Azure-specific changes:
- **Workload Identity** (OIDC issuer + federated credential) instead of managed identity env: annotate the ServiceAccount (`azure.workload.identity/client-id`), label pods `azure.workload.identity/use: "true"`, and set `automountServiceAccountToken: true` for that SA (the sample disables it).
- **Secrets:** Azure Key Vault **Secrets Store CSI driver** (or External Secrets) instead of `secret.example.yaml`.
- **Ingress:** Application Gateway for Containers / ingress-nginx + cert-manager; keep NetworkPolicy.
- **Scale:** KEDA (HTTP/Prometheus/Service Bus) + cluster autoscaler; **Managed Prometheus + Managed Grafana** scrape `/metrics`.
- **Self-hosting Langfuse** fits naturally here via Helm.

---
## 9. Runbooks (Azure-specific)
| Incident | Response |
|---|---|
| **429 / TPM exhausted** | Check Azure OpenAI metrics (throttled requests) → raise quota / add second deployment (another region) behind APIM load balancer → temporarily lower `max_turns`, enable lighter model route → queue non-urgent work. |
| **Regional outage / elevated 5xx** | Fail over to secondary deployment/region (APIM backend pool or config switch); `/readyz` stays up, chats degrade to "handoff to human" if provider unavailable. |
| **Content-filter false positives** | Find traces with `refusal` stop reason in Langfuse; review categories; adjust filter config (with security approval); add regression cases. |
| **Cost spike** | Langfuse: tokens/trace by release & user → context bloat? loop caps hit? abusive user? → rate-limit/kill key; check cache hit-rate (`cached_tokens`); roll back release. |
| **Quality regression after deploy** | Langfuse: compare scores by `release`; open worst traces; roll back revision; add failing cases to dataset. |
| **Langfuse outage** | App keeps serving (fail-open); events dropped after buffer limits — acceptable; rely on Azure Monitor + local JSONL/trace logs for forensics. |
| **Model retirement notice** | Create new deployment with replacement model, run evals + Langfuse experiment, canary, switch deployment mapping before the retirement date. |
| **Credential leak suspicion** | Rotate Key Vault secrets (API keys, Langfuse keys), revoke Entra app credentials, review sign-in & Activity logs, restart revisions. |

---
## 10. Interview questions for this stack
1. Why use managed identity + `disableLocalAuth` for Azure OpenAI? What role does the app need?
2. A deployment name vs a model name — why does it matter operationally (and for Langfuse cost)?
3. Explain the differences between Chat Completions tool calling and the Messages-style dialect; how did you keep the agent provider-agnostic?
4. What does `finish_reason=content_filter` mean and how does your agent respond? What about a 400 from the prompt filter?
5. How do you plan TPM quota for an agent that makes 3–5 model calls per user request?
6. Why can't you scale this app to many replicas with the in-memory state? What did you change?
7. Parallel sub-agents appear as separate traces in your observability tool. Why, and how did you fix it?
8. How do you prevent PII from reaching Langfuse? How do you verify?
9. Cloud vs self-hosted Langfuse on Azure — components and trade-offs?
10. Walk me through a zero-downtime deploy + rollback on Container Apps. How would you do a canary?
11. How do you upgrade the underlying model version safely?
12. What would you put in APIM in front of Azure OpenAI?
13. Where does this design still *not* meet production standards?  *(business-state in memory, API-key auth, no private networking, unverified in a live subscription, no load test)*
