# Kahunas MCP Server — Multi-stage Docker build
#
# Supports:
#   - Azure Container Instances (ACI)
#   - AWS Lambda (container image)
#   - Any Docker / Kubernetes host
#
# Build:
#   docker build -t kahunas-mcp .
#
# Run (HTTP mode — ACI / standalone):
#   docker run -p 8000:8000 \
#     -e KAHUNAS_EMAIL=you@example.com \
#     -e KAHUNAS_PASSWORD=your-password \
#     kahunas-mcp
#
# Run (AWS Lambda — set KAHUNAS_MCP_LAMBDA=1):
#   docker run -p 9000:8080 \
#     -e KAHUNAS_MCP_LAMBDA=1 \
#     -e KAHUNAS_EMAIL=you@example.com \
#     -e KAHUNAS_PASSWORD=your-password \
#     kahunas-mcp
#
# The container exposes port 8000 for HTTP/SSE transport by default.
# For AWS Lambda, it uses the Lambda Runtime Interface Client (RIC) on port 8080.

# ── Stage 1: Build ──
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools
RUN pip install --no-cache-dir uv

# LICENSE is required: pyproject.toml declares it via license-files.
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ src/

# Install the exact versions recorded in uv.lock rather than re-resolving.
# Without the lockfile the image could ship a different dependency set from
# the one CI audits, which is how a fixed vulnerability quietly returns.
#
# The lambda extra is included because the entrypoint below supports AWS
# Lambda mode, which needs mangum and the Lambda Runtime Interface Client.
# Those were previously never installed, so that documented mode failed at
# startup with an ImportError.
#
# uvicorn arrives transitively through fastmcp and is pinned by the
# lockfile, so it no longer needs a separate unpinned install.
RUN uv export --locked --no-dev --extra lambda --no-emit-project \
        --format requirements-txt -o /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt \
    && uv pip install --system --no-cache --no-deps . \
    && rm /tmp/requirements.txt

# ── Stage 2: Runtime ──
FROM python:3.12-slim AS runtime

# System deps for matplotlib (non-interactive backend)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libfreetype6 \
        libpng16-16 \
        libjpeg62-turbo \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/kahunas* /usr/local/bin/

# Non-root user for security
RUN useradd -m -r kahunas
USER kahunas
WORKDIR /home/kahunas

# Create export directory
RUN mkdir -p /home/kahunas/kahunas_exports

# Default environment. The server binds loopback by default because it has
# no authentication of its own; inside a container the published port is
# the boundary being controlled, so binding all interfaces is deliberate.
ENV KAHUNAS_MCP_TRANSPORT=http \
    KAHUNAS_MCP_HOST=0.0.0.0 \
    KAHUNAS_MCP_PORT=8000 \
    MATPLOTLIB_BACKEND=Agg \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Health check for container orchestrators. The server serves /health on
# the HTTP transports; it reports process liveness only and makes no call
# to the Kahunas API, so an upstream outage does not restart the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Entry point — supports both HTTP and Lambda modes
COPY --chown=kahunas:kahunas docker-entrypoint.sh /home/kahunas/
RUN chmod +x /home/kahunas/docker-entrypoint.sh

ENTRYPOINT ["/home/kahunas/docker-entrypoint.sh"]
