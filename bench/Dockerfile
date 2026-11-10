# bench/Dockerfile
FROM python:3.12-slim

WORKDIR /bench

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bench.py .

# Results are written to /results volume
RUN mkdir -p /results

ENV GATEWAY_URL=http://gateway:8080
ENV CONTROL_URL=http://control-api:8003
ENV TARPIT_DELAY_MS=3000
ENV TARPIT_MAX_CONCURRENT=50
ENV ENUM_THRESHOLD=5
ENV RESULTS_PATH=/results/bench.json

CMD ["python", "bench.py"]
