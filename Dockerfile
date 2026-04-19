FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (cached unless pyproject.toml changes)
COPY pyproject.toml .
RUN pip install --no-cache-dir proxmoxer requests apscheduler "pydantic-settings>=2.3.0" jinja2 httpx

# Install the package
COPY src/ src/
RUN pip install --no-cache-dir --no-deps .

RUN mkdir -p /data

EXPOSE 8080

ENV DATA_PATH=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python", "-m", "pvewatch.main"]
