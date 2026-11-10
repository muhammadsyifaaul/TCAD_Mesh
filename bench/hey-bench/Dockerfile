# bench/hey-bench/Dockerfile
# Go-based load generator using hey — no Python bottleneck.
FROM golang:1.24-alpine AS builder

RUN go install github.com/rakyll/hey@latest

FROM alpine:3.19
RUN apk add --no-cache jq
COPY --from=builder /go/bin/hey /usr/local/bin/hey

ENTRYPOINT ["hey"]
