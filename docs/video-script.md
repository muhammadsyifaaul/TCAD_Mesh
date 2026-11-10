# TCAD Mesh — Video Script (≤ 10 Minutes)

**Format:** Screen recording with voiceover  
**Target length:** 8–9 minutes  
**Submission:** YouTube (unlisted)

---

## [0:00–0:45] Hook + Problem Statement

**[SCREEN: Title card — "TCAD Mesh: Active Defense for Internal APIs"]**

**VO:** "Your internal API is behind a firewall. But attackers who get inside
your network can still enumerate every endpoint, discover sensitive paths,
and map your data schema before your SIEM even fires an alert.

Traditional security controls — firewalls, WAFs, authentication — tell attackers
*no*. TCAD Mesh takes a different approach: it tells attackers *yes* — and
then traps them.

This is TCAD Mesh: a transparent active-defense gateway for internal APIs."

---

## [0:45–1:30] Solution Overview

**[SCREEN: Architecture diagram from docs/architecture.md — the top-level flow]**

**VO:** "TCAD Mesh is a reverse proxy that sits between clients and your backend.
Legitimate clients pass straight through — they see your real API, your real data,
your real response times. Attackers get a different experience entirely.

Three core mechanisms:
One — Canary paths. Pre-defined sensitive URLs that no legitimate client ever
requests. The moment something hits `/admin` or `/.env`, TCAD Mesh knows it's
not a legitimate user.

Two — Honeypot. A parallel API that serves deterministic fictitious data —
same schema, same ID formats, but completely fake. Attackers get confidently
wrong information.

Three — Honeytokens. The fake data contains tracking IDs. If an attacker
extracts a DOC ID from our honeypot and uses it in a subsequent request,
TCAD Mesh flags it — attribution by deception."

---

## [1:30–2:30] One-Command Quickstart

**[SCREEN: Terminal — running docker compose up --build -d]**

**VO:** "Deployment is a single command. No changes to your backend. No SDK
required on the client. No database setup. Everything runs in Docker.

We have five services: the Go gateway, the FastAPI backend, the honeypot,
the control API backed by SQLite, and a React dashboard served by nginx.

Thirty seconds after running that command, all five containers are healthy."

**[SCREEN: docker compose ps showing all services as "healthy"]**

---

## [2:30–4:30] Live Demo — The Attack

**[SCREEN: Split view — dashboard left, terminal right]**

**VO:** "Let me show you what this looks like under attack.

First, legitimate traffic. I'll hit the shipments API — 200 OK, real data,
dashboard shows no alerts. That's the 0% false-positive rate we measured."

**[SCREEN: curl /api/v1/shipments → 200, dashboard stays clean]**

**VO:** "Now I'm the attacker. I probe for `/admin`."

**[SCREEN: curl /admin → 200, dashboard shows CANARY_HIT + QUARANTINED]**

**VO:** "I got a 200 — the attacker thinks they found something. But they've
been silently redirected to the honeypot, and every subsequent request from
this identity now serves fake data. They don't know. The gateway doesn't
change its response code, doesn't change its headers — it's completely transparent."

**[SCREEN: Show honeypot shipment data — realistic-looking DOC- IDs]**

**VO:** "See those DOC IDs in the response? Those are honeytokens — tracking
identifiers that only exist in the honeypot. When the attacker tries to use
one of them..."

**[SCREEN: curl with ?doc=DOC-abc123... → HONEYTOKEN_REUSED fires on dashboard]**

**VO:** "...we know exactly who touched our trap. That's attribution."

---

## [4:30–5:30] Tarpit and Saturation

**[SCREEN: Terminal — 7 curl requests to random paths]**

**VO:** "A scanner hits 7 random 404 paths within 10 seconds.
ENUM_DETECTED fires. The tarpit activates."

**[SCREEN: time curl — shows 3-second delay, TARPIT_ACTIVE on dashboard]**

**VO:** "Every subsequent request from this scanner takes 3 seconds.
At scale — fifty concurrent scanners — the semaphore fills and they start
getting 429 Too Many Requests. The scanner effectively stalls."

---

## [5:30–6:30] Operator Dashboard

**[SCREEN: Dashboard — Stats Panel, Event Timeline, Quarantine Table]**

**VO:** "The operator dashboard gives full visibility in real time. Here's
the event timeline — filterable by type. The quarantine table shows every
trapped identity with a TTL countdown.

Operators can release a quarantine manually — the gateway reflects that
release within two seconds via the polling loop."

**[SCREEN: Click Release, show identity disappearing from quarantine table]**

**VO:** "And with one click — Full Demo — the built-in attack simulator
replays the full attack sequence so you can demonstrate the system to
stakeholders on demand."

---

## [6:30–7:30] Metrics (Honest)

**[SCREEN: results/SUMMARY.md]**

**VO:** "All metrics in our documentation come from real benchmark runs —
never fabricated.

Canary detection rate: 100% — every configured canary path was caught.
Time-to-detect: 30 of 30 measurements succeeded, median 169ms.
Time-to-contain: 29 of 30 succeeded (1 failure revealed a real quarantine race condition), median 190ms.
False-positive rate: 0.0% — 1000 consecutive legit requests triggered zero alerts.
Replay rejection: 100%.
Gateway median overhead of about 0.7 ms (p50 difference), p99 under about 10 ms at 50–100 req/s in a local Docker test, saturation between 200 and 300 req/s with the single-process upstream also saturating.
Honeytoken session attribution: 100% at 1s+ delay (session-verified). 52% at 0s delay — the blind window is documented as a known limitation.

We want to be honest: these numbers come from a single run on a 4-core
development laptop running Docker Desktop. Production hardware will show
different absolute latency values. The detection rates are behavioural
and hardware-independent."

---

## [7:30–8:30] Mode 2 — Hardened Routing (Optional)

**[SCREEN: Architecture diagram — Mode 2 pipeline]**

**VO:** "For higher-security environments, Mode 2 adds time-based moving-target
routing. Routes change every 60 seconds based on an HMAC-derived prefix.
An attacker who intercepts a valid URL can't replay it — the nonce
anti-replay layer rejects duplicate nonces regardless of timing.

Anti-replay uses nonces cached in Redis with a 180-second TTL. Even if an
attacker captures a request mid-flight, replaying it returns 401.

This is optional — flip a single environment variable. Mode 1 behavior is
completely unchanged when Mode 2 is disabled."

---

## [8:30–9:15] Limitations and Roadmap

**[SCREEN: Limitation table from README.md]**

**VO:** "We're honest about what this is: a hackathon prototype that demonstrates
the concept. It's a complement to existing controls — not a replacement for
your WAF or authentication layer.

Current limitations: single-instance only, SQLite storage, identity based on
IP or device header, and the honeypot's determinism means a persistent attacker
could potentially fingerprint it.

Roadmap for a production version would include: distributed state via Redis,
per-tenant honeytoken entropy, TLS termination, and deeper integration with
SIEM pipelines."

---

## [9:15–9:45] Closing

**[SCREEN: Terminal — docker compose up, then open browser]**

**VO:** "TCAD Mesh. One command to deploy. Zero changes to your backend.
Active deception that turns the attacker's reconnaissance against them.

The code is in the repository. The benchmark results are in results/SUMMARY.md.
Thank you."

**[SCREEN: Dashboard with live events populating from the simulation]**

---

## Recording Notes

- Keep terminal font size ≥ 16pt for readability
- Highlight key moments: CANARY_HIT flash, tarpit delay timer, release button
- Silence between commands is fine — let the events load naturally
- Do not speed up the tarpit delay — 3 seconds is the point
- Total target: 8 minutes 45 seconds
