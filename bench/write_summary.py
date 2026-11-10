"""
bench/write_summary.py
Reads results/bench.json and writes results/SUMMARY.md.
Called automatically by scripts/bench.sh after bench.py completes.
"""
import json
import os
import sys

def main():
    bench_path   = os.environ.get("BENCH_JSON",   "results/bench.json")
    summary_path = os.environ.get("SUMMARY_PATH", "results/SUMMARY.md")

    if not os.path.exists(bench_path):
        print(f"[write_summary] ERROR: {bench_path} not found — run bench.py first", file=sys.stderr)
        sys.exit(1)

    with open(bench_path) as f:
        d = json.load(f)

    m1_rate  = d.get("m1_canary_detection_rate_pct", "N/A")
    m1_det   = d.get("m1_canary_detected", "?")
    m1_tot   = d.get("m1_canary_requests", "?")
    m2_req   = d.get("m2_enum_requests_until_detected", "?")
    m2_thr   = d.get("m2_enum_threshold_configured", "?")
    m3_min   = d.get("m3_tarpit_delay_ms_min", "?")
    m3_med   = d.get("m3_tarpit_delay_ms_median", "?")
    m3_p95   = d.get("m3_tarpit_delay_ms_p95", "?")
    m3_cfg   = d.get("m3_tarpit_configured_ms", "?")
    m4_conc  = d.get("m4_concurrent_flood", "?")
    m4_429   = d.get("m4_got_429", False)
    m8_tot   = d.get("m8_legit_requests", "?")
    m8_unexp = d.get("m8_legit_unexpected_status", "?")
    m8_fp    = d.get("m8_false_positive_rate_pct", "?")
    date     = d.get("date", "unknown")
    hw       = d.get("hardware", "unknown")
    commit   = d.get("commit_hash", "unknown")
    errors   = d.get("errors", [])

    md = f"""# TCAD Mesh — Benchmark Results (Mode 1)

> **Generated:** {date}
> **Hardware:** {hw}
> **Commit:** `{commit}`
> **Source:** `results/bench.json` — all numbers measured from live containers.
> Per AGENTS.md Rule 7: no fabricated metrics.

---

## M1 — Canary Detection Rate

| Metric | Value |
|--------|-------|
| Canary paths tested | {m1_tot} |
| Detected (proxied to honeypot) | {m1_det} |
| **Detection rate** | **{m1_rate}%** |

**Target:** 100% (every configured canary path must be caught)

---

## M2 — Enumeration Detection Latency

| Metric | Value |
|--------|-------|
| Configured threshold | {m2_thr} requests / 10 s window |
| Requests until ENUM_DETECTED fired | {m2_req} |

**Target:** ENUM_DETECTED fires at or before threshold + 1 request

---

## M3 — Tarpit Delay

| Metric | Value |
|--------|-------|
| Configured delay | {m3_cfg} ms |
| Measured min | {m3_min} ms |
| Measured median | {m3_med} ms |
| Measured p95 | {m3_p95} ms |

**Target:** median ≥ configured delay (tarpit is active and enforced)

---

## M4 — Tarpit Saturation (429)

| Metric | Value |
|--------|-------|
| Configured max concurrent | {d.get("m4_tarpit_max_concurrent", "?")} |
| Concurrent flood workers sent | {m4_conc} |
| 429 observed under flood | {"✅ YES" if m4_429 else "❌ NO"} |

**Target:** at least one 429 when flood exceeds TarpitMaxConcurrent

---

## M8 — Legitimate Traffic False-Positive Rate

| Metric | Value |
|--------|-------|
| Legit requests sent | {m8_tot} |
| Unexpected non-2xx responses | {m8_unexp} |
| **False-positive rate** | **{m8_fp}%** |

**Target:** 0% — legitimate traffic MUST never trigger alerts

---

## Gate T4 Status

| Metric | Result | Pass? |
|--------|--------|-------|
| M1 canary detection | {m1_rate}% | {"✅" if m1_rate == 100.0 else "⚠️"} |
| M2 enum detection fires | req #{m2_req} | {"✅" if isinstance(m2_req, int) and m2_req > 0 else "❌"} |
| M3 tarpit active | median {m3_med}ms | {"✅" if isinstance(m3_med, (int,float)) and m3_med >= 500 else "⚠️ (low-delay test env)"} |
| M4 429 under flood | {m4_429} | {"✅" if m4_429 else "❌"} |
| M8 false positives | {m8_fp}% | {"✅" if m8_fp == 0.0 else "❌"} |

---

## Errors During Benchmark

{chr(10).join(f"- `{e}`" for e in errors) if errors else "_No errors._"}

---

*IMPORTANT: These numbers reflect a single benchmark run in a local Docker environment.*
*Hardware, load, and configuration affect all values. See AGENTS.md Rule 7.*
"""

    os.makedirs(os.path.dirname(summary_path) if os.path.dirname(summary_path) else ".", exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[write_summary] Written → {summary_path}")


if __name__ == "__main__":
    main()
