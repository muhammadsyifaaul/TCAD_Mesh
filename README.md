# TCAD Mesh — Active Defense Gateway

> **Kartika Cyber Hackathon 2026 — Defensive Shield Category**

TCAD Mesh is a transparent reverse-proxy gateway that detects API reconnaissance,
silently traps scanners in a tarpit, redirects attackers to a honeypot serving
laced fictitious data, and lets operators manage the response from a real-time
dashboard — all without any changes to the backend or the legitimate client.

---

## One-Command Quickstart

**Requires:** Docker (with `docker compose`) and `curl`. No Go, Python, Node.js, or `make` required on the host.

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Build and start all services (the only command you need)
docker compose up --build -d

# 3. Open the operator dashboard
#    Browser: http://localhost:3000

# 4. Gateway is live at
curl http://localhost:8080/health
```

That's it. No additional tooling, no manual database setup, no client SDK required.

### Windows / PowerShell users

```powershell
Copy-Item .env.example .env
docker compose up --build -d
# Open http://localhost:3000 in your browser
curl http://localhost:8080/health
```

---

## Makefile (Optional)

`make` is a convenience wrapper — not required. Raw equivalents:

| `make` command | Raw command (works on any shell) |
|----------------|-----------------------------------|
| `make up` | `docker compose up --build -d` |
| `make down` | `docker compose down` |
| `make test` | See below |
| `make e2e` | `bash scripts/e2e.sh` |
| `make bench` | `bash scripts/bench.sh` |

**Running unit tests without `make`** (all via Docker — no host toolchain needed):

```bash
# Gateway (Go tests in a throwaway golang container — no host Go needed)
# On Git Bash for Windows, pwd -W returns a Windows path; on Linux/macOS,
# pwd -W fails and plain pwd is used instead.
docker run --rm -v "$(pwd -W 2>/dev/null || pwd):/src" -w /src/gateway golang:1.22-alpine go test ./... -timeout 30s

# Python services (inside their containers)
docker compose exec -T target-app  python -m pytest -q --tb=no
docker compose exec -T honeypot    python -m pytest -q --tb=no
docker compose exec -T control-api  python -m pytest -q --tb=no
```

---

## What It Does

```
Attacker/Scanner ──► gateway:8080 ──► target-app:8001  (real backend)
                         │
                         ├─ Canary path hit?     ──► honeypot:8002
                         ├─ Quarantined identity? ──► honeypot:8002
                         ├─ Honeytoken reused?   ──► honeypot:8002
                         └─ 404 storm > threshold ──► tarpit + honeypot
                                │
                          control-api:8003  (events, quarantine, metrics)
                                │
                          dashboard:3000   (operator UI)
```

| Threat | Response |
|--------|----------|
| Path enumeration (e.g. dirbusting) | Sliding-window counter → tarpit → 429 if saturated |
| Access to canary paths (`/admin`, `/.env`, `/backup`) | Instant quarantine → honeypot redirect |
| Honeytoken reuse (attacker reuses ID from honeypot data) | HONEYTOKEN_REUSED event → quarantine |
| Sustained scanning from quarantined identity | All requests silently served honeypot data |

**Legitimate traffic is never affected.** Measured false-positive rate: **0.0%** (1000/1000 legit requests, see `results/SUMMARY.md`).

---

## Repository Map

```
tcad-mesh/
├── README.md           ← You are here
├── ATTRIBUTION.md      ← All third-party libraries + AI usage declaration
├── Makefile            ← make up / down / test / e2e / bench / demo
├── docker-compose.yml  ← All services (gateway, target-app, honeypot, control-api, dashboard)
├── .env.example        ← Template — copy to .env
│
├── gateway/            ← Go 1.22 reverse proxy + detection pipeline (minimal deps)
├── target-app/         ← FastAPI mock logistics API ("real backend")
├── honeypot/           ← FastAPI deterministic honeypot (HMAC-seeded per identity)
├── control-api/        ← FastAPI + SQLite: events, quarantine, honeytokens, sim
├── dashboard/          ← React + Vite → nginx (real-time operator UI)
├── attacker-sim/       ← Python httpx attack scenarios + Mode 2 SDK
│
├── contracts/          ← Frozen API contracts (openapi.yaml, events.schema.json)
├── bench/              ← Benchmark harness (M1–M8 metrics)
├── scripts/            ← e2e.sh, bench.sh, clean-room-test.sh
├── docs/               ← Architecture, demo scripts, slide outline
└── results/            ← Real benchmark output (SUMMARY.md, bench.json)
```

---

## Makefile Commands (Optional)

All commands below have raw equivalents listed in the Quickstart section above.
`make` is not required — Docker and `curl` are sufficient.

| Command | Action |
|---------|--------|
| `make up` | Build + start all services, wait for healthy |
| `make down` | Stop and remove containers |
| `make test` | Run unit tests across all services |
| `make e2e` | End-to-end integration tests |
| `make bench` | Run benchmark harness, write `results/SUMMARY.md` |
| `make demo` | Execute the full demo sequence |

---

## Mode 1 (Drop-In) vs Mode 2 (Hardened)

| Feature | Mode 1 | Mode 2 |
|---------|--------|--------|
| Backend changes required | ❌ None | ❌ None |
| Client SDK required | ❌ No | ✅ Lightweight |
| Canary detection | ✅ | ✅ |
| 404 enumeration detection | ✅ | ✅ |
| Honeytoken lacing | ✅ | ✅ |
| Tarpit with concurrency limit | ✅ | ✅ |
| Time-based moving-target routing | ❌ | ✅ |
| Anti-replay nonce (Redis) | ❌ | ✅ |
| Tripwire for stale-route attackers | ❌ | ✅ |
| Redis dependency | ❌ | ✅ (with in-memory fallback) |

Mode 2 is controlled by `MODE2_ENABLED=true` in `.env`.

---

## Measured Metrics (from `results/SUMMARY.md`)

> All numbers measured from live containers on a 4-core Windows 11 development
> machine running Docker Desktop. See `results/bench.json` for raw data.

### Functional Verification (from `results/bench.json`)

> These verify that detection mechanisms fire correctly. They are NOT
> performance benchmarks — see the latency and TTD/TTC sections below
> for performance measurements.

| Metric | Value | Target |
|--------|-------|--------|
| M1 Canary detection (10 paths) | **100%** | 100% |
| M2 Enum detection fires at | **request #6** | ≤ threshold+1 |
| M3 Tarpit delay (configured 3000ms) | **3016 ms** | ≥ 3000 ms |
| M4 429 under flood (60 workers) | **Yes** | Yes |
| M6 Legit success ±45s drift | **100%** | >99.9% |
| M7 Replay rejection rate | **100%** | 100% |
| **M8 False-positive rate** | **0.0%** (1000 req) | 0% |

### Performance Benchmark (from `results/bench_openloop.json`, `results/bench_ttd_ttc_v2.json`, `results/bench_ht_attr_v2.json`)

> Measured with k6 (constant-arrival-rate, open-loop) inside the Docker network,
> 60s per run, 3 reps at 50/100/200 req/s.

| Metric | Value |
|--------|-------|
| TTD (30/30, median) | **162 ms** |
| TTC (29/30, median) | **198 ms** |
| Honeytoken attribution (2s+ delay, 30/30 session-verified) | **100%** |
| Honeytoken attribution (0s delay, 15/29) | **52%** (blind window) |
| Gateway median overhead (p50, about 0.7 ms) | mean 0.69 ms, spread 0.48–0.85 ms |
| p99 under about 10 ms at 50–100 req/s | yes (≤13 ms, spread ≤±6 ms) |
| Saturation between 200 and 300 req/s | single-process upstream also saturates |
| p99 claim at 200+ rps | **none** (unstable, spread ±490 ms) |

**Honest caveat:** These numbers reflect a single-run local benchmark. They
demonstrate the system behaves correctly by design, not absolute performance
claims. See `results/SUMMARY.md` for full context and reproduction instructions.

---

## Configuration

Copy `.env.example` to `.env` and adjust:

```bash
INTERNAL_KEY=<random 32+ char string>   # gateway → control-api auth
HONEYPOT_SECRET=<random string>          # HMAC seed for fake data generation
ENUM_THRESHOLD=5                         # 404s per window before tarpit
ENUM_WINDOW_SEC=10                       # sliding window duration
TARPIT_DELAY_MS=3000                     # delay per tarpitted response
TARPIT_MAX_CONCURRENT=50                 # semaphore cap (→ 429 when full)
CANARY_PATHS=/admin,/api/v1/ops/deploy,/.env,/backup
HONEYTOKEN_POLL_MS=500                 # honeytoken poll interval (ms)
```

---

## Limitations and Honest Boundaries

This is a **hackathon prototype**, not a production-ready security product.
Known limitations:

| Limitation | Notes |
|------------|-------|
| Single-instance only | No horizontal scaling; quarantine and enum state are in-memory |
| SQLite storage | Not suitable for high-throughput production event ingestion |
| Identity based on `X-Device-ID` / IP | NAT'd environments reduce precision |
| Honeypot data determinism | Same identity always gets the same fake data — a persistent attacker could fingerprint this |
| **Target-app shipment IDs are static fixtures** | The 5 shipment IDs (`DOC-1a2b3c4d5e6f` through `DOC-5e6f7a8b9c0d`) are hardcoded in `target-app/data.py` and follow a sequential hex pattern. Honeypot IDs are HMAC-derived and look random. A sophisticated attacker comparing a legitimate response to a honeypot response could distinguish them by ID pattern alone. For a production system, target-app IDs would be randomly generated (e.g., UUIDs) or stored in a database — this is a demo simplification, not a design limitation of the gateway itself. |
| No TLS termination | Deploy behind a TLS-terminating load balancer in production |
| Mode 2 requires client SDK | Not truly transparent for Mode 2; adds client coupling |
| Replay window is 180 s | Nonces are not persisted across gateway restarts |
| Honeytoken body scan limit | Body scanning limited to 64 KB; large multipart uploads not scanned |
| Honeytoken blind window | Tokens reused within 0–500ms of issuance may not be detected (gateway polls token list every 500ms; HONEYTOKEN_POLL_MS configurable) |
| Dashboard bound to 127.0.0.1 | Not accessible from other machines without a reverse proxy; by design for demo safety |

TCAD Mesh is designed as a **complement** to existing security controls
(WAF, IDS, authentication), not a replacement. It adds active deception and
detection at the API layer with zero backend changes.

---

## Technology Stack

| Service | Stack |
|---------|-------|
| Gateway | Go 1.22 · minimal deps (`net/http`, `httputil.ReverseProxy`, `github.com/google/uuid`) |
| Target-App | Python 3.12 · FastAPI · uvicorn |
| Honeypot | Python 3.12 · FastAPI · uvicorn |
| Control-API | Python 3.12 · FastAPI · SQLite · uvicorn |
| Dashboard | React 18 · Vite 5 → nginx 1.27 |
| Attacker-Sim | Python 3.12 · httpx |
| Anti-Replay Store | Redis 7 (Mode 2 only; in-memory fallback) |

---

## License

This project was created for the Kartika Cyber Hackathon 2026.
See `ATTRIBUTION.md` for all third-party library licenses.
