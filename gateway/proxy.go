// gateway/proxy.go
// Reverse proxy helpers and header normalisation.
// Gateway MUST normalise ALL responses (AGENTS.md §4.3 step 8).
package main

import (
	"net/http"
	"net/http/httputil"
	"net/url"
	"time"
)

// buildProxy creates a reverse proxy to the given target URL.
// upstreamTimeout controls ResponseHeaderTimeout per request.
func buildProxy(targetRaw string, upstreamTimeout ...time.Duration) *httputil.ReverseProxy {
	target, err := url.Parse(targetRaw)
	if err != nil {
		panic("invalid proxy target URL: " + targetRaw)
	}

	rht := 10 * time.Second
	if len(upstreamTimeout) > 0 && upstreamTimeout[0] > 0 {
		rht = upstreamTimeout[0]
	}

	proxy := httputil.NewSingleHostReverseProxy(target)

	// Transport with hardened timeouts (Tier 4)
	proxy.Transport = &http.Transport{
		ResponseHeaderTimeout: rht,
		IdleConnTimeout:       60 * time.Second,
		MaxIdleConns:          200,
		MaxIdleConnsPerHost:   50,
		DisableCompression:    false,
	}

	defaultDirector := proxy.Director
	proxy.Director = func(req *http.Request) {
		defaultDirector(req)
		req.Host = target.Host
		req.Header.Del("X-Forwarded-For")
		req.Header.Del("X-Real-IP")
	}

	proxy.ModifyResponse = normaliseResponse

	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		writeJSON(w, http.StatusServiceUnavailable,
			`{"error":"upstream unavailable","code":503}`)
	}

	return proxy
}

// normaliseResponse sets standard response headers on every upstream reply.
// This makes target-app and honeypot responses indistinguishable (AGENTS.md §4.3 step 8).
func normaliseResponse(resp *http.Response) error {
	resp.Header.Set("Server", "nginx")
	resp.Header.Del("X-Powered-By")
	// Ensure Date header is always present and in standard format
	if resp.Header.Get("Date") == "" {
		resp.Header.Set("Date", time.Now().UTC().Format(http.TimeFormat))
	}
	return nil
}
