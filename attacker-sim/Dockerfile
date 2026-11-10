# attacker-sim/Dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /results
RUN useradd -r -s /bin/false tcad
RUN chown -R tcad:tcad /results
USER tcad

EXPOSE 8004

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004", "--no-access-log"]
