# AGENTS.md — TCAD Mesh (Kartika Cyber Hackathon 2026)

This document contains the strict global rules for all AI agents working on this repository.
**READ THIS ENTIRE DOCUMENT BEFORE WRITING ANY CODE.** 
The step-by-step work plan is located in `PLAN.md`.

---

## 1. Project Context

TCAD Mesh is an **active defense gateway** (reverse proxy) deployed in front of internal API services. It detects enumeration, holds scanners in a tarpit, transparently redirects attackers to a honeypot serving deterministic fictitious data (laced with honeytokens), quarantines suspicious sessions, and visualizes alerts on a C2 dashboard.

- **Hackathon Category:** Defensive Shield.
- **Evaluation Criteria:** The prototype MUST be functional, reproducible, and easily runnable by the judges. Weight: Relevance 25%, Innovation 25%, Prototype Functionality 25%, Implementation Feasibility 15%, Documentation 10%.
- **Deadline:** November 15, 2026, 23:59 WIB. Time is severely limited. 
- **Absolute Priority:** *A smooth, flawless minimal execution is vastly superior to a complete but buggy implementation.*

### Two Operational Modes

| Mode | Features | Status |
| --- | --- | --- |
| **Mode 1 — Drop-in (Agent Focus)** | Canary paths, 404 rate detection, concurrent-limited tarpit, honeypot routing, honeytokens, quarantine, C2 dashboard. Zero backend/client changes. | **CORE. Must be flawless.** |
| **Mode 2 — Hardened** | Time-based MTD routing (HMAC), expired route tripwires, anti-replay (nonce), lightweight client SDK. | **OPTIONAL.** Only if Tier 4 is completely verified. |

---

## 2. Agent Operational Rules (STRICT COMPLIANCE REQUIRED)

1. **SINGLE TIER EXECUTION:** Work on exactly ONE tier at a time as defined in `PLAN.md`. DO NOT proceed to the next tier until all current tier gate criteria pass AND human approval is given.
2. **STRICT SCOPE:** DO NOT invent or add features outside the task list. DO NOT add LLMs, ML models, external cloud services, or heavy dependencies. If you believe something is necessary, propose it in your report—do not build it.
3. **EVIDENCE-BASED COMPLETION:** DO NOT claim a task is done without proof. Run verification commands and paste the exact output (pass/fail, metrics) in your end-of-tier report.
4. **ATOMIC COMMITS:** Make small, frequent commits. One logical task = one commit. Use conventional commits (e.g., `feat(gateway): add 404 rate limiter`).
5. **NO HARDCODED SECRETS:** Use `.env` (gitignored) and maintain `.env.example`. Never hardcode secrets in source files.
6. **ETHICAL SIMULATION:** All simulated attacks must target local containers within this Docker network. The simulator MUST use an allowlist (e.g., `gateway` or `localhost`). DO NOT scan external hosts.
7. **NO FABRICATED METRICS:** All metrics in documentation MUST originate from actual benchmark runs saved in `results/` (JSON + `SUMMARY.md`), noting the date, hardware, and commit hash.
8. **HALT ON AMBIGUITY:** If architecture is ambiguous, STOP and ask the human. Do not guess.
9. **MINIMAL DEPENDENCIES:** Log every third-party library in `ATTRIBUTION.md` (name, version, license). 
10. **HUMAN-READABLE CODE:** Write clean code with concise comments explaining security logic. Avoid overly clever tricks. The human owner must be able to explain your code to the judges.
11. **DIRECTORY ISOLATION:** Only edit the directory assigned to your current role. DO NOT modify `contracts/` without explicit human permission.
12. **NO REGRESSIONS:** DO NOT alter or break behavior that passed previous tier gates without mentioning it in your report and re-running tests.

---

## 3. Architecture

```text
 Client / Attacker
        │
        ▼
 ┌──────────────┐   Normal Proxy    ┌──────────────┐
 │   gateway    │ ────────────────► │  target-app  │ (Mock Logistics API = "Real Backend")
 │   (Go)       │                   └──────────────┘
 │              │   Canary / Quar.  ┌──────────────┐
 │              │ ────────────────► │   honeypot   │ (FastAPI, Deterministic Fictitious Data)
 └──────┬───────┘                   └──────┬───────┘
        │ events (JSON)                    │ registers honeytokens
        ▼                                  ▼
 ┌─────────────────────────────────────────────┐
 │ control-api (FastAPI + SQLite)              │ ◄── dashboard (React, Static UI)
 │ events, stats, quarantine, honeytokens, sim │ ◄── attacker-sim (Python)
 └─────────────────────────────────────────────┘
        (Mode 2) redis: nonce cache
```

| Service | Tech Stack | Responsibilities |
| --- | --- | --- |
| `gateway` | Go 1.22+, **stdlib** (`net/http`, `httputil.ReverseProxy`) | Detection pipeline, tarpit, quarantine enforcement, reverse proxy, header normalization, async event dispatch. |
| `target-app` | Python FastAPI | The "Real Backend": Mock logistics API serving operational data. |
| `honeypot` | Python FastAPI | Identical schema to target-app, deterministic fake data, honeytoken generation. |
| `control-api` | Python FastAPI + SQLite | State management: events, metrics, active quarantines, honeytoken registry, simulation trigger. |
| `dashboard` | React + Vite (Static build) | Operator UI, event timeline, simulation trigger buttons. |
| `attacker-sim` | Python (httpx) | Execution of scan, replay, and legitimate client scenarios; outputs metrics. |
| `redis` | Redis 7 | Mode 2 only (nonce cache for anti-replay). |

---

## 4. Contracts (Source of Truth: `contracts/` folder)

### 4.1 Event Schema (JSON, one object per event)

```json
{
  "id": "uuid",
  "ts": "2026-11-08T10:00:00Z",
  "event_type": "CANARY_HIT",
  "severity": "info|warn|high",
  "mode": 1,
  "src_ip": "172.20.0.5",
  "identity": "device-id or IP",
  "session_id": "string",
  "method": "GET",
  "path": "truncated to 256 chars, sanitized",
  "user_agent": "truncated to 200 chars",
  "status": 200,
  "detail": {}
}
```

- **Allowed `event_type`:** `SYSTEM_START`, `ENUM_DETECTED`, `TARPIT_ACTIVE`, `TARPIT_SATURATED`, `CANARY_HIT`, `QUARANTINED`, `QUARANTINE_RELEASED`, `HONEYTOKEN_ISSUED`, `HONEYTOKEN_REUSED`, `SIM_STARTED`, `SIM_FINISHED`, and (Mode 2) `TRIPWIRE_HIT`, `REPLAY_REJECTED`.
- **MANDATORY SANITIZATION:** All attacker-controlled inputs (path, headers, UA) MUST be sanitized before logging to prevent Log Injection.

### 4.2 Control-API Endpoints (Write endpoints require `X-Internal-Key` header)

| Method | Path | Function |
| --- | --- | --- |
| POST | `/events` | Ingest events from gateway/honeypot |
| GET | `/events?since=&type=&limit=` | Fetch events for dashboard |
| GET | `/stats` | Summary metrics |
| GET | `/quarantine` | List quarantined identities (+ remaining TTL) |
| POST | `/quarantine/{identity}` | Add quarantine (called by gateway) |
| POST | `/quarantine/{identity}/release` | Operator manually lifts quarantine |
| POST | `/honeytokens` | Honeypot registers token + session_id |
| GET | `/honeytokens` | Gateway polls token list (every 2s) |
| POST | `/sim/run` | Execute scenario `{scenario: "scan"|"replay"|"legit"|"full"}` |
| GET | `/sim/status` | Current simulation status |
| GET | `/health` | Health check |

### 4.3 Gateway Behavior Pipeline (Mode 1) — Execution Order

1. **Identity Extraction:** Use `X-Device-ID` header if present, otherwise fallback to Client IP.
2. **Quarantine Check:** If identity is quarantined → proxy directly to `honeypot` (normalize headers). Stop execution.
3. **Honeytoken Scan:** Regex scan path/query/header/body for registered honeytokens. If found → emit `HONEYTOKEN_REUSED`, trigger quarantine, proxy to honeypot.
4. **Canary Check:** If path matches `CANARY_PATHS` list → emit `CANARY_HIT`, trigger quarantine, proxy to honeypot.
5. **Upstream Proxy:** Forward to `target-app`. If upstream returns **404**, increment the 404 counter for this identity.
6. **Enumeration Threshold:** If `> ENUM_THRESHOLD` 404s occur within `ENUM_WINDOW_SEC` → emit `ENUM_DETECTED`, activate **Tarpit** for this identity for 60 seconds.
7. **Tarpit Execution:** Delay response by `TARPIT_DELAY_MS`. Concurrency MUST be bounded by `TARPIT_MAX_CONCURRENT` (use a semaphore). If semaphore is full → immediately return `429 Too Many Requests` + emit `TARPIT_SATURATED`.
8. **Header Normalization:** ALL responses MUST have headers normalized (set standard `Server`, format `Date`, strip `X-Powered-By`).

**Required ENV Variables (with defaults in `.env.example`):** `UPSTREAM_URL`, `HONEYPOT_URL`, `CONTROL_URL`, `INTERNAL_KEY`, `CANARY_PATHS` (default `/admin,/api/v1/ops/deploy,/.env,/backup`), `ENUM_THRESHOLD=5`, `ENUM_WINDOW_SEC=10`, `TARPIT_DELAY_MS=3000`, `TARPIT_MAX_CONCURRENT=50`, `QUARANTINE_TTL_SEC=900`, `MODE2_ENABLED=false`.

**Event Dispatch:** Gateway MUST send events asynchronously. Gateway MUST NOT crash or block if `control-api` is down.

### 4.4 Honeypot Rules

- **Schema Parity:** MUST exactly match `target-app` schema.
- **Deterministic Data:** Fake data generation MUST be seeded using `HMAC(secret_server, identity)`.
- **Honeytokens:** Generated IDs MUST share the exact format as real IDs (`DOC-<12 hex>`).
- **Absolute Secrecy:** DO NOT include words like `simulated`, `honeypot`, `fake`, or `pending_*` anywhere in the response.
- **Latency Jitter:** Add slight latency jitter (5-15ms).

### 4.5 Mode 2 (Only if instructed)

- **Routing:** `/m/<interval>-<mac16>/<canonical_path>`. Gateway strips the prefix and forwards `<canonical_path>`.
- **MAC Calc:** `mac = HMAC-SHA256(secret_device, "route:" + interval)`, extract first 16 hex chars.
- **Interval:** `interval = floor(unix_time / INTERVAL_SEC)`. Calculate `now` exactly ONCE per request.
- **Validation:** O(1) check. `interval` must be within `[cur-GRACE, cur+GRACE]` AND MAC must be correct. If interval is older than grace window but MAC is correct → `TRIPWIRE_HIT` → Quarantine + Honeypot.
- **Anti-Replay:** Require headers `X-Device-ID`, `X-Timestamp`, `X-Nonce`, `X-Signature = HMAC(secret, method|path|sha256(body)|timestamp|nonce)`. Store nonce in Redis `SET NX EX 180`. Duplicate → `REPLAY_REJECTED`.
- **Constant Time Compare:** Always use `crypto/subtle.ConstantTimeCompare`.

---

## 5. Design Anti-Patterns (STRICTLY FORBIDDEN)

- ❌ Returning HTTP 200 for all unknown paths.
- ❌ Hardcoding honeypot response JSON with obvious "fake" labels.
- ❌ Using basic string concatenation `SHA256(secret:path:interval)` instead of true HMAC.
- ❌ Calling `time.Now()` multiple times in a single routing decision block.
- ❌ Using standard `==` string comparison for security hashes/MACs.
- ❌ `Printf`-ing raw attacker inputs into logs.
- ❌ Committing secrets or hardcoding them in source files.
- ❌ Claiming "0% false positive" or "100% detection" in docs.
- ❌ Implementing a Tarpit without concurrency limits.
- ❌ Synchronous event dispatching that blocks the main proxy thread.

---

## 6. Repository Structure & Ownership

```text
tcad-mesh/
├── AGENTS.md  PLAN.md  README.md  ATTRIBUTION.md  Makefile
├── docker-compose.yml  .env.example  .gitignore
├── contracts/            # openapi.yaml, events.schema.json
├── gateway/              # Go
├── target-app/           # FastAPI
├── honeypot/             # FastAPI
├── control-api/          # FastAPI + SQLite
├── dashboard/            # React + Vite
├── attacker-sim/         # Python scenarios + metrics
├── bench/                # load testing scripts
├── results/              # Real metrics (JSON + SUMMARY.md)
├── docs/                 # architecture, scripts, slides
└── scripts/              # bash scripts for E2E
```

---

## 7. Makefile Commands

| Command | Function |
| --- | --- |
| `make up` | `docker compose up --build -d` and wait for health OK |
| `make down` | stop and clean containers |
| `make test` | run unit tests across all services |
| `make e2e` | run integration tests |
| `make bench` | run load/metrics tests |
| `make demo` | execute full demo script sequence |

---

## 8. Agent Report Format

```markdown
## Tier [N] Report
**Status:** COMPLETE | PARTIAL | BLOCKED
**Completed Tasks:** (Brief list + commit hashes)
**Verification Evidence:** (Paste exact CLI command executed + pass/fail output or metrics)
**Gate Criteria Checklist:** (Mark ✅/❌ for each gate criterion with proof)
**Human Input Required / Decisions:** (List any blockers; empty if none)
```

---

## 9. Definition of Done (Project Level)

- [ ] `docker compose up` works on a clean machine without manual intervention.
- [ ] `make e2e` and `make test` pass.
- [ ] Dashboard displays real-time events.
- [ ] Legitimate traffic baseline generates **zero** alerts.
- [ ] `results/SUMMARY.md` is populated with REAL metrics.
- [ ] Documentation is complete and honest.
- [ ] `.env.example` is present; no secrets committed.