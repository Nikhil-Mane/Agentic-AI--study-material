# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src SUPPORTOPS_TRACE_DIR=/tmp/traces

# non-root user (principle of least privilege)
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app

# dependencies first -> cached layer unless requirements change
COPY requirements-prod.txt .
RUN pip install -r requirements-prod.txt

COPY src ./src
COPY data ./data

USER 10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status==200 else 1)"

# workers: scale with replicas, not processes, inside k8s. 2 workers is a sane default for a single container.
CMD ["uvicorn", "supportops.api:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2", "--no-server-header"]
