# bench/k6-bench/Dockerfile
FROM grafana/k6:latest

# k6 image already has the k6 binary at /usr/bin/k6
# We mount the script at runtime
ENTRYPOINT ["k6"]
