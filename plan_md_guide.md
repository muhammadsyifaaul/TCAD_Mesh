# PLAN.md — Tiered Work Plan for TCAD Mesh

General rules are in `AGENTS.md`. This document outlines the tiers, tasks, gates, and ready-to-use LLM system prompts. 
**EXECUTE SEQUENTIALLY. Every tier ends at a Gate: All criteria MUST pass + Human Approval required before proceeding.**

Today is Saturday, November 7, 2026. Submission Deadline: **November 15, 2026, 23:59 WIB**.

---

## Schedule and Decision Points

| Date | Tier | Notes |
| --- | --- | --- |
| Nov 7 | Tier 0 (Foundation & Contracts) | Contracts frozen today |
| Nov 7–8 | Tier 1 (Mode 1 Core) | Parallel directory execution allowed post-Tier 0 |
| Nov 8–9 | Tier 2 (Control-API, Events, Quar.) | |
| Nov 9–10 | Tier 3 (Dashboard, Simulator) | |
| Nov 10–11 | Tier 4 (Hardening, E2E, Metrics) | **GO/NO-GO Decision for Mode 2 by Nov 11 Noon** |
| Nov 11–12 | Tier 5 (Minimal Mode 2, **OPTIONAL**) | Skip entirely if Tier 4 is not flawlessly completed |
| Nov 12–14 | Tier 6 (Submission Assets) | Video scripts, architecture docs, README |
| Nov 15 | Buffer | Final submit **before evening** |

**Parallel Mode Constraints:**
After Tier 0, agents can work concurrently strictly within their assigned directories:
- **Agent-Gateway:** `gateway/`
- **Agent-Backend:** `target-app/`, `honeypot/`, `control-api/`
- **Agent-Frontend:** `dashboard/`
- **Agent-Sim:** `attacker-sim/`, `bench/`

---

## Tier 0 — Foundation and Contracts (Target: Today)

**Goal:** Establish a working repo skeleton and freeze inter-service contracts.

**Tasks:**
1. Scaffold repo structure (`AGENTS.md` Sec 6), `.gitignore`, `.env.example`, `Makefile`, `ATTRIBUTION.md`.
2. Write `docker-compose.yml` with healthchecks. Expose ONLY `gateway` and `dashboard`.
3. Scaffold services: Create minimal Dockerfiles and `/health` endpoints.
4. Define `contracts/openapi.yaml` for `target-app`.
5. Define `contracts/events.schema.json` and `contracts/control-api.md`.

**Gate T0:**
- [ ] `docker compose up --build` results in all services displaying `healthy`.
- [ ] `make up` and `make down` work flawlessly.
- [ ] Contracts are validated and frozen.

**Agent Prompt (Tier 0):**
```text
SYSTEM PROMPT: You are the Lead Architect Agent. Read AGENTS.md and PLAN.md thoroughly.
TASK: Execute ONLY Tier 0. Scaffold the repository structure, docker-compose (with healthchecks), baseline service folders (implementing ONLY /health endpoints), and the `contracts/` directory strictly following AGENTS.md. DO NOT implement security logic yet. 
VERIFICATION: Run `docker compose up --build`, prove all services are healthy. 
DELIVERABLE: End with a Tier 0 Report as formatted in AGENTS.md Section 8.
```

---

## Tier 1 — Mode 1 Core: Gateway, Target-App, Honeypot

**Goal:** Detection and routing pipeline works End-to-End locally.

**Tasks by Agent:**
- **Agent-Backend (`target-app`):** Implement `contracts/openapi.yaml` with realistic mock data. Unknown paths MUST return 404.
- **Agent-Backend (`honeypot`):** Implement identical schema. Data MUST be deterministic per identity. NO LEAKY WORDS. Inject latency jitter.
- **Agent-Gateway (`gateway`):** Implement pipeline from `AGENTS.md` 4.3 using Go stdlib. Async structured JSON logging. Configure via ENV.

**Gate T1:**
- [ ] Legit request to gateway → target-app response, 0 events.
- [ ] `GET /admin` → honeypot response + `CANARY_HIT` event. Subsequent requests from same identity route directly to honeypot.
- [ ] 7 requests to random 404 paths within 10s → `ENUM_DETECTED` + Tarpit active. When semaphore full → 429.
- [ ] Honeypot and target-app responses are indistinguishable via HTTP Headers.
- [ ] Unit tests pass.

**Agent-Gateway Prompt:**
```text
SYSTEM PROMPT: You are the Gateway Agent (Expert Go Developer). Read AGENTS.md and PLAN.md. 
TASK: Execute Tier 1 for `gateway/` ONLY. Implement the detection pipeline (AGENTS.md 4.3) using Go stdlib. STRICTLY adhere to the Design Anti-Patterns (Sec 5). Write table-driven unit tests. 
VERIFICATION: Run `go test ./... -race` and provide curl logs proving Gate T1 criteria. 
DELIVERABLE: End with a Tier 1 (Gateway) Report.
```

**Agent-Backend Prompt:**
```text
SYSTEM PROMPT: You are the Backend Agent (Expert Python/FastAPI Developer). Read AGENTS.md and PLAN.md. 
TASK: Execute Tier 1 for `target-app/` and `honeypot/` ONLY. Implement openapi.yaml in target-app. Build the honeypot with exact schema parity, deterministic fake data generation per identity, and zero metadata leaks. Write pytests proving determinism and schema parity. 
DELIVERABLE: End with a Tier 1 (Backend) Report.
```

---

## Tier 2 — Control-API, Events, Managed Quarantine

**Goal:** All events are durably recorded, queryable, and operators can manage quarantines.

**Tasks:**
1. `control-api`: Implement endpoints (`AGENTS.md` 4.2) using SQLite. Secure writes with `X-Internal-Key`.
2. `gateway`: Wire async event dispatching to control-api. Sync quarantine state (TTL-based). Poll honeytokens every 2s. Attribute `HONEYTOKEN_REUSED` to original session.
3. `honeypot`: Post generated honeytokens to control-api (`HONEYTOKEN_ISSUED`).
4. Operator `release` via control-api propagates to gateway within ≤ 2 seconds.

**Gate T2:**
- [ ] All Tier 1 scenario events appear in `GET /events` with valid schemas.
- [ ] Killing `control-api` container does NOT crash or slow down `gateway`.
- [ ] Using a token from honeypot payload in a new request triggers `HONEYTOKEN_REUSED`.
- [ ] Releasing quarantine works.

**Agent Prompt:**
```text
SYSTEM PROMPT: You are the Backend Integration Agent. Read AGENTS.md and PLAN.md. 
TASK: Execute Tier 2. Build full control-api (SQLite). Wire gateway event dispatching asynchronously (must survive control-api downtime). Implement honeytoken registry & detection logic. 
VERIFICATION: Prove all Gate T2 criteria. 
DELIVERABLE: End with a Tier 2 Report.
```

---

## Tier 3 — Dashboard, Simulator, One-Click Demo

**Goal:** Judges can open the UI, click one button, and watch the system defend itself.

**Tasks:**
1. `attacker-sim`: Write Python httpx scenarios: `scan`, `legit`, `full`. MUST implement allowlist. Output JSON results.
2. `control-api`: Wire `/sim/run` to trigger simulator container.
3. `dashboard`: React + Vite (Static build served by control-api). Implement Stats Panel, Event Timeline, Quarantine Table, Honeytoken Panel, and "Run Simulation" buttons.

**Gate T3:**
- [ ] Clean repo `make up` → open `http://localhost:8080` → Click "Full Simulation" → Events populate real-time.
- [ ] `legit` scenario generates 0 alerts.
- [ ] Simulator rejects non-allowlisted targets.

**Agent-Sim Prompt:**
```text
SYSTEM PROMPT: You are the Security Simulator Agent. Read AGENTS.md and PLAN.md. 
TASK: Execute Tier 3 for `attacker-sim/`. Create scan, legit, and full scenarios. Enforce strict target allowlisting. 
DELIVERABLE: End with a Tier 3 (Sim) Report.
```

**Agent-Frontend Prompt:**
```text
SYSTEM PROMPT: You are the Frontend Agent. Read AGENTS.md and PLAN.md. 
TASK: Execute Tier 3 for `dashboard/`. Build React+Vite dashboard consuming control-api. Build static files into `dashboard/dist`. 
DELIVERABLE: End with a Tier 3 (Frontend) Report.
```

---

## Tier 4 — Hardening, E2E Tests, and Mode 1 Metrics

**Goal:** Rock-solid reliability. All documentation metrics are backed by real benchmarking data.

**Tasks:**
1. **Metrics Harness (`bench/`):** Write scripts to measure M1, M2, M3, M4, M8, and False Positives. Save output to `results/SUMMARY.md`.
2. **Hardening:** Gateway timeouts, body size limits, graceful shutdown, goroutine leak checks under load.
3. **E2E Scripts:** `scripts/e2e.sh` combining Gate T1-T3 tests.
4. **Clean Room Test:** `scripts/clean-room-test.sh` to simulate judge environment.

**Gate T4:**
- [ ] `make test`, `make e2e`, `make bench` all pass.
- [ ] `results/SUMMARY.md` populated with REAL numbers.
- [ ] Clean room script executes flawlessly.
- [ ] **GO/NO-GO Decision logged by human.**

**Agent Prompt:**
```text
SYSTEM PROMPT: You are the QA & Performance Agent. Read AGENTS.md and PLAN.md. 
TASK: Execute Tier 4. Build benchmark harness in `bench/`, harden gateway limits, and write e2e scripts. DO NOT fabricate metrics—run the benchmarks and save output to `results/`. 
DELIVERABLE: End with a Tier 4 Report.
```

---

## Tier 5 — Minimal Mode 2 (OPTIONAL, ONLY IF GO)

**Goal:** Demonstrate time-based MTD routing and anti-replay concisely without breaking Mode 1.

**Tasks:** (Spec in `AGENTS.md` 4.5)
1. Hide behind `MODE2_ENABLED=false` flag. Mode 1 behavior MUST NOT regress when false.
2. Implement O(1) HMAC route derivation, ±1 interval Grace Window, tripwire classification, nonce caching in Redis.
3. `attacker-sim`: Add legit client SDK logic, real `replay` attack scenario, and test clock drift (±45s).
4. Extract M6 and M7 metrics to `results/`.

**Gate T5:**
- [ ] With flag `false`: All Tier 1-4 tests pass (Zero regressions).
- [ ] With flag `true`: Legit clients succeed >99.9% under ±45s clock drift. In-window replays rejected. Out-of-window valid MACs trigger Tripwire.
- [ ] Constant-time compare used strictly.

**Agent Prompt:**
```text
SYSTEM PROMPT: You are the Advanced Security Agent. Read AGENTS.md and PLAN.md. 
TASK: Execute Tier 5 (Mode 2) protected by `MODE2_ENABLED` flag. Implement MTD, Grace Window, and Nonce validation (AGENTS.md 4.5). MUST NOT break Mode 1. 
VERIFICATION: Rerun all Tier 1-4 tests with flag false. Run Tier 5 tests with flag true. 
DELIVERABLE: End with a Tier 5 Report.
```

---

## Tier 6 — Submission Assets and Documentation

**Goal:** Polished, honest, and comprehensive submission materials.

**Tasks (Agent):**
1. Write `README.md` (Elevator pitch, 1-command quickstart, repo map).
2. Write `docs/architecture.md` (Mermaid diagrams, threat model, pipeline flow).
3. Draft `docs/demo-script.md` and `docs/video-script.md`.
4. Draft `docs/slide-outline.md`.
5. Finalize `ATTRIBUTION.md`.

**Gate T6:**
- [ ] NO fabricated claims. All numbers match `results/SUMMARY.md`.
- [ ] Repo builds cleanly from `README.md` instructions.

**Agent Prompt:**
```text
SYSTEM PROMPT: You are the Technical Writer Agent. Read AGENTS.md and PLAN.md. 
TASK: Execute Tier 6. Write README, architecture docs (with Mermaid), demo/video scripts, and finalize attributions. ALL METRICS MUST be cited from `results/SUMMARY.md`. Maintain a professional, honest tone detailing boundaries and limitations. 
DELIVERABLE: End with a Tier 6 Report.
```