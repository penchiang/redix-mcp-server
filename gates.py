"""Compliance gates for Redix MCP Server.

V1 implements two gates:
  Gate 1 — Input Validation: validates X12 content before conversion.
  Gate 5 — Output Validation: re-validates X12 content produced by conversion.

Gates 2-4 (regulatory currency, clinical plausibility, temporal) are deferred
to V2 — they require new API endpoints that don't exist yet.
"""

import logging
from typing import Optional

from api_client import RedixAPIClient
from response import build_response

logger = logging.getLogger("redix-mcp")

VALIDATE_ENDPOINT = "/api/v2/hipaa-validate/validate-content"


async def gate1_input_validation(
    client: RedixAPIClient,
    x12_content: str,
    transaction_type: Optional[str] = None,
    strict_mode: bool = False,
) -> Optional[dict]:
    """Gate 1: Validate X12 input before conversion.

    Returns a BLOCKED response dict if validation fails, or None if passed.
    When ``strict_mode`` is True, warnings also block.
    Transaction type is auto-detected from content if not specified.
    """
    json_body: dict = {"content": x12_content}
    if transaction_type:
        json_body["transaction_type"] = transaction_type

    result = await client.post_json(
        VALIDATE_ENDPOINT,
        json_body=json_body,
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=(
                f"Gate 1 (input validation) could not reach the validation service. "
                f"HTTP {result.get('_status_code')}: {result.get('_detail', 'unknown error')[:300]}"
            ),
            gate="gate1_input_validation",
        )

    validation_status = result.get("validation_status", "UNKNOWN")
    errors_obj = result.get("errors", {})
    has_errors = errors_obj.get("has_errors", False)
    has_warnings = errors_obj.get("has_warnings", False)
    error_count = errors_obj.get("error_count", 0)
    warning_count = errors_obj.get("warning_count", 0)
    error_lines = errors_obj.get("error_lines", [])
    error_desc = result.get("error_code_description", "")

    # FAILED or has errors → BLOCK
    if validation_status == "FAILED" or has_errors:
        summary_lines = error_lines[:5]
        detail = "; ".join(str(l) for l in summary_lines)
        return build_response(
            status="BLOCKED",
            ruling=(
                f"Conversion REFUSED. Input X12 has {error_count} validation error(s). "
                f"{error_desc}. Details: {detail}"
            ),
            errors=error_lines,
            warnings=[],
            gate="gate1_input_validation",
            data={
                "validation_status": validation_status,
                "error_count": error_count,
                "warning_count": warning_count,
            },
        )

    # WARNING with strict_mode → BLOCK
    if (validation_status == "WARNING" or has_warnings) and strict_mode:
        return build_response(
            status="BLOCKED",
            ruling=(
                f"Conversion REFUSED (strict mode). Input X12 has {warning_count} warning(s). "
                f"Disable strict_mode or fix warnings before retrying."
            ),
            warnings=error_lines,
            gate="gate1_input_validation",
            data={
                "validation_status": validation_status,
                "warning_count": warning_count,
            },
        )

    # PASSED (possibly with non-blocking warnings)
    return None


async def gate5_output_validation(
    client: RedixAPIClient,
    x12_output: str,
    transaction_type: Optional[str] = None,
    source_tool: str = "unknown",
) -> Optional[dict]:
    """Gate 5: Re-validate X12 output produced by a conversion tool.

    Returns an APPROVED_WITH_CONDITIONS or BLOCKED response if the generated
    X12 has issues, or None if it passes cleanly.
    Transaction type is auto-detected from content if not specified.
    """
    json_body: dict = {"content": x12_output}
    if transaction_type:
        json_body["transaction_type"] = transaction_type

    result = await client.post_json(
        VALIDATE_ENDPOINT,
        json_body=json_body,
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=(
                f"Gate 5 (output validation) could not re-validate the generated X12. "
                f"HTTP {result.get('_status_code')}: {result.get('_detail', 'unknown error')[:300]}"
            ),
            gate="gate5_output_validation",
        )

    validation_status = result.get("validation_status", "UNKNOWN")
    errors_obj = result.get("errors", {})
    has_errors = errors_obj.get("has_errors", False)
    error_count = errors_obj.get("error_count", 0)
    warning_count = errors_obj.get("warning_count", 0)
    error_lines = errors_obj.get("error_lines", [])
    error_desc = result.get("error_code_description", "")

    if validation_status == "FAILED" or has_errors:
        return build_response(
            status="BLOCKED",
            ruling=(
                f"X12 was generated by {source_tool} but FAILED output validation "
                f"with {error_count} error(s). {error_desc}. "
                f"The source data may be incomplete. DO NOT submit this to payers."
            ),
            errors=error_lines,
            gate="gate5_output_validation",
            data={"validation_status": validation_status, "error_count": error_count},
        )

    # Clean pass
    return None
