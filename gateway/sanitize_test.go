// gateway/sanitize_test.go
// Table-driven tests for log injection prevention.
package main

import (
	"strings"
	"testing"
)

func TestSanitizePath(t *testing.T) {
	cases := []struct {
		name  string
		input string
		check func(string) bool
		desc  string
	}{
		{
			name:  "newline stripped",
			input: "/path\nX-Injected: evil",
			check: func(s string) bool { return !strings.Contains(s, "\n") },
			desc:  "newline must be removed",
		},
		{
			name:  "carriage return stripped",
			input: "/path\rHeader: injected",
			check: func(s string) bool { return !strings.Contains(s, "\r") },
			desc:  "CR must be removed",
		},
		{
			name:  "ANSI escape stripped",
			input: "/path\x1b[31mred\x1b[0m",
			check: func(s string) bool { return !strings.Contains(s, "\x1b") },
			desc:  "ANSI escape must be removed",
		},
		{
			name:  "truncated to 256",
			input: "/" + strings.Repeat("a", 300),
			check: func(s string) bool { return len(s) <= 256 },
			desc:  "path must be truncated to maxPathLen",
		},
		{
			name:  "normal path unchanged",
			input: "/api/v1/shipments?page=1&limit=20",
			check: func(s string) bool { return s == "/api/v1/shipments?page=1&limit=20" },
			desc:  "normal path must pass through unchanged",
		},
		{
			name:  "null byte stripped",
			input: "/path\x00evil",
			check: func(s string) bool { return !strings.Contains(s, "\x00") },
			desc:  "null byte must be removed",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := sanitizePath(tc.input)
			if !tc.check(got) {
				t.Errorf("%s: got %q", tc.desc, got)
			}
		})
	}
}

func TestSanitizeUA(t *testing.T) {
	long := strings.Repeat("X", 250)
	got := sanitizeUA(long)
	if len(got) > 200 {
		t.Errorf("UA not truncated: len=%d", len(got))
	}
}

func TestStripPort(t *testing.T) {
	cases := []struct{ input, want string }{
		{"1.2.3.4:5678", "1.2.3.4"},
		{"::1:9999", "::1"},
		{"127.0.0.1:80", "127.0.0.1"},
		{"no-port", "no-port"},
	}
	for _, tc := range cases {
		got := stripPort(tc.input)
		if got != tc.want {
			t.Errorf("stripPort(%q) = %q, want %q", tc.input, got, tc.want)
		}
	}
}
