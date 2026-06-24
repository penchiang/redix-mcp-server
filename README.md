# Redix AnyToAny MCP Server

A developer sandbox for the **Redix AnyToAny healthcare data conversion engine**, exposed to AI clients (Claude Desktop, Claude Code, Cursor, and any MCP-compatible agent) over the Model Context Protocol.

Point your AI client at this server and ask it, in plain language, to validate an X12 claim, turn an 837 into a FHIR R4 Bundle, render a CMS-1500 PDF, or map an HL7 v2 message - and watch the Redix engine do it, with validation gates that block bad conversions instead of silently passing them.

## What this is (and is not)

This server is an **interactive evaluation and debugging surface** for the Redix conversion engine. It is the fastest way to see what the engine does to your data before you write a line of integration code.

It is **not** a production pipeline. Healthcare conversion at volume runs through the deterministic **Redix REST API** (the same engine this server wraps), under a Redix license. When you have seen enough here, that is where you go next:

- REST API and tools: <https://demo.redix.com>
- Production licensing: ppc@redix.com

## Tools (11)

| Tool | Description | Validation gate |
|------|-------------|-----------------|
| `validate_x12` | Validate HIPAA X12 against 5010 implementation-guide rules | is the gate |
| `convert_x12_to_fhir` | X12 -> FHIR R4 Bundle | Gate 1 (input) |
| `convert_x12_to_rmap` | X12 -> RMap v5 intermediate | Gate 1 (input) |
| `convert_rmap_to_x12` | RMap v5 -> X12 | Gate 5 (output) |
| `convert_x12_to_database` | X12 -> relational DB tables | Gate 1 (input) |
| `generate_x12_from_database` | DB -> X12 | Gate 5 (output) |
| `convert_hl7_to_fhir` | HL7 v2 -> FHIR R4 | - |
| `convert_cda_to_fhir` | CDA / C-CDA -> FHIR R4 | - |
| `convert_fhir_to_rmap` | FHIR -> RMap v5 (inspect the intermediate mapping) | - |
| `generate_claim_pdf` | X12 837 -> PDF (CMS-1500 / UB-04 / ADA J400) | Gate 1 (input) |
| `list_supported_formats` | Capability discovery (no key needed) | - |

> **Reverse FHIR-to-X12 (278)** is intentionally not exposed in this sandbox. External, provider-generated PAS bundles do not yet ingest cleanly end to end, so it is unfit for unattended use where a failure would look like an engine defect. It remains available through the REST API under a short private technical review - email ppc@redix.com.

## Quick start - hosted (no install)

Point your MCP client at the hosted demo server. It runs with a sample-only demo key, so you can try every tool against Redix sample files immediately.

### Streamable HTTP (recommended)

```json
{
  "mcpServers": {
    "redix-anytoany": {
      "url": "https://demo.redix.com/mcp",
      "env": { "REDIX_API_KEY": "demo-key-12345" }
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
      "env": { "REDIX_API_KEY": "demo-key-12345" }
    }
  }
}
```

## Evaluating with your own data

The published `demo-key-12345` is **sample-only**: it converts Redix sample files so you can see each tool work, but it will not process your own files. This protects healthcare data and keeps the demo a controlled technical evaluation.

When you send your own data, a tool returns a clear `EVAL_KEY_REQUIRED` response telling you exactly where to request a **free, tool-scoped evaluation key** - for example, the X12 validator points you to <https://demo.redix.com/tools/validate>. Submit the short "request an evaluation key" form on that page (or email ppc@redix.com); Redix issues a scoped key by email, usually for a 7-day evaluation. Then set `REDIX_API_KEY` to that key and rerun.

Use test or de-identified data for evaluation. Do not upload production PHI to the demo server.

## Setup - local (self-hosted)

```bash
pip install -r requirements.txt
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIX_API_BASE` | `http://localhost:8080` | Redix API base URL |
| `REDIX_API_KEY` | `demo-key-12345` | API authentication key |
| `REQUEST_TIMEOUT` | `120` | HTTP timeout in seconds |
| `LOG_LEVEL` | `INFO` | Python logging level |

### Running locally

```bash
# STDIO mode (Claude Desktop / Claude Code)
python3.11 server.py

# Streamable HTTP mode (multi-client)
fastmcp run server.py --transport streamable-http --port 8001

# SSE mode (multi-client)
fastmcp run server.py --transport sse --port 8000

# MCP Inspector (browser UI)
fastmcp dev server.py
```

## Claude Code integration

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

## Claude Desktop integration

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

## How it works

Each tool is a thin wrapper over the Redix AnyToAny REST API. Conversions are bracketed by validation gates:

- **Gate 1 (input)** validates X12 against 5010 rules before converting. A malformed claim is refused, not silently mangled.
- **Gate 5 (output)** re-validates X12 that a tool generates, so you never get back EDI that would bounce at a payer.

Transaction types are auto-detected from content when you do not specify them.

## Testing

```bash
python3.11 tests/test_tools.py
```

Requires the Redix API running at `REDIX_API_BASE`. Note: against the hosted demo (sample-only key, 3-second rate limit) many cases return `EVAL_KEY_REQUIRED` or rate-limit errors by design; run the suite against a local API with an evaluation key for full coverage.
