# Redix AnyToAny MCP Server

MCP server that exposes the Redix AnyToAny healthcare data conversion engine to AI agents via the Model Context Protocol.

## Tools (12)

| Tool | Description | Gates |
|------|-------------|-------|
| `validate_x12` | Validate HIPAA X12 against 5010 rules | IS the gate |
| `convert_x12_to_fhir` | X12 → FHIR R4 Bundle | Gate 1 (input) |
| `convert_x12_to_rmap` | X12 → RMap v5 | Gate 1 (input) |
| `convert_rmap_to_x12` | RMap v5 → X12 | Gate 5 (output) |
| `convert_x12_to_database` | X12 → relational DB tables | Gate 1 (input) |
| `generate_x12_from_database` | DB → X12 | Gate 5 (output) |
| `convert_hl7_to_fhir` | HL7 v2 → FHIR R4 | — |
| `convert_cda_to_fhir` | CDA / C-CDA → FHIR R4 | — |
| `convert_fhir_to_x12` | FHIR → X12 278 | Gate 5 (output) |
| `convert_fhir_to_rmap` | FHIR → RMap v5 | — |
| `generate_claim_pdf` | X12 837 → PDF (CMS-1500/UB-04/ADA) | Gate 1 (input) |
| `list_supported_formats` | Capability discovery | — |

## Quick Start — Remote (Hosted)

Connect to the hosted demo server — no installation required.

### Streamable HTTP (recommended)

```json
{
  "mcpServers": {
    "redix-anytoany": {
      "url": "https://demo.redix.com/mcp",
      "env": {
        "REDIX_API_KEY": "demo-key-12345"
      }
    }
  }
}
```

### SSE

```json
{
  "mcpServers": {
    "redix-anytoany": {
      "url": "https://demo.redix.com/sse",
      "env": {
        "REDIX_API_KEY": "demo-key-12345"
      }
    }
  }
}
```

## Setup — Local (Self-Hosted)

```bash
pip install -r requirements.txt
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIX_API_BASE` | `http://localhost:8080` | Redix API base URL |
| `REDIX_API_KEY` | `demo-key-12345` | API authentication key |
| `REQUEST_TIMEOUT` | `120` | HTTP timeout in seconds |
| `LOG_LEVEL` | `INFO` | Python logging level |

### Running Locally

#### STDIO mode (Claude Desktop / Claude Code)

```bash
python3.11 server.py
```

#### Streamable HTTP mode (multi-client)

```bash
fastmcp run server.py --transport streamable-http --port 8000
```

#### SSE mode (multi-client)

```bash
fastmcp run server.py --transport sse --port 8000
```

#### MCP Inspector

```bash
fastmcp dev server.py
```

## Claude Code Integration

Copy `.mcp.json` to your project root, or add to Claude Code settings:

```json
{
  "mcpServers": {
    "redix-anytoany": {
      "command": "python3.11",
      "args": ["server.py"],
      "cwd": "/opt/MCP/redix-mcp-server",
      "env": {
        "REDIX_API_BASE": "http://localhost:8080",
        "REDIX_API_KEY": "demo-key-12345"
      }
    }
  }
}
```

## Claude Desktop Integration

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "redix-anytoany": {
      "command": "python3.11",
      "args": ["/opt/MCP/redix-mcp-server/server.py"],
      "env": {
        "REDIX_API_BASE": "http://localhost:8080",
        "REDIX_API_KEY": "demo-key-12345"
      }
    }
  }
}
```

## Testing

```bash
python3.11 tests/test_tools.py
```

Requires the Redix API to be running at the configured `REDIX_API_BASE`.
