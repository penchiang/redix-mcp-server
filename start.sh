#!/bin/bash
# Start the Redix MCP Server
#
# Usage:
#   ./start.sh              # STDIO mode (for Claude Desktop / Claude Code)
#   ./start.sh sse          # HTTP/SSE mode on port 8000 (multi-client)
#   ./start.sh http         # Streamable HTTP mode on port 8000
#   ./start.sh dev          # MCP Inspector web UI (opens browser)
#   ./start.sh test         # Run end-to-end tests

cd "$(dirname "$0")"

export REDIX_API_BASE="${REDIX_API_BASE:-http://localhost:8080}"
export REDIX_API_KEY="${REDIX_API_KEY:-demo-key-12345}"

case "${1:-stdio}" in
    stdio)
        echo "Starting Redix MCP Server (STDIO mode)..."
        python3.11 server.py
        ;;
    sse)
        echo "Starting Redix MCP Server (SSE mode on 0.0.0.0:${2:-8000})..."
        fastmcp run server.py -t sse --host 0.0.0.0 --port "${2:-8000}"
        ;;
    http)
        echo "Starting Redix MCP Server (HTTP mode on 0.0.0.0:${2:-8000})..."
        fastmcp run server.py -t streamable-http --host 0.0.0.0 --port "${2:-8000}"
        ;;
    dev)
        echo "Starting MCP Inspector (web UI)..."
        echo "  UI:     http://localhost:${2:-6274}"
        echo "  Proxy:  http://localhost:${3:-6277}"
        fastmcp dev server.py --ui-port "${2:-6274}" --server-port "${3:-6277}"
        ;;
    test)
        echo "Running end-to-end tests..."
        python3.11 tests/test_tools.py
        ;;
    *)
        echo "Usage: ./start.sh [stdio|sse|http|dev|test] [port]"
        echo ""
        echo "  stdio  - STDIO mode for Claude Desktop/Code (default)"
        echo "  sse    - SSE server on port (default 8000)"
        echo "  http   - Streamable HTTP server on port (default 8000)"
        echo "  dev    - MCP Inspector web UI (default port 6274)"
        echo "  test   - Run end-to-end tests"
        ;;
esac
