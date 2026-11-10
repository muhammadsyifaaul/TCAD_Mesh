# TCAD Mesh — Slide Deck Outline

**Event:** Kartika Cyber Hackathon 2026  
**Category:** Defensive Shield  
**Total slides:** 12  
**Presentation time:** ~10 minutes (50 seconds/slide average)  
**Tone:** Technical, honest, confident — prototype framing throughout

---

## Slide 1 — Title

**Title:** TCAD Mesh: Active Defense for Internal APIs  
**Subtitle:** Transparent Honeypot Gateway — Kartika Cyber Hackathon 2026  
**Visual:** Dark background with the system architecture diagram (minimal version)  
**Speaker note:** One sentence: "We built a gateway that traps attackers using deception, with zero changes to the backend."

---

## Slide 2 — The Problem

**Title:** Internal APIs Are Soft Targets  
**Content:**
- Perimeter-focused security assumes "inside = trusted"
- Once inside, attackers enumerate endpoints freely
- Standard controls say **no** — attackers just try harder
- No visibility into reconnaissance behavior

**Visual:** Timeline showing: perimeter breach → quiet enumeration → data exfiltration  
**Key message:** "The recon phase is silent and largely uninstrumented."

---

## Slide 3 — Our Approach: Active Deception

**Title:** Don't Just Block — Mislead  
**Content:**
- **Canary paths** — tripwires that trigger on first hit
- **Honeypot** — parallel API serving believable fictitious data
- **Honeytokens** — laced IDs that track when fake data is reused
- **Tarpit** — slow scanners to a crawl, bounded by a semaphore
- **Zero backend changes required (Mode 1)**

**Visual:** 2-column table: "Attacker sees" vs "What actually happened"  
**Key message:** "Let the attacker believe they're winning — while you watch."

---

## Slide 4 — Architecture

**Title:** System Design  
**Content:** Architecture diagram (from docs/architecture.md — top-level Mermaid)  
**Callouts:**
- Only gateway:8080 and dashboard:3000 exposed to host
- All events dispatched **asynchronously** — gateway never blocks
- Control-API stores events in SQLite, polled by dashboard every 2s

**Speaker note:** "Five services. One Docker Compose file. One command to start."

---

## Slide 5 — Detection Pipeline (Mode 1)

**Title:** The 8-Step Detection Pipeline  
**Content:** Simplified flowchart (from docs/architecture.md)  
**Steps labeled:**
1. Identity extraction (X-Device-ID → IP)
2. Quarantine check
3. Honeytoken scan
4. Canary check
5. Upstream proxy + buffer
6. 404 sliding window
7. Tarpit (semaphore-bounded)
8. Header normalisation

**Visual:** Flowchart with attacker path highlighted in red  
**Key message:** "`time.Now()` called exactly once per routing decision to prevent time-oracle attacks."

---

## Slide 6 — Honeypot Design

**Title:** An Indistinguishable Trap  
**Content:**
- **Schema parity:** Identical endpoint paths and response shapes
- **Deterministic data:** `HMAC(secret, identity + field_key)` — same attacker always gets same fake data
- **Honeytoken format:** `DOC-<12 hex>` — identical to real IDs
- **Latency jitter:** ±5–15ms to mimic real backend timing
- **Zero leaky words:** "honeypot", "fake", "simulated" never appear in responses

**Visual:** Side-by-side JSON: real shipment vs honeypot shipment (same shape, different values)

---

## Slide 7 — Live Demo

**Title:** One Click. Real Attack. Real Response.  
**Content:** Screenshot or recording still from demo  
**Show:**
- Dashboard with CANARY_HIT event firing
- Quarantine table with identity + TTL
- Honeytoken panel with active DOC- token
- Event timeline filtering to CANARY_HIT

**Speaker note:** "Walk through the live demo here — see demo-script.md."

---

## Slide 8 — Measured Metrics

**Title:** Real Numbers, Not Claims  
**Subtitle:** All metrics from `results/SUMMARY.md` — measured from live containers

| Metric | Value | Target |
|--------|-------|--------|
| M1 Canary detection | 100% | 100% |
| M2 Enum fires at | Request #6 | ≤ threshold+1 |
| M3 Tarpit delay (median) | 3016 ms | ≥ 3000 ms |
| M4 429 under flood | ✅ Yes | Yes |
| M6 Legit success ±45s drift | 100% | >99.9% |
| M7 Replay rejection | 100% | 100% |
| M8 False-positive (1000 req) | 0.0% | 0% |
| TTD (30/30, median) | 162 ms | — |
| TTC (29/30, median) | 198 ms | — |
| Gateway p50 at 100 rps | 2.28 ms | — |
| Gateway overhead (p50 mean) | ~0.7 ms | — |
| Honeytoken attribution (2s+ delay) | 100% (session-verified) | — |
| **M8 False-positive rate** | **0.0%** | 0% |

**Footer:** "Single-run benchmark, 4-core dev laptop, Docker Desktop. Detection rates are behavioural and hardware-independent."

---

## Slide 9 — Mode 2: Hardened Routing (Optional)

**Title:** Moving-Target Defense for Higher-Risk Environments  
**Content:**
- Routes change every 30 seconds: `/m/<interval>-<HMAC[:16]>/<canonical_path>`
- Stale routes → **TRIPWIRE_HIT** → quarantine + honeypot
- Anti-replay: nonces cached in Redis (SET NX EX 180)
- Constant-time MAC comparison throughout (`crypto/subtle`)
- Flag-gated: `MODE2_ENABLED=false` → zero Mode 1 regression

**Visual:** Mode 2 pipeline flowchart (simplified)  
**Key message:** "Opt-in hardening. Flip one environment variable."

---

## Slide 10 — Threat Model and Honest Limitations

**Title:** What TCAD Mesh Is — and Isn't  
**In scope:**
- API enumeration, canary probing, honeytoken reuse, replay attacks, concurrent floods

**Out of scope / known limitations:**
- Authenticated API abuse (requires auth layer integration)
- Horizontal scaling (quarantine state is in-memory)
- Highly distributed NAT'd scanners
- Honeypot fingerprinting by persistent adversaries
- TLS termination (deploy behind terminating load balancer)

**Key message:** "TCAD Mesh is a **complement** to existing controls — not a replacement for authentication or WAF."

---

## Slide 11 — Implementation Quality

**Title:** Built to Be Auditable  
**Content:**
- **187/187 tests pass** (62 Go, 125 Python) — run via `make test` or raw Docker commands
- **Minimal external Go dependency** (only `github.com/google/uuid` for event IDs)
- **No fabricated metrics** — all numbers from benchmark runs in `results/`
- **ATTRIBUTION.md** documents every library + AI tool usage
- `scripts/clean-room-test.sh` simulates judge running from scratch
- Single command: `docker compose up --build -d`

**Visual:** Test output screenshot showing 187 passing  
**Key message:** "All metrics in this presentation are sourced from `results/SUMMARY.md`."

---

## Slide 12 — Roadmap and Closing

**Title:** What's Next (If This Were Production)  
**Roadmap items:**
- Distributed quarantine state (Redis Cluster)
- Per-identity honeytoken entropy via HSM
- SIEM integration (Splunk/Elastic event forwarding)
- TLS termination built-in
- Per-path honeytoken TTL and revocation
- gRPC/WebSocket support in Mode 2

**Closing line:** "TCAD Mesh demonstrates that the best defense sometimes looks exactly like what the attacker expects to find."

**Final visual:** Dashboard with live events populating + `docker compose up` command

---

## Slide Formatting Notes

- Dark theme (`#020617` background, `#e2e8f0` text) — matches dashboard aesthetic
- Code blocks in monospace, syntax highlighted
- Mermaid diagrams exported as SVG for crisp rendering
- No more than 6 bullet points per slide
- Every metric slide must reference `results/SUMMARY.md` as source
