#!/bin/bash
# Redix MCP Server — management script
#
# Usage:
#   ./mcp.sh start [mode]    Start the server (dev|sse|http|stdio)
#   ./mcp.sh stop            Stop all running instances
#   ./mcp.sh restart [mode]  Restart (stop + start)
#   ./mcp.sh status          Show running instances and ports
#   ./mcp.sh test            Run end-to-end tests
#   ./mcp.sh logs            Tail the log file
#
# Modes:
#   dev    — MCP Inspector web UI (default: ports 6274/6277)
#   sse    — SSE server for remote agents (default: port 8000)
#   http   — Streamable HTTP server (default: port 8000)
#   stdio  — STDIO for Claude Desktop/Code (foreground)

set -e
cd "$(dirname "$0")"

export REDIX_API_BASE="${REDIX_API_BASE:-http://localhost:8080}"
export REDIX_API_KEY="${REDIX_API_KEY:-demo-key-12345}"

PIDFILE="/tmp/redix-mcp-server.pid"
LOGFILE="/tmp/redix-mcp-server.log"

# ── helpers ──────────────────────────────────────────────────

_is_running() {
    [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null
}

_stop() {
    # Kill tracked PID
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Stopping Redix MCP Server (PID $PID)..."
            kill "$PID" 2>/dev/null || true
            pkill -P "$PID" 2>/dev/null || true
        fi
        rm -f "$PIDFILE"
    fi

    # Kill anything on our known ports (inspector + sse/http)
    # Skip 6277 — that's nginx (HTTPS proxy), not ours to kill
    for port in 6274 6278 8000; do
        PIDS=$(fuser "${port}/tcp" 2>/dev/null | xargs)
        if [ -n "$PIDS" ]; then
            echo "Stopping process on port $port (PID $PIDS)..."
            kill $PIDS 2>/dev/null || true
        fi
    done

    # Wait for ports to free up
    sleep 2

    # Force-kill anything still lingering
    for port in 6274 6278 8000; do
        PIDS=$(fuser "${port}/tcp" 2>/dev/null | xargs)
        if [ -n "$PIDS" ]; then
            kill -9 $PIDS 2>/dev/null || true
        fi
    done
    sleep 1
    echo "Stopped."
}

_start() {
    local MODE="${1:-dev}"

    if _is_running; then
        echo "Server already running (PID $(cat "$PIDFILE")). Use './mcp.sh restart $MODE' instead."
        exit 1
    fi

    case "$MODE" in
        dev)
            echo "Starting MCP Inspector (web UI)..."
            DANGEROUSLY_OMIT_AUTH=true ALLOWED_ORIGINS="https://demo.redix.com:6275,http://localhost:6274,http://127.0.0.1:6274" fastmcp dev server.py --server-port 6278 > "$LOGFILE" 2>&1 &
            echo $! > "$PIDFILE"
            sleep 8
            if _is_running; then
                # Extract the URL with token from logs
                URL=$(grep -o 'http://localhost:6274/[^ ]*' "$LOGFILE" | head -1)
                echo ""
                echo "  MCP Inspector running!"
                echo "  UI:    ${URL:-http://localhost:6274}"
                echo "  Proxy: http://localhost:6278 (nginx HTTPS on :6277)"
                echo "  Logs:  $LOGFILE"
                echo ""
            else
                echo "Failed to start. Check logs:"
                tail -20 "$LOGFILE"
                rm -f "$PIDFILE"
                exit 1
            fi
            ;;
        sse)
            local PORT="${2:-8000}"
            echo "Starting SSE server on port $PORT..."
            fastmcp run server.py -t sse --host 0.0.0.0 --port "$PORT" > "$LOGFILE" 2>&1 &
            echo $! > "$PIDFILE"
            sleep 3
            if _is_running; then
                echo ""
                echo "  SSE server running!"
                echo "  Endpoint: http://0.0.0.0:$PORT/sse"
                echo "  Logs:     $LOGFILE"
                echo ""
            else
                echo "Failed to start. Check logs:"
                tail -20 "$LOGFILE"
                rm -f "$PIDFILE"
                exit 1
            fi
            ;;
        http)
            local PORT="${2:-8000}"
            echo "Starting HTTP server on port $PORT..."
            fastmcp run server.py -t streamable-http --host 0.0.0.0 --port "$PORT" > "$LOGFILE" 2>&1 &
            echo $! > "$PIDFILE"
            sleep 3
            if _is_running; then
                echo ""
                echo "  HTTP server running!"
                echo "  Endpoint: http://0.0.0.0:$PORT/mcp"
                echo "  Logs:     $LOGFILE"
                echo ""
            else
                echo "Failed to start. Check logs:"
                tail -20 "$LOGFILE"
                rm -f "$PIDFILE"
                exit 1
            fi
            ;;
        stdio)
            echo "Starting STDIO server (foreground — Ctrl+C to stop)..."
            python3.11 server.py
            ;;
        *)
            echo "Unknown mode: $MODE"
            echo "Available: dev, sse, http, stdio"
            exit 1
            ;;
    esac
}

_status() {
    echo ""
    echo "  Redix MCP Server Status"
    echo "  ───────────────────────"
    if _is_running; then
        PID=$(cat "$PIDFILE")
        echo "  Running:  Yes (PID $PID)"
    else
        echo "  Running:  No"
    fi
    echo ""
    echo "  Listening ports:"
    for port in 6274 6277 6278 8000; do
        PID=$(fuser "${port}/tcp" 2>/dev/null | xargs)
        if [ -n "$PID" ]; then
            case $port in
                6274) DESC="MCP Inspector UI" ;;
                6277) DESC="MCP Inspector Proxy (nginx)" ;;
                6278) DESC="MCP Inspector Proxy (node)" ;;
                8000) DESC="SSE/HTTP server" ;;
            esac
            echo "    :$port  $DESC (PID $PID)"
        fi
    done
    echo ""
    echo "  API base: $REDIX_API_BASE"
    echo "  Logs:     $LOGFILE"
    echo ""
}

# ── main ─────────────────────────────────────────────────────

case "${1:-help}" in
    start)   _start "$2" "$3" ;;
    stop)    _stop ;;
    restart) _stop; sleep 2; _start "${2:-dev}" "$3" ;;
    status)  _status ;;
    test)    python3.11 tests/test_tools.py ;;
    logs)    tail -f "$LOGFILE" ;;
    help|*)
        echo ""
        echo "  Redix MCP Server"
        echo "  ────────────────"
        echo "  ./mcp.sh start [mode]    Start (dev|sse|http|stdio)"
        echo "  ./mcp.sh stop            Stop all instances"
        echo "  ./mcp.sh restart [mode]  Restart"
        echo "  ./mcp.sh status          Show status and ports"
        echo "  ./mcp.sh test            Run end-to-end tests"
        echo "  ./mcp.sh logs            Tail server logs"
        echo ""
        echo "  Modes:"
        echo "    dev    MCP Inspector web UI at :6274 (default)"
        echo "    sse    SSE server at :8000"
        echo "    http   HTTP server at :8000"
        echo "    stdio  STDIO for Claude Desktop/Code"
        echo ""
        ;;
esac
