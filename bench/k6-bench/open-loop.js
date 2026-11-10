// bench/k6-bench/open-loop.js
// Open-loop latency benchmark using k6 constant-arrival-rate executor.
//
// This is a TRUE open-loop test: requests are generated at a fixed arrival
// rate regardless of response latency. Pre-allocated VUs absorb any
// queueing without throttling the arrival rate. This avoids the saturation
// artifact seen with closed-loop tools (hey -c 50) where concurrency
// caps throughput and inflates latency.
//
// Usage:
//   k6 run --env TARGET=gateway --env RATE=100 --env DURATION=60s open-loop.js
//   k6 run --env TARGET=upstream --env RATE=100 --env DURATION=60s open-loop.js

import http from 'k6/http';
import { check, sleep } from 'k6';

const target = __ENV.TARGET || 'gateway';
const rate = parseInt(__ENV.RATE || '100');
const duration = __ENV.DURATION || '60s';
const endpoint = __ENV.ENDPOINT || '/api/v1/shipments';

const baseUrls = {
  gateway:  'http://gateway:8080',
  upstream: 'http://target-app:8001',
};
const baseUrl = baseUrls[target] || baseUrls.gateway;

export const options = {
  // constant-arrival-rate: generates exactly `rate` requests per second
  // regardless of how fast/slow responses come back. This is the key
  // difference from closed-loop (constant-VU) executors.
  scenarios: {
    openloop: {
      executor: 'constant-arrival-rate',
      rate: rate,
      timeUnit: '1s',
      duration: duration,
      preAllocatedVUs: 500,   // enough VUs to absorb latency without throttling
      maxVUs: 1000,
    },
  },
  thresholds: {
    // We don't set hard thresholds — we report the numbers
    http_req_failed: ['rate<0.01'],
  },
};

export default function () {
  const params = {
    headers: { 'X-Device-ID': 'k6-bench-' + target },
    timeout: '10s',
  };
  const res = http.get(baseUrl + endpoint, params);
  check(res, {
    'status 200': (r) => r.status === 200,
  });
}
