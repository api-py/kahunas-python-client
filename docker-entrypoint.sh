#!/bin/bash
set -e

# AWS Lambda container mode
if [ "${KAHUNAS_MCP_LAMBDA}" = "1" ]; then
    echo "Starting Kahunas MCP Server in AWS Lambda mode..."
    exec python -m awslambdaric kahunas_client.mcp.lambda_handler.handler
fi

# Standard HTTP/SSE mode (Azure ACI, Kubernetes, standalone)
echo "Starting Kahunas MCP Server (${KAHUNAS_MCP_TRANSPORT:-http} on ${KAHUNAS_MCP_HOST:-0.0.0.0}:${KAHUNAS_MCP_PORT:-8000})"
exec python -m kahunas_client.mcp "${KAHUNAS_MCP_TRANSPORT:-http}"
