# ATTRIBUTION.md

All third-party libraries, tools, and AI assistance used in TCAD Mesh are
documented here per AGENTS.md Rule 9. This file must be updated whenever a
new dependency is introduced.

---

## AI Assistance Declaration

This project was developed with substantial assistance from **Kiro** (Amazon's
AI-powered development environment, powered by Claude Anthropic models).

The AI assistant was used as a "Lead Architect Agent" and coding partner
throughout the project, performing the following roles:

| Role | Tasks |
|------|-------|
| Architecture design | Designed the 8-step detection pipeline, Mode 2 HMAC routing scheme, async event dispatch, and nonce store resilience strategy |
| Code generation | Wrote the majority of Go (gateway) and Python (honeypot, control-api, attacker-sim) source code |
| Security review | Identified the GRACE=1 insufficient-drift-coverage bug and proposed GRACE=2 as the correct fix; enforced constant-time comparison throughout |
| Test writing | Wrote all unit tests, integration tests, and the benchmark harness |
| Documentation | Wrote all docs/ files, README.md, and this ATTRIBUTION.md |

**Human contributions:** System prompt design, tier-by-tier requirements
definition, all go/no-go gate decisions, final code review, live Docker
environment execution and verification, and architectural decisions where
the AI flagged ambiguity (e.g. the GRACE parameter correction).

Per AGENTS.md Rule 7: All benchmark metrics in `results/SUMMARY.md` were
measured from live container runs — the AI assistant did not fabricate any
numbers.

---

## gateway (Go)

| Library | Version | License | Purpose |
|---------|---------|---------|---------|
| Go stdlib | 1.22 | BSD-3-Clause | `net/http`, `httputil.ReverseProxy`, `crypto/hmac`, `crypto/subtle`, `crypto/sha256` — all core logic |
| github.com/google/uuid | 1.6.0 | BSD-3-Clause | UUID v4 generation for event IDs |

**Note:** The gateway has one external dependency (`github.com/google/uuid`).
`net/http`, `httputil.ReverseProxy`, `crypto/subtle`, `crypto/hmac`, and
`crypto/sha256` are all Go stdlib. Redis is accessed via raw RESP protocol
over a TCP socket (no Redis client library).

---

## target-app (Python)

| Library | Version | License | Purpose |
|---------|---------|---------|---------|
| fastapi | 0.111.1 | MIT | Web framework |
| uvicorn | 0.29.0 | BSD-3-Clause | ASGI server |
| httpx | 0.27.0 | BSD-3-Clause | HTTP client (test fixtures) |
| pytest | 8.2.2 | MIT | Test runner |
| pytest-asyncio | 0.23.7 | Apache-2.0 | Async test support |

---

## honeypot (Python)

| Library | Version | License | Purpose |
|---------|---------|---------|---------|
| fastapi | 0.111.1 | MIT | Web framework |
| uvicorn | 0.29.0 | BSD-3-Clause | ASGI server |
| httpx | 0.27.0 | BSD-3-Clause | HTTP client (honeytoken registration, test fixtures) |
| pytest | 8.2.2 | MIT | Test runner |
| pytest-asyncio | 0.23.7 | Apache-2.0 | Async test support |

**Honeypot data generation uses only Python stdlib:** `hmac`, `hashlib`, `struct`

---

## control-api (Python)

| Library | Version | License | Purpose |
|---------|---------|---------|---------|
| fastapi | 0.111.1 | MIT | Web framework |
| uvicorn | 0.29.0 | BSD-3-Clause | ASGI server |
| pydantic | 2.7.4 | MIT | Request/response validation |
| httpx | 0.27.0 | BSD-3-Clause | HTTP client (test fixtures) |
| pytest | 8.2.2 | MIT | Test runner |
| pytest-asyncio | 0.23.7 | Apache-2.0 | Async test support |
| docker | 7.1.0 | Apache-2.0 | Docker SDK (launching attacker-sim container) |

**Storage:** Python stdlib `sqlite3` — no ORM dependency.

---

## dashboard (React + Vite)

| Library | Version | License | Purpose |
|---------|---------|---------|---------|
| react | 18.3.1 | MIT | UI framework |
| react-dom | 18.3.1 | MIT | DOM rendering |
| recharts | 2.12.7 | MIT | Chart components (included but not actively used in Tier 3 scope) |
| vite | 5.3.4 | MIT | Build tool |
| @vitejs/plugin-react | 4.3.1 | MIT | React JSX transform |
| nginx | 1.27 (Alpine) | BSD-2-Clause | Static file server + API reverse proxy |

### Dashboard test dependencies (devDependencies — not in production bundle)

| Library | Version | License | Purpose |
|---------|---------|---------|---------|
| vitest | 1.6.0 | MIT | Unit test runner (54 render tests) |
| @testing-library/react | 16.0.0 | MIT | React component testing utilities |
| @testing-library/dom | 10.4.0 | MIT | DOM query/match utilities |
| @testing-library/jest-dom | 6.4.6 | MIT | Custom jest-dom matchers |
| @testing-library/user-event | 14.5.2 | MIT | User interaction simulation |
| jsdom | 24.1.1 | MIT | DOM environment for vitest |

### Browser test (optional, Docker-only — not a judge-machine requirement)

| Tool | Image | License | Purpose |
|------|-------|---------|---------|
| Playwright | mcr.microsoft.com/playwright:v1.48.0-noble | Apache-2.0 | Headless browser test for BMS Simulator (catches CORS/console errors that curl cannot) |

---

## attacker-sim (Python)

| Library | Version | License | Purpose |
|---------|---------|---------|---------|
| httpx | 0.27.0 | BSD-3-Clause | HTTP client for attack scenarios |
| pytest | 8.2.2 | MIT | Test runner |
| pytest-asyncio | 0.23.7 | Apache-2.0 | Async test support |

**Mode 2 SDK uses only Python stdlib:** `hmac`, `hashlib`, `math`, `uuid`, `time`

---

## bench (Python + k6 + hey)

| Library | Version | License | Purpose |
|---------|---------|---------|---------|
| httpx | 0.27.0 | BSD-3-Clause | HTTP client for benchmark requests |
| k6 | latest | AGPL-3.0 | Open-loop load testing (constant-arrival-rate) — primary latency benchmark |
| hey | latest | BSD-3-Clause | Closed-loop load testing — superseded by k6 (saturation artifact) |

---

## Infrastructure

| Component | Version | License | Purpose |
|-----------|---------|---------|---------|
| Redis | 7 (Alpine) | BSD-3-Clause | Mode 2 nonce cache (anti-replay) |
| Docker | — | Apache-2.0 | Container runtime |
| Docker Compose | v2 | Apache-2.0 | Multi-service orchestration |
| Python | 3.12 | PSF | Runtime for FastAPI services |
| Go | 1.22 | BSD-3-Clause | Runtime for gateway |
| Node.js | 20 (Alpine) | MIT | Dashboard build environment |

---

## Pre-Existing Components and Patterns

| Pattern | Origin | Usage in this project |
|---------|--------|----------------------|
| Reverse proxy pattern | `net/http/httputil` Go stdlib | `buildProxy()` in `gateway/proxy.go` |
| Sliding window rate limiting | Standard algorithm | `EnumTracker` in `gateway/state.go` |
| HMAC-based token generation | NIST FIPS 198-1 | Honeytoken derivation, Mode 2 routing |
| Semaphore-bounded concurrency | Go channel idiom | `Tarpit` in `gateway/state.go` |
| `SET NX EX` for idempotent nonce storage | Redis documentation pattern | `nonce.go` |
| Envsubst for secret injection | nginx standard practice | `dashboard/docker-entrypoint.sh` |

---

## No Pre-Existing Code Base

This project was written entirely from scratch during the hackathon period
(November 7–14, 2026). No existing TCAD Mesh codebase was forked or reused.
The only pre-existing artifacts are the libraries listed above.

---

*Last updated: 2026-11-12 — test counts: gateway Go (1 suite, ok 1.5s), target-app pytest (26 passed), honeypot pytest (27 passed), control-api pytest (27 passed), dashboard vitest (62 passed across 7 files), e2e Mode 1 (37/37), e2e Mode 2 (8/8), clean-room (25/25)*
