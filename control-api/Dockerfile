# control-api/Dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Data directory for SQLite volume mount + results
RUN mkdir -p /app/data /results

# Create unprivileged user (no docker group needed — no socket mount)
RUN useradd -r -s /bin/false tcad \
 && chown -R tcad:tcad /app/data /results
USER tcad

EXPOSE 8003

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003", "--no-access-log"]
