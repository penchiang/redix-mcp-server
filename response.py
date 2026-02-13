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
