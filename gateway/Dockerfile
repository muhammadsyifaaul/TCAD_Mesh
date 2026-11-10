# ── Build stage ────────────────────────────────────────────────
FROM golang:1.22-alpine AS builder

WORKDIR /src

# Copy module files first for dependency caching
COPY go.mod go.sum ./
RUN go mod download

# Copy all source files
COPY . .

# Build a statically linked binary
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /gateway ./...

# ── Runtime stage ───────────────────────────────────────────────
FROM alpine:3.19

# wget is needed for the Docker healthcheck
RUN apk add --no-cache wget

WORKDIR /app
COPY --from=builder /gateway /app/gateway

# Drop privileges
RUN addgroup -S tcad && adduser -S tcad -G tcad
USER tcad

EXPOSE 8080

ENTRYPOINT ["/app/gateway"]
