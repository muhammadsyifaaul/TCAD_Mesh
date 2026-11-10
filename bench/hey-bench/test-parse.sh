#!/usr/bin/env sh
hey -n 100 -c 10 -q 50 -t 10 http://gateway:8080/api/v1/shipments > /tmp/hey_out.txt 2>&1
echo "=== Raw latency lines ==="
grep "%%" /tmp/hey_out.txt
echo "=== P50 extraction ==="
P50=$(grep " 50%% in " /tmp/hey_out.txt | awk '{printf "%.2f", $4 * 1000}')
echo "P50 = ${P50} ms"
echo "=== P95 extraction ==="
P95=$(grep " 95%% in " /tmp/hey_out.txt | awk '{printf "%.2f", $4 * 1000}')
echo "P95 = ${P95} ms"
echo "=== P99 extraction ==="
P99=$(grep " 99%% in " /tmp/hey_out.txt | awk '{printf "%.2f", $4 * 1000}')
echo "P99 = ${P99} ms"
echo "=== RPS extraction ==="
RPS=$(grep "Requests/sec:" /tmp/hey_out.txt | awk '{printf "%.1f", $2}')
echo "RPS = ${RPS}"
echo "=== Status 200 extraction ==="
OK=$(grep "\[200\]" /tmp/hey_out.txt | sed 's/.*\[200\].*responses//' | tr -d ' \t')
echo "OK = ${OK}"
echo "=== Full raw output ==="
cat /tmp/hey_out.txt
