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

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ src/

# Build the wheel
RUN uv pip install --system --no-cache . \
    && uv pip install --system --no-cache uvicorn

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

# Default environment
ENV KAHUNAS_MCP_TRANSPORT=http \
    KAHUNAS_MCP_HOST=0.0.0.0 \
    KAHUNAS_MCP_PORT=8000 \
    MATPLOTLIB_BACKEND=Agg \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Health check for container orchestrators
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Entry point — supports both HTTP and Lambda modes
COPY --chown=kahunas:kahunas docker-entrypoint.sh /home/kahunas/
RUN chmod +x /home/kahunas/docker-entrypoint.sh

ENTRYPOINT ["/home/kahunas/docker-entrypoint.sh"]
