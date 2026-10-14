FROM python:3.12-slim AS builder
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.lock.txt ./
RUN python -m pip install --no-cache-dir -r requirements.lock.txt
COPY pyproject.toml server.py gateway.toml ./
COPY camara_server ./camara_server
RUN python -m pip install --no-cache-dir --no-deps .

FROM python:3.12-slim AS runtime
RUN groupadd --gid 10001 mcp && useradd --uid 10001 --gid 10001 --create-home mcp
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY gateway.toml ./
USER 10001:10001
ENV PATH="/opt/venv/bin:$PATH" BIND_HOST=0.0.0.0 PORT=3000 GATEWAY_MODULES_FILE=/app/gateway.toml PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV LOG_TO_FILE=false LOG_LEVEL=info
EXPOSE 3000
CMD ["camara-mcp-server"]
