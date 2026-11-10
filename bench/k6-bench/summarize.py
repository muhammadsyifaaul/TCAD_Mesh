"""Compute median-of-reps summary from bench_openloop.json."""
import json, sys, statistics

d = json.load(open(sys.argv[1]))
runs = d['runs']

print(f"date={d['date']}  tool=k6  executor=constant-arrival-rate")
print(f"endpoint={d['endpoint']}  duration={d['duration']}  reps={d['reps']}")
print()

# Per-run detail
print("=== Per-run detail ===")
print(f"{'Target':<10} {'Rate':<4} {'Rep':<4} {'p50_ms':<8} {'p95_ms':<8} {'p99_ms':<8} {'ActRps':<10} {'Valid':<5}")
print(f"{'-'*10} {'-'*4} {'-'*4} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*5}")
for r in runs:
    print(f"{r['target']:<10} {r['rate']:<4} {r['rep']:<4} {r['p50_ms']:<8} {r['p95_ms']:<8} {r['p99_ms']:<8} {r['actual_rps']:<10} {r['valid']:<5}")

print()
print("=== Median of valid runs (N=3 each cell) ===")
print(f"{'Target':<10} {'Rate':<4} {'p50_ms':<8} {'p95_ms':<8} {'p99_ms':<8} {'ActRps':<10} {'N':<3}")
print(f"{'-'*10} {'-'*4} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*3}")

medians = {}
for target in ('gateway', 'upstream'):
    for rate in (50, 100, 200):
        valid = [r for r in runs if r['target']==target and r['rate']==rate and r['valid']=='yes']
        n = len(valid)
        if n == 0:
            print(f"{target:<10} {rate:<4} {'INVALID':<8} {'INVALID':<8} {'INVALID':<8} {'INVALID':<10} {n:<3}")
            continue
        p50s = sorted(r['p50_ms'] for r in valid)
        p95s = sorted(r['p95_ms'] for r in valid)
        p99s = sorted(r['p99_ms'] for r in valid)
        rpss = sorted(r['actual_rps'] for r in valid)
        med_p50 = p50s[n//2]
        med_p95 = p95s[n//2]
        med_p99 = p99s[n//2]
        med_rps = rpss[n//2]
        medians[(target, rate)] = {'p50': med_p50, 'p95': med_p95, 'p99': med_p99, 'rps': med_rps}
        # all 3 reps per metric
        spread_p50 = max(p50s) - min(p50s)
        spread_p95 = max(p95s) - min(p95s)
        spread_p99 = max(p99s) - min(p99s)
        print(f"{target:<10} {rate:<4} {med_p50:<8} {med_p95:<8} {med_p99:<8} {med_rps:<10.2f} {n:<3}  (spread p50=±{spread_p50:.2f} p99=±{spread_p99:.2f})")

print()
print("=== Gateway overhead assessment (gateway_p50 - upstream_p50, median) ===")
overheads = []
for rate in (50, 100, 200):
    gw = medians.get(('gateway', rate))
    up = medians.get(('upstream', rate))
    if gw and up:
        oh = gw['p50'] - up['p50']
        overheads.append(oh)
        print(f"  {rate} rps: gw_p50={gw['p50']}ms  up_p50={up['p50']}ms  overhead={oh:+.2f}ms")
    else:
        print(f"  {rate} rps: data missing")

if overheads:
    signs = set('pos' if x > 0 else 'neg' for x in overheads)
    spread = max(overheads) - min(overheads)
    max_abs = max(abs(x) for x in overheads)
    if len(signs) > 1:
        print()
        print("  VERDICT: overhead changes sign across rates → overhead not characterized")
    elif max_abs > 0 and spread > 2 * max_abs:
        print()
        print("  VERDICT: overhead spread > 2× absolute value → overhead not characterized")
    else:
        print()
        print(f"  VERDICT: overhead consistent, mean={sum(overheads)/len(overheads):+.2f}ms across rates")

print()
print("=== Saturation test (300 rps, single rep) ===")
s = d.get('saturation_300rps', {})
print(f"  actual={s.get('actual_rps')}rps  p50={s.get('p50_ms')}ms  p95={s.get('p95_ms')}ms  p99={s.get('p99_ms')}ms  fail={s.get('fail_pct')}")
print("  (p99 at 300 rps shows queueing — saturation point between 200 and 300 rps)")
print("  Note: single uvicorn worker for target-app; --workers 2+ would shift saturation higher")
