# Multi-arch base image -- works on both the Raspberry Pi 4 (arm64) and a
# dev laptop (amd64) without any Dockerfile changes; Docker pulls the
# matching layer automatically.
FROM python:3.11-slim

WORKDIR /app

# psycopg2-binary needs libpq at runtime; build-essential/libpq-dev only
# needed if we ever switch to the (faster, but compiled) psycopg2 package.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
