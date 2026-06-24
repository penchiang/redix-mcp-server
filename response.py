"""Standardized response builder for all MCP tool responses.

Every tool response carries a ``redix_ruling`` — a plain-English sentence that
an AI agent can relay directly to its user.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional


def build_response(
    status: str,
    ruling: str,
    data: Optional[dict[str, Any]] = None,
    errors: Optional[list] = None,
    warnings: Optional[list] = None,
    gate: Optional[str] = None,
    transaction_id: Optional[str] = None,
) -> dict:
    """Build a standardized Redix MCP response.

    Parameters
    ----------
    status : str
        One of APPROVED, APPROVED_WITH_CONDITIONS, BLOCKED, ERROR.
    ruling : str
        Plain-English explanation for AI agents.  Be specific — include
        counts, segment references, and actionable next steps.
    data : dict, optional
        Conversion output (FHIR bundle, RMap content, X12 text, etc.).
    errors : list, optional
        Blocking issues that caused BLOCKED status.
    warnings : list, optional
        Non-blocking issues (informational).
    gate : str, optional
        Which compliance gate produced this ruling.
    transaction_id : str, optional
        Unique audit ID (auto-generated if omitted).
    """
    return {
        "status": status,
        "redix_ruling": ruling,
        "gate": gate,
        "transaction_id": transaction_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data or {},
        "errors": errors or [],
        "warnings": warnings or [],
    }


# ---------------------------------------------------------------------------
# Evaluation-key doorway
# ---------------------------------------------------------------------------
# The hosted server runs with the public demo key, which the REST API scope
# gate treats as sample-only: Redix sample files convert, your own files get
# HTTP 403 {"error":"evaluation_key_required"}. Web tools turn that marker into
# a doorway modal; an MCP client has no modal, so we surface the same doorway
# in the tool response — pointing the developer at the exact /tools/<slug> page
# where the request auto-issues a scoped key (unified 2026-06-23).
_DOORWAY_BASE = "https://demo.redix.com/tools"

# Failing endpoint path fragment -> (tools slug, eval scope, friendly label).
# Slugs/scopes are the authoritative map from routers/leads.py (_SLUG_SCOPE).
_DOORWAY_MAP = [
    ("/api/v2/hipaa-validate",    "validate",     "validate",   "the HIPAA X12 validator"),
    ("/api/v2/hipaa-to-fhir",     "x12-to-fhir",  "fhir",       "X12 to FHIR"),
    ("/api/v2/hipaa-to-rmap",     "x12-to-rmap",  "legacy_edi", "X12 to RMap"),
    ("/api/v2/rmap-to-hipaa",     "rmap-to-x12",  "legacy_edi", "RMap to X12"),
    ("/api/v2/hipaa-to-database", "load-db",      "legacy_edi", "load X12 to database"),
    ("/api/v2/database-to-hipaa", "db-to-x12",    "legacy_edi", "database to X12"),
    ("/api/v2/ai/hl7-convert",    "hl7",          "hl7",        "HL7 / CDA to FHIR"),
    ("/api/v2/fhir-to-hipaa",     "fhir-to-rmap", "fhir",       "FHIR to RMap"),
    ("/api/v2/claims-to-pdf",     "claims-pdf",   "claims_pdf", "claims to PDF"),
]


def eval_key_doorway(result: dict) -> Optional[dict]:
    """Return a doorway response if an API error is the sample-only scope gate.

    The hosted demo key only processes Redix sample files. When a developer
    sends their own data the REST API returns HTTP 403 with an
    ``evaluation_key_required`` marker. This converts that into a clear,
    actionable MCP response telling them exactly where to request a free,
    tool-scoped evaluation key. Returns ``None`` for any other error so the
    caller keeps its normal error handling.
    """
    if not result.get("_error") or result.get("_status_code") != 403:
        return None
    if "evaluation_key_required" not in (result.get("_detail") or ""):
        return None

    url = result.get("_url") or ""
    slug = scope = label = None
    for fragment, s, sc, lbl in _DOORWAY_MAP:
        if fragment in url:
            slug, scope, label = s, sc, lbl
            break

    # ?ref=mcp tags the click so MCP-originated eval requests are
    # distinguishable from plain web-tool requests (nginx access log at
    # minimum; the lead funnel can later read it into the source). Without
    # it the 90-day "leads attributable to MCP" measurement is blind.
    base = f"{_DOORWAY_BASE}/{slug}" if slug else _DOORWAY_BASE
    request_url = f"{base}?ref=mcp"
    tool_label = label or "this tool"
    return build_response(
        status="EVAL_KEY_REQUIRED",
        ruling=(
            f"The Redix demo key processes Redix sample files only. To run "
            f"{tool_label} on your own data, request a free evaluation key "
            f"(scope: {scope or 'tool-specific'}). Open {request_url}, submit "
            f"the 'request an evaluation key' form, and Redix issues a scoped "
            f"key by email; then set REDIX_API_KEY to that key. You can also "
            f"email ppc@redix.com."
        ),
        data={
            "eval_key_request_url": request_url,
            "scope": scope,
            "tool": tool_label,
            "demo_key_is_sample_only": True,
        },
        gate="scope_gate",
    )
