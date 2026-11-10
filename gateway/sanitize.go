// gateway/sanitize.go
// Input sanitisation helpers.
// All attacker-controlled values MUST pass through here before logging
// to prevent Log Injection (AGENTS.md §4.1, §5).
package main

import (
	"strings"
	"unicode"
)

const (
	maxPathLen = 256
	maxUALen   = 200
	maxIDLen   = 128
)

// sanitizePath strips control characters, newlines, and ANSI escape sequences,
// then truncates to maxPathLen. Returns a safe string suitable for structured logging.
func sanitizePath(s string) string {
	s = stripControl(s)
	if len(s) > maxPathLen {
		s = s[:maxPathLen]
	}
	return s
}

// sanitizeUA sanitises a User-Agent header value.
func sanitizeUA(s string) string {
	s = stripControl(s)
	if len(s) > maxUALen {
		s = s[:maxUALen]
	}
	return s
}

// sanitizeIdentity sanitises the identity string (X-Device-ID or IP).
func sanitizeIdentity(s string) string {
	s = stripControl(s)
	if len(s) > maxIDLen {
		s = s[:maxIDLen]
	}
	return s
}

// stripControl removes ASCII control characters (0x00–0x1F, 0x7F) and
// basic ANSI escape sequences to prevent log injection.
func stripControl(s string) string {
	// Remove ANSI ESC sequences: ESC [ ... m
	var b strings.Builder
	b.Grow(len(s))
	inEsc := false
	for _, r := range s {
		if r == '\x1b' {
			inEsc = true
			continue
		}
		if inEsc {
			// End of ANSI sequence on a letter
			if r >= 'A' && r <= 'z' {
				inEsc = false
			}
			continue
		}
		// Drop control characters except safe whitespace (space)
		if unicode.IsControl(r) && r != ' ' {
			continue
		}
		b.WriteRune(r)
	}
	return b.String()
}
