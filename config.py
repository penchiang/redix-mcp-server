"""Configuration for Redix MCP Server."""

import os

REDIX_API_BASE = os.environ.get("REDIX_API_BASE", "http://localhost:8080")
REDIX_API_KEY = os.environ.get("REDIX_API_KEY", "demo-key-12345")
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "120"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
