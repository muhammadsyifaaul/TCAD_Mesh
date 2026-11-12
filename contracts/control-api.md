# Control-API Contract

**Service:** `control-api` (FastAPI + SQLite)  
**Internal Base URL:** `http://control-api:8003`  
**Version:** 1.0.0  
**Status:** FROZEN (Tier 0)

---

## Authentication

Write endpoints (marked **🔒**) require the header:

```
X-Internal-Key: <value of INTERNAL_KEY env var>
```

Read endpoints and `/health` are unauthenticated (accessible only within the Docker `mesh` network — never exposed directly to the host).

---

## Endpoints

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Returns `{"status":"ok","service":"control-api","version":"0.1.0"}` |

---

### Events

#### `POST /events` 🔒

Ingest a single event from gateway or honeypot.

**Request body:** One event object conforming to `contracts/events.schema.json`.

**Response `202 Accepted`:**
```json
{ "id": "<uuid of ingested event>" }
```

**Response `422 Unprocessable Entity`:** Schema validation failure.

---

#### `GET /events`

Fetch events for the dashboard, with optional filters.

**Query parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `since` | ISO 8601 datetime string | (none) | Return events with `ts >= since` |
| `type` | string | (none) | Filter by `event_type` (comma-separated for multiple) |
| `limit` | integer (1–1000) | 100 | Maximum number of events to return |

**Response `200 OK`:**
```json
{
  "data": [ /* array of event objects */ ],
  "total": 42
}
```

> **Design note — time window:** When `since` is omitted, `GET /events` applies a rolling
> **24-hour cutoff** (`ts >= now - 24h`). The `total` field in the response counts only the
> events within that window (and within the `limit` cap). This is intentional: keeping the
> dashboard payload small and showing only recent activity.
>
> `GET /stats`, by contrast, counts **all rows** (`SELECT COUNT(*) FROM events`) regardless
> of age. This is also intentional: stats track lifetime totals for KPI dashboards and
> post-incident review.
>
> Consequence: `stats.total_events` will always be **≥** the `events.total` returned by
> `GET /events`, and can be much larger after the system has been running for hours. Both
> values are correct — they answer different questions.
>
> If you need all events since a specific point in time, pass `?since=<ISO8601>` explicitly.

---

### Stats

#### `GET /stats`

Returns aggregated summary metrics. Counts cover **all rows in the database** (no time
filter) and reflect lifetime totals since the last `POST /reset`.

**Response `200 OK`:**
```json
{
  "total_events": 142,
  "events_by_type": {
    "CANARY_HIT": 5,
    "ENUM_DETECTED": 3,
    "QUARANTINED": 4
  },
  "active_quarantines": 2,
  "active_honeytokens": 7,
  "uptime_seconds": 3600
}
```

---

### Quarantine

#### `GET /quarantine`

List all currently quarantined identities.

**Response `200 OK`:**
```json
{
  "epoch": 3,
  "data": [
    {
      "identity": "172.20.0.5",
      "quarantined_at": "2026-11-08T10:05:00Z",
      "expires_at": "2026-11-08T10:20:00Z",
      "remaining_ttl_sec": 847,
      "reason": "CANARY_HIT"
    }
  ]
}
```

The `epoch` field is a monotonic integer incremented by `POST /reset`. The gateway uses this
to clear its confirmed in-memory quarantines deterministically — it does NOT infer a reset
from an empty list.

---

#### `POST /quarantine/{identity}` 🔒

Add an identity to quarantine (called by gateway).

**Path parameter:** `identity` — URL-encoded device ID or IP.

**Request body:**
```json
{
  "reason": "CANARY_HIT",
  "ttl_sec": 900
}
```

**Response `201 Created`:**
```json
{ "identity": "172.20.0.5", "expires_at": "2026-11-08T10:20:00Z" }
```

**Response `200 OK`:** If identity already quarantined (TTL is NOT reset).

---

#### `POST /quarantine/{identity}/release` 🔒

Operator manually lifts a quarantine.

**Response `200 OK`:**
```json
{ "identity": "172.20.0.5", "released": true }
```

**Response `404 Not Found`:** Identity not currently quarantined.

> **SLA:** Gateway MUST poll quarantine state and reflect a release within ≤ 2 seconds.

---

### Honeytokens

#### `POST /honeytokens` 🔒

Honeypot registers a newly issued honeytoken.

**Request body:**
```json
{
  "token": "DOC-1a2b3c4d5e6f",
  "session_id": "sess-7a3f9b",
  "identity": "172.20.0.5",
  "issued_at": "2026-11-08T10:00:00Z"
}
```

**Response `201 Created`:**
```json
{ "token": "DOC-1a2b3c4d5e6f", "registered": true }
```

---

#### `GET /honeytokens`

Gateway polls this endpoint every `HONEYTOKEN_POLL_MS` milliseconds (default 100 ms)
to refresh its in-memory token set with full issuing metadata.

**Response `200 OK`:**
```json
{
  "tokens": [
    {
      "token":      "DOC-1a2b3c4d5e6f",
      "session_id": "sess-7a3f9b",
      "identity":   "172.20.0.5",
      "issued_at":  "2026-11-08T10:00:00Z"
    }
  ]
}
```

**Contract change (approved in Tier 5 fix):** Previously returned `{"tokens": ["DOC-..."]}`.
Now returns full objects so the gateway can populate `detail.original_session` correctly in
`HONEYTOKEN_REUSED` events, enabling attribution to the issuing session.

**Blind window (measured):** With the default `HONEYTOKEN_POLL_MS=100` ms, attribution was 30/30 (100%) at 0 s, 0.25 s, 0.5 s, and 1 s reuse delays in controlled 30-token batches (run 2026-11-12, inside Docker network). The configurable `HONEYTOKEN_POLL_MS` env var allows tuning this window.

---

### Simulation

#### `POST /sim/run` 🔒

Trigger the attacker-sim container to execute a scenario.

**Request body:**
```json
{ "scenario": "scan" }
```

**Allowed `scenario` values:** `scan`, `legit`, `full`

**Response `202 Accepted`:**
```json
{ "run_id": "<uuid>", "scenario": "scan", "status": "started" }
```

**Response `409 Conflict`:** A simulation is already running.

---

#### `GET /sim/status`

Get the current simulation status.

**Response `200 OK`:**
```json
{
  "run_id": "<uuid>",
  "scenario": "scan",
  "status": "running | completed | failed | idle",
  "started_at": "2026-11-08T10:10:00Z",
  "finished_at": null,
  "result": null
}
```

---

## Error Format

All error responses use:
```json
{ "error": "<human-readable message>", "code": <http_status_int> }
```

---

## Notes

- SQLite database file is stored at `/app/data/tcad.db` (persisted via Docker volume `control-api-data`).
- All timestamps are UTC ISO 8601.
- The `/events` endpoint applies a rolling **24-hour cutoff** (`ts >= now - 24h`) when `since`
  is not specified. `total` in the response reflects only the events within that window (capped
  by `limit`). `GET /stats` counts all rows with no time filter. See the `GET /events` Design
  note above for a full explanation of when the two counters will differ.
- `POST /events` MUST validate the incoming body against `events.schema.json` before persisting.
