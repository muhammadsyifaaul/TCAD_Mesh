// gateway/events.go
// Async event dispatcher to control-api.
// Gateway MUST NOT crash or block if control-api is down (AGENTS.md §4.3).
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"
)

// Event mirrors contracts/events.schema.json exactly.
type Event struct {
	ID        string         `json:"id"`
	Ts        string         `json:"ts"`
	EventType string         `json:"event_type"`
	Severity  string         `json:"severity"`
	Mode      int            `json:"mode"`
	SrcIP     string         `json:"src_ip"`
	Identity  string         `json:"identity"`
	SessionID string         `json:"session_id"`
	Method    string         `json:"method"`
	Path      string         `json:"path"`
	UserAgent string         `json:"user_agent"`
	Status    int            `json:"status"`
	Detail    map[string]any `json:"detail,omitempty"`
}

// Dispatcher sends events to control-api asynchronously via a buffered channel.
// Drops events if the channel is full — gateway availability > event durability.
type Dispatcher struct {
	ch          chan Event
	controlURL  string
	internalKey string
	client      *http.Client
	// discard=true makes Emit a no-op (used in unit tests to avoid real HTTP calls)
	discard bool
}

func newDispatcher(controlURL, internalKey string) *Dispatcher {
	d := &Dispatcher{
		ch:          make(chan Event, 512),
		controlURL:  controlURL,
		internalKey: internalKey,
		client: &http.Client{
			Timeout: 3 * time.Second,
		},
	}
	go d.run()
	return d
}

// newNoopDispatcher creates a dispatcher that discards all events instantly.
// Used in unit tests to prevent goroutines from dialling real addresses.
func newNoopDispatcher() *Dispatcher {
	return &Dispatcher{discard: true, ch: make(chan Event, 512)}
}

// Emit queues an event for async delivery. Never blocks the caller.
func (d *Dispatcher) Emit(e Event) {
	if d.discard {
		return
	}
	select {
	case d.ch <- e:
	default:
		// Channel full — drop silently to avoid blocking proxy path (AGENTS.md §5)
		slog.Warn("event channel full, dropping event", "event_type", e.EventType)
	}
}

// run is the background worker that drains the channel and POSTs to control-api.
func (d *Dispatcher) run() {
	for e := range d.ch {
		d.send(e)
	}
}

func (d *Dispatcher) send(e Event) {
	body, err := json.Marshal(e)
	if err != nil {
		slog.Error("failed to marshal event", "err", err)
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, d.controlURL+"/events", bytes.NewReader(body))
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Internal-Key", d.internalKey)

	resp, err := d.client.Do(req)
	if err != nil {
		// control-api down — log and discard (AGENTS.md §4.3)
		slog.Debug("control-api unreachable, event dropped", "event_type", e.EventType)
		return
	}
	resp.Body.Close()
}

// newEvent constructs a fully populated Event from request context.
func newEvent(
	eventType, severity string,
	srcIP, identity, sessionID, method, path, ua string,
	status int,
	detail map[string]any,
) Event {
	return Event{
		ID:        uuid.New().String(),
		Ts:        time.Now().UTC().Format(time.RFC3339),
		EventType: eventType,
		Severity:  severity,
		Mode:      1,
		SrcIP:     srcIP,
		Identity:  identity,
		SessionID: sessionID,
		Method:    method,
		Path:      path,
		UserAgent: ua,
		Status:    status,
		Detail:    detail,
	}
}
