"""Redix AnyToAny MCP Server — 11 healthcare data conversion tools.

Exposes the Redix AnyToAny REST API to AI agents via the Model Context
Protocol.  Each tool is a thin wrapper: validate → convert → re-validate.

Run:
    python server.py              # STDIO mode (Claude Desktop / Claude Code)
    fastmcp run server.py --transport sse --port 8000   # HTTP/SSE mode
"""

import json
import logging
from typing import Optional

from fastmcp import FastMCP

from api_client import RedixAPIClient
from config import LOG_LEVEL
from gates import gate1_input_validation, gate5_output_validation
from response import build_response

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("redix-mcp")

# ---------------------------------------------------------------------------
# MCP server + shared API client
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "Redix AnyToAny",
    instructions=(
        "Healthcare data conversion and compliance tools. "
        "Converts between HIPAA X12, FHIR R4, HL7 v2, RMap, database, "
        "and PDF claim forms — with built-in validation gates that may "
        "BLOCK unsafe conversions."
    ),
)
client = RedixAPIClient()

# ---------------------------------------------------------------------------
# Transaction type mapping: short codes → HIPAA-to-FHIR endpoint enum values
# ---------------------------------------------------------------------------
_FHIR_TX_MAP = {
    "837p": "837-professional",
    "837i": "837-institutional",
    "837d": "837-dental",
    "835": "835-remittance",
    "834": "834-enrollment",
    "270": "270-eligibility",
    "271": "271-eligibility",
    "276": "276-claim-status",
    "277": "277-claim-status",
    "278": "278-request",
    "278-request": "278-request",
    "278-response": "278-response",
    # Pass through values that are already in the right format
    "837-professional": "837-professional",
    "837-institutional": "837-institutional",
    "837-dental": "837-dental",
    "835-remittance": "835-remittance",
    "834-enrollment": "834-enrollment",
    "270-eligibility": "270-eligibility",
    "271-eligibility": "271-eligibility",
    "276-claim-status": "276-claim-status",
    "277-claim-status": "277-claim-status",
}


def _fhir_tx(transaction_type: Optional[str]) -> Optional[str]:
    """Map short transaction type codes to HIPAA-to-FHIR endpoint values."""
    if not transaction_type:
        return None
    return _FHIR_TX_MAP.get(transaction_type.lower(), transaction_type)


# ===================================================================
# Tool 1: validate_x12
# ===================================================================

@mcp.tool()
async def validate_x12(
    x12_content: str,
    transaction_type: Optional[str] = None,
) -> dict:
    """Validate HIPAA X12 EDI content against 5010 implementation guide rules.

    Supported transaction types: 837P, 837I, 837D, 835, 834, 270, 271, 276,
    277, 278. Auto-detected from content if not specified.

    Returns APPROVED if the X12 passes all validation levels (syntax,
    inter-segment, balancing). Returns APPROVED_WITH_CONDITIONS if there are
    warnings only. Returns BLOCKED if there are structural or data errors.

    The response includes TA1 acknowledgment, 999 acknowledgment with
    IK3/IK4 error details, and a balance report when applicable.

    Args:
        x12_content: Raw X12 EDI content starting with ISA segment.
        transaction_type: HIPAA transaction type. Auto-detected if omitted.

    Returns:
        dict with status, redix_ruling, and full validation details.
    """
    json_body: dict = {"content": x12_content}
    if transaction_type:
        json_body["transaction_type"] = transaction_type

    result = await client.post_json(
        "/api/v2/hipaa-validate/validate-content",
        json_body=json_body,
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=f"Validation service error: HTTP {result.get('_status_code')}. {result.get('_detail', '')[:300]}",
        )

    validation_status = result.get("validation_status", "UNKNOWN")
    errors_obj = result.get("errors", {})
    has_errors = errors_obj.get("has_errors", False)
    has_warnings = errors_obj.get("has_warnings", False)
    error_count = errors_obj.get("error_count", 0)
    warning_count = errors_obj.get("warning_count", 0)
    error_lines = errors_obj.get("error_lines", [])
    error_desc = result.get("error_code_description", "")

    data = {
        "validation_status": validation_status,
        "transaction_type": result.get("transaction_type"),
        "transaction_name": result.get("transaction_name"),
        "error_count": error_count,
        "warning_count": warning_count,
        "validation_levels": result.get("validation_levels"),
        "ta1": result.get("ta1"),
        "ack999": result.get("ack999"),
        "balance_report": result.get("balance_report"),
    }

    if validation_status == "FAILED" or has_errors:
        detail = "; ".join(str(l) for l in error_lines[:5])
        return build_response(
            status="BLOCKED",
            ruling=(
                f"Validation FAILED with {error_count} error(s). "
                f"{error_desc}. Details: {detail}"
            ),
            data=data,
            errors=error_lines,
            gate="validation",
        )

    if has_warnings:
        return build_response(
            status="APPROVED_WITH_CONDITIONS",
            ruling=(
                f"Validation PASSED with {warning_count} warning(s). "
                f"The X12 is structurally valid but review the warnings."
            ),
            data=data,
            warnings=error_lines,
            gate="validation",
        )

    return build_response(
        status="APPROVED",
        ruling=(
            f"Validation PASSED. The {result.get('transaction_name') or transaction_type or 'X12'} "
            f"X12 content is structurally valid with no errors or warnings."
        ),
        data=data,
        gate="validation",
    )


# ===================================================================
# Tool 2: convert_x12_to_fhir
# ===================================================================

@mcp.tool()
async def convert_x12_to_fhir(
    x12_content: str,
    transaction_type: Optional[str] = None,
    strict_mode: bool = False,
) -> dict:
    """Convert HIPAA X12 EDI to FHIR R4 resources with compliance checking.

    Supported transaction types: 837P, 837I, 837D, 835, 834, 270, 271, 276,
    277, 278. Auto-detected from content if not specified.

    This tool applies two compliance gates:
    1. Gate 1 — Input validation (5010 rules). BLOCKS if X12 is malformed.
    2. Conversion via Redix 30-year production engine.

    May return BLOCKED if:
    - Input fails 5010 structural validation (missing segments, bad delimiters)
    - Required data elements missing (NPI, Tax ID, etc.)
    - In strict_mode, even warnings block

    Args:
        x12_content: Raw X12 EDI content with ISA/GS/ST envelope.
        transaction_type: HIPAA transaction type. Auto-detected if omitted.
        strict_mode: If True, validation warnings also block (default False).

    Returns:
        dict with status, redix_ruling, and data containing the FHIR Bundle.
    """
    # Gate 1: input validation
    blocked = await gate1_input_validation(client, x12_content, transaction_type, strict_mode)
    if blocked:
        return blocked

    # Conversion — HIPAA-to-FHIR uses long-form transaction type names
    filename = f"input.{transaction_type}.x12" if transaction_type else "input.x12"
    upload = client.make_upload(x12_content, filename)
    params: dict[str, str] = {}
    if transaction_type:
        params["transaction_type"] = _fhir_tx(transaction_type)
    result = await client.post_form(
        "/api/v2/hipaa-to-fhir/convert",
        files=[upload],
        params=params if params else None,
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=f"X12-to-FHIR conversion failed: HTTP {result.get('_status_code')}. {result.get('_detail', '')[:300]}",
        )

    warnings = result.get("warnings", [])
    detected_tx = result.get("transaction_type", transaction_type)
    status = "APPROVED_WITH_CONDITIONS" if warnings else "APPROVED"
    tx_label = (transaction_type or detected_tx or "").upper() or "X12"
    ruling = (
        f"X12 {tx_label} successfully converted to FHIR R4 Bundle."
        + (f" {len(warnings)} warning(s) noted." if warnings else "")
    )

    return build_response(
        status=status,
        ruling=ruling,
        data={
            "fhir_bundle": result.get("fhir_bundle") or result.get("fhir_output") or result,
            "transaction_type": detected_tx,
            "metadata": result.get("metadata"),
        },
        warnings=warnings,
    )


# ===================================================================
# Tool 3: convert_x12_to_rmap
# ===================================================================

@mcp.tool()
async def convert_x12_to_rmap(
    x12_content: str,
    transaction_type: Optional[str] = None,
    strict_mode: bool = False,
) -> dict:
    """Convert HIPAA X12 EDI to RMap v5 intermediate format.

    RMap is Redix's intermediate representation — a human-readable,
    field-level record layout with 100% fidelity to the original X12.
    Useful for debugging, auditing, and round-trip conversions.

    Supported types: 837P, 837I, 837D, 835, 834, 270, 271, 276, 277, 278.
    Auto-detected from content if not specified.

    Gate 1 (input validation) is applied. BLOCKS if X12 is malformed.

    Args:
        x12_content: Raw X12 EDI content.
        transaction_type: HIPAA transaction type. Auto-detected if omitted.
        strict_mode: If True, validation warnings also block.

    Returns:
        dict with status, redix_ruling, and data containing RMap content
        plus parsed record structure.
    """
    blocked = await gate1_input_validation(client, x12_content, transaction_type, strict_mode)
    if blocked:
        return blocked

    filename = f"input.{transaction_type}.x12" if transaction_type else "input.x12"
    upload = client.make_upload(x12_content, filename)
    params: dict[str, str] = {}
    if transaction_type:
        params["transaction_type"] = transaction_type
    result = await client.post_form(
        "/api/v2/hipaa-to-rmap/convert",
        files=[upload],
        params=params if params else None,
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=f"X12-to-RMap conversion failed: HTTP {result.get('_status_code')}. {result.get('_detail', '')[:300]}",
        )

    warnings = result.get("warnings", [])
    parsed = result.get("rmap_parsed", {})
    record_count = parsed.get("record_count", 0)
    detected_tx = result.get("transaction_type", transaction_type)
    tx_label = (transaction_type or detected_tx or "").upper() or "X12"
    status = "APPROVED_WITH_CONDITIONS" if warnings else "APPROVED"

    return build_response(
        status=status,
        ruling=(
            f"X12 {tx_label} converted to RMap v5 with "
            f"{record_count} record(s)."
            + (f" {len(warnings)} warning(s)." if warnings else "")
        ),
        data={
            "rmap_content": result.get("rmap_content"),
            "rmap_parsed": parsed,
            "metadata": result.get("metadata"),
        },
        warnings=warnings,
    )


# ===================================================================
# Tool 4: convert_rmap_to_x12
# ===================================================================

@mcp.tool()
async def convert_rmap_to_x12(
    rmap_content: str,
    transaction_type: Optional[str] = None,
) -> dict:
    """Convert RMap v5 intermediate format to HIPAA X12 EDI.

    RMap is Redix's human-readable record layout. This tool converts it
    back to compliant X12 and then validates its own output (Gate 5).

    Supported types: 837P, 837I, 837D, 835, 834, 270, 271, 276, 277, 278.
    Auto-detected from RMap content if not specified.

    Gate 5 (output validation) is applied. BLOCKS if the generated X12
    fails validation — this means the source RMap may be incomplete.
    DO NOT submit blocked output to payers.

    Args:
        rmap_content: RMap v5 text content.
        transaction_type: Target HIPAA transaction type. Auto-detected if omitted.

    Returns:
        dict with status, redix_ruling, and data containing X12 content.
    """
    filename = f"input.{transaction_type}.rmap" if transaction_type else "input.rmap"
    upload = client.make_upload(rmap_content, filename)
    params: dict[str, str] = {}
    if transaction_type:
        params["transaction_type"] = transaction_type
    result = await client.post_form(
        "/api/v2/rmap-to-hipaa/convert",
        files=[upload],
        params=params if params else None,
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=f"RMap-to-X12 conversion failed: HTTP {result.get('_status_code')}. {result.get('_detail', '')[:300]}",
        )

    # Response may use "x12_content" or "hipaa_content" depending on endpoint version
    x12_output = result.get("x12_content") or result.get("hipaa_content", "")
    if not x12_output:
        return build_response(
            status="ERROR",
            ruling="RMap-to-X12 conversion returned empty X12 content.",
        )

    # Gate 5: re-validate our own output
    gate5 = await gate5_output_validation(client, x12_output, transaction_type, "convert_rmap_to_x12")
    if gate5:
        gate5["data"]["x12_content"] = x12_output
        return gate5

    warnings = result.get("warnings", [])
    detected_tx = result.get("transaction_type", transaction_type)
    tx_label = (transaction_type or detected_tx or "").upper() or "X12"
    status = "APPROVED_WITH_CONDITIONS" if warnings else "APPROVED"

    return build_response(
        status=status,
        ruling=(
            f"RMap converted to {tx_label} X12 and passed output validation."
            + (f" {len(warnings)} warning(s)." if warnings else "")
        ),
        data={
            "x12_content": x12_output,
            "metadata": result.get("metadata"),
        },
        warnings=warnings,
    )


# ===================================================================
# Tool 5: convert_x12_to_database
# ===================================================================

@mcp.tool()
async def convert_x12_to_database(
    x12_content: str,
    transaction_type: Optional[str] = None,
    session_id: Optional[str] = None,
    strict_mode: bool = False,
) -> dict:
    """Load HIPAA X12 EDI into a relational database for querying.

    Parses the X12 into structured database tables (claims, subscribers,
    service lines, etc.) scoped to a session. Returns the session_id and
    table summary. Use the session_id to later generate X12 back from the
    database with generate_x12_from_database.

    Supported types: 837P, 835, 834. Auto-detected from content if not
    specified.

    Gate 1 (input validation) is applied. BLOCKS if X12 is invalid —
    loading invalid data creates downstream problems.

    Args:
        x12_content: Raw X12 EDI content.
        transaction_type: HIPAA transaction type. Auto-detected if omitted.
        session_id: Optional session ID for table scoping (auto-generated if omitted).
        strict_mode: If True, validation warnings also block.

    Returns:
        dict with status, redix_ruling, session_id, and table summary.
    """
    blocked = await gate1_input_validation(client, x12_content, transaction_type, strict_mode)
    if blocked:
        return blocked

    filename = f"input.{transaction_type}.x12" if transaction_type else "input.x12"
    upload = client.make_upload(x12_content, filename)
    form_data: dict = {}
    if transaction_type:
        form_data["transaction_type"] = transaction_type
    if session_id:
        form_data["session_id"] = session_id

    result = await client.post_form(
        "/api/v2/hipaa-to-database/load",
        files=[upload],
        data=form_data,
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=f"X12-to-database load failed: HTTP {result.get('_status_code')}. {result.get('_detail', '')[:300]}",
        )

    if not result.get("success"):
        return build_response(
            status="ERROR",
            ruling=f"Database load failed: {result.get('error', 'unknown error')}",
            data=result,
        )

    stage2 = result.get("stage2", {})
    warnings = result.get("warnings", [])
    status = "APPROVED_WITH_CONDITIONS" if warnings else "APPROVED"

    return build_response(
        status=status,
        ruling=(
            f"X12 {(transaction_type or result.get('transaction_type') or '').upper() or 'X12'} "
            f"loaded into database session '{result.get('session_id')}'. "
            f"{stage2.get('tables_created', 0)} tables created, "
            f"{stage2.get('total_rows', 0)} total rows."
            + (f" {len(warnings)} warning(s)." if warnings else "")
        ),
        data={
            "session_id": result.get("session_id"),
            "transaction_type": result.get("transaction_type"),
            "tables_created": stage2.get("tables_created"),
            "tables_with_data": stage2.get("tables_with_data"),
            "total_rows": stage2.get("total_rows"),
            "table_counts": stage2.get("table_counts"),
        },
        warnings=warnings,
    )


# ===================================================================
# Tool 6: generate_x12_from_database
# ===================================================================

@mcp.tool()
async def generate_x12_from_database(
    transaction_type: Optional[str] = None,
    record_id: Optional[int] = None,
) -> dict:
    """Generate HIPAA X12 EDI from database records.

    Pulls structured data from the Redix database and converts it to
    compliant X12 via a two-stage pipeline (DB → RMap → X12).

    Supported types: 837P, 835, 834. Auto-detected if not specified.

    Gate 5 (output validation) is applied. BLOCKS if the generated X12
    fails validation. DO NOT submit blocked output to payers.

    Args:
        transaction_type: HIPAA transaction type. Auto-detected if omitted.
        record_id: Database record ID to fetch (uses default if omitted).

    Returns:
        dict with status, redix_ruling, and generated X12 content.
    """
    params: dict[str, str] = {}
    if transaction_type:
        params["transaction_type"] = transaction_type
    if record_id is not None:
        params["record_id"] = str(record_id)

    result = await client.post_json(
        "/api/v2/database-to-hipaa/convert",
        params=params,
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=f"Database-to-X12 generation failed: HTTP {result.get('_status_code')}. {result.get('_detail', '')[:300]}",
        )

    if not result.get("success"):
        return build_response(
            status="ERROR",
            ruling=f"Database-to-X12 generation failed: {result.get('error', 'unknown')}",
            data=result,
        )

    x12_output = result.get("stage2_rmap_to_hipaa", {}).get("hipaa_content", "")
    if not x12_output:
        return build_response(
            status="ERROR",
            ruling="Database-to-X12 generation returned empty X12 content.",
        )

    # Gate 5: re-validate our own output
    gate5 = await gate5_output_validation(client, x12_output, transaction_type, "generate_x12_from_database")
    if gate5:
        gate5["data"]["x12_content"] = x12_output
        return gate5

    return build_response(
        status="APPROVED",
        ruling=(
            f"X12 {(transaction_type or result.get('transaction_type') or '').upper() or 'X12'} "
            f"generated from database record {record_id or '(default)'} and passed output validation."
        ),
        data={
            "x12_content": x12_output,
            "transaction_type": result.get("transaction_type"),
            "metadata": result.get("metadata"),
        },
    )


# ===================================================================
# Tool 7: convert_hl7_to_fhir
# ===================================================================

@mcp.tool()
async def convert_hl7_to_fhir(
    hl7_content: str,
) -> dict:
    """Convert HL7 v2.x messages or CDA/C-CDA XML to FHIR R4 resources.

    Auto-detects the input type (HL7 v2 pipe-delimited, CDA XML, C-CDA XML).
    Supported HL7 v2 message types: ADT, ORM, ORU, SIU, MDM, VXU, RDE,
    DFT, BAR, ACK, MFN, and others. Also handles CCD, CDA, and C-CDA.

    No X12 validation gate is applied (this is HL7, not X12).

    Args:
        hl7_content: Raw HL7 v2.x message (pipe-delimited) or CDA/C-CDA XML.

    Returns:
        dict with status, redix_ruling, and FHIR R4 Bundle.
    """
    result = await client.post_form(
        "/api/v2/ai/hl7-convert",
        data={"content": hl7_content},
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=f"HL7-to-FHIR conversion failed: HTTP {result.get('_status_code')}. {result.get('_detail', '')[:300]}",
        )

    if not result.get("success", True):
        return build_response(
            status="ERROR",
            ruling=f"HL7-to-FHIR conversion failed: {result.get('error', 'unknown error')}",
            data=result,
        )

    fhir_bundle = result.get("fhir_bundle", {})
    resource_count = result.get("resource_count", 0)
    message_type = result.get("message_type", "unknown")

    return build_response(
        status="APPROVED",
        ruling=(
            f"HL7 {message_type} converted to FHIR R4 Bundle with "
            f"{resource_count} resource(s)."
        ),
        data={
            "fhir_bundle": fhir_bundle,
            "message_type": message_type,
            "resource_count": resource_count,
            "processing_time_ms": result.get("processing_time_ms"),
        },
    )


# ===================================================================
# Tool 8: convert_cda_to_fhir
# ===================================================================

@mcp.tool()
async def convert_cda_to_fhir(
    cda_content: str,
) -> dict:
    """Convert CDA or C-CDA clinical documents to FHIR R4 resources.

    Accepts CDA (Clinical Document Architecture) and C-CDA (Consolidated CDA)
    XML documents — including CCD (Continuity of Care Documents), discharge
    summaries, progress notes, and other clinical document types.

    The converter extracts patient demographics, problems, medications,
    allergies, procedures, results, and other clinical sections into
    corresponding FHIR R4 resources.

    No X12 validation gate is applied (this is CDA, not X12).

    Args:
        cda_content: CDA or C-CDA XML document content.

    Returns:
        dict with status, redix_ruling, and FHIR R4 Bundle.
    """
    result = await client.post_form(
        "/api/v2/ai/hl7-convert",
        data={"content": cda_content},
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=f"CDA-to-FHIR conversion failed: HTTP {result.get('_status_code')}. {result.get('_detail', '')[:300]}",
        )

    if not result.get("success", True):
        return build_response(
            status="ERROR",
            ruling=f"CDA-to-FHIR conversion failed: {result.get('error', 'unknown error')}",
            data=result,
        )

    fhir_bundle = result.get("fhir_bundle", {})
    resource_count = result.get("resource_count") or len(fhir_bundle.get("entry", []))
    message_type = result.get("message_type", "CDA")

    return build_response(
        status="APPROVED",
        ruling=(
            f"{message_type} document converted to FHIR R4 Bundle with "
            f"{resource_count} resource(s)."
        ),
        data={
            "fhir_bundle": fhir_bundle,
            "document_type": message_type,
            "resource_count": resource_count,
            "processing_time_ms": result.get("processing_time_ms"),
        },
    )


# ===================================================================
# Tool 9: convert_fhir_to_x12
# ===================================================================

@mcp.tool()
async def convert_fhir_to_x12(
    fhir_bundle: str,
) -> dict:
    """Convert a FHIR R4 Bundle to HIPAA X12 EDI (278 Prior Authorization).

    Accepts a FHIR Bundle containing a Claim resource with
    use="preauthorization" (278 Request) or a ClaimResponse (278 Response).
    The FHIR content must follow the Da Vinci PAS profile.

    Gate 5 (output validation) is applied — the generated X12 is
    re-validated. BLOCKS if the output fails validation.

    Args:
        fhir_bundle: FHIR R4 Bundle as a JSON string. Must contain a
            Claim (preauthorization) or ClaimResponse resource.

    Returns:
        dict with status, redix_ruling, and X12 278 content.
    """
    try:
        bundle_obj = json.loads(fhir_bundle) if isinstance(fhir_bundle, str) else fhir_bundle
    except json.JSONDecodeError as exc:
        return build_response(
            status="ERROR",
            ruling=f"Invalid JSON in fhir_bundle: {exc}",
        )

    result = await client.post_json(
        "/api/v2/fhir-to-hipaa/convert",
        json_body=bundle_obj,
        params={"output_format": "x12"},
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=f"FHIR-to-X12 conversion failed: HTTP {result.get('_status_code')}. {result.get('_detail', '')[:300]}",
        )

    x12_output = result.get("x12_output", "")
    if not x12_output:
        return build_response(
            status="ERROR",
            ruling="FHIR-to-X12 conversion returned empty X12 content.",
            data=result,
        )

    # Gate 5: re-validate generated X12
    gate5 = await gate5_output_validation(client, x12_output, "278", "convert_fhir_to_x12")
    if gate5:
        gate5["data"]["x12_content"] = x12_output
        return gate5

    warnings = result.get("warnings", [])
    status = "APPROVED_WITH_CONDITIONS" if warnings else "APPROVED"
    conv_type = result.get("conversion_type", "278")

    return build_response(
        status=status,
        ruling=(
            f"FHIR Bundle converted to X12 {conv_type} and passed output validation."
            + (f" {len(warnings)} warning(s)." if warnings else "")
        ),
        data={
            "x12_content": x12_output,
            "conversion_type": conv_type,
            "metadata": result.get("metadata"),
        },
        warnings=warnings,
    )


# ===================================================================
# Tool 10: convert_fhir_to_rmap
# ===================================================================

@mcp.tool()
async def convert_fhir_to_rmap(
    fhir_bundle: str,
) -> dict:
    """Convert a FHIR R4 Bundle to RMap v5 intermediate format.

    Uses the same FHIR-to-HIPAA engine but returns only the intermediate
    RMap representation instead of full X12. Useful for inspecting the
    field-level mapping before generating X12.

    Accepts FHIR Bundles containing Claim (preauthorization) or
    ClaimResponse resources (Da Vinci PAS profile).

    No output validation gate — RMap is an intermediate format.

    Args:
        fhir_bundle: FHIR R4 Bundle as a JSON string.

    Returns:
        dict with status, redix_ruling, and RMap content.
    """
    try:
        bundle_obj = json.loads(fhir_bundle) if isinstance(fhir_bundle, str) else fhir_bundle
    except json.JSONDecodeError as exc:
        return build_response(
            status="ERROR",
            ruling=f"Invalid JSON in fhir_bundle: {exc}",
        )

    result = await client.post_json(
        "/api/v2/fhir-to-hipaa/convert",
        json_body=bundle_obj,
        params={"output_format": "rmap"},
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=f"FHIR-to-RMap conversion failed: HTTP {result.get('_status_code')}. {result.get('_detail', '')[:300]}",
        )

    rmap_output = result.get("rmap_output", "")
    warnings = result.get("warnings", [])
    status = "APPROVED_WITH_CONDITIONS" if warnings else "APPROVED"

    return build_response(
        status=status,
        ruling=(
            f"FHIR Bundle converted to RMap intermediate format."
            + (f" {len(warnings)} warning(s)." if warnings else "")
        ),
        data={
            "rmap_content": rmap_output,
            "metadata": result.get("metadata"),
        },
        warnings=warnings,
    )


# ===================================================================
# Tool 11: generate_claim_pdf
# ===================================================================

@mcp.tool()
async def generate_claim_pdf(
    x12_837_content: str,
    claim_type: str = "auto",
    strict_mode: bool = False,
) -> dict:
    """Generate PDF claim forms (CMS-1500, UB-04, ADA J400) from X12 837.

    Accepts 837P (→ CMS-1500), 837I (→ UB-04), or 837D (→ ADA J400) and
    produces downloadable PDF files — one per claim in the X12.

    Gate 1 (input validation) is applied. BLOCKS if the source 837 has
    validation errors — generating a claim form from invalid data creates
    legal liability.

    The response contains download URLs, not binary PDF content.

    Args:
        x12_837_content: Raw X12 837 EDI content.
        claim_type: "837p", "837i", "837d", or "auto" for detection.
        strict_mode: If True, validation warnings also block.

    Returns:
        dict with status, redix_ruling, PDF download URLs, and metadata.
    """
    # Determine transaction type for validation
    tx_type = claim_type if claim_type != "auto" else "837p"
    blocked = await gate1_input_validation(client, x12_837_content, tx_type, strict_mode)
    if blocked:
        return blocked

    upload = client.make_upload(x12_837_content, "claim.x12")
    params: dict[str, str] = {}
    if claim_type != "auto":
        params["claim_type"] = claim_type

    result = await client.post_form(
        "/api/v2/claims-to-pdf/convert",
        files=[upload],
        params=params,
    )

    if result.get("_error"):
        return build_response(
            status="ERROR",
            ruling=f"Claims-to-PDF conversion failed: HTTP {result.get('_status_code')}. {result.get('_detail', '')[:300]}",
        )

    pdf_files = result.get("pdf_files", [])
    form_name = result.get("form_name", "unknown")

    return build_response(
        status="APPROVED",
        ruling=(
            f"Generated {len(pdf_files)} {form_name} PDF claim form(s). "
            f"Download via the URLs in the response."
        ),
        data={
            "claim_type": result.get("claim_type"),
            "form_name": form_name,
            "pdf_count": result.get("pdf_count", len(pdf_files)),
            "pdf_files": pdf_files,
            "zip_download_url": result.get("zip_download_url"),
            "conversion_id": result.get("conversion_id"),
        },
    )


# ===================================================================
# Tool 12: list_supported_formats
# ===================================================================

@mcp.tool()
async def list_supported_formats() -> dict:
    """List all supported conversion formats, transaction types, and capabilities.

    Returns a manifest of every conversion path the Redix AnyToAny engine
    supports, including: HIPAA X12 transaction types (837P, 835, 834, etc.),
    HL7 v2 message types (ADT, ORU, etc.), FHIR profiles, RMap, database,
    and PDF claim forms.

    No gates applied — this is a capability discovery tool.

    Returns:
        dict with supported transaction types grouped by conversion pipeline.
    """
    endpoints = [
        ("hipaa_validate", "/api/v2/hipaa-validate/supported-transactions"),
        ("hipaa_to_rmap", "/api/v2/hipaa-to-rmap/supported-transactions"),
        ("hipaa_to_fhir", "/api/v2/hipaa-to-fhir/supported-transactions"),
        ("database_to_hipaa", "/api/v2/database-to-hipaa/transaction-types"),
    ]

    manifest: dict = {}
    for key, endpoint in endpoints:
        result = await client.get(endpoint)
        if not result.get("_error"):
            manifest[key] = result

    manifest["conversion_paths"] = [
        "X12 → FHIR R4 (hipaa-to-fhir)",
        "X12 → RMap v5 (hipaa-to-rmap)",
        "RMap v5 → X12 (rmap-to-hipaa)",
        "X12 → Database (hipaa-to-database)",
        "Database → X12 (database-to-hipaa)",
        "FHIR R4 → X12 278 (fhir-to-hipaa)",
        "FHIR R4 → RMap v5 (fhir-to-hipaa?output_format=rmap)",
        "HL7 v2 / CDA → FHIR R4 (ai/hl7-convert)",
        "X12 837 → PDF claim forms (claims-to-pdf)",
    ]

    manifest["compliance_gates"] = {
        "gate1_input_validation": "Validates X12 input before conversion (5010 rules)",
        "gate5_output_validation": "Re-validates generated X12 output before returning",
    }

    return build_response(
        status="APPROVED",
        ruling="Capability manifest retrieved. See data for all supported formats and conversion paths.",
        data=manifest,
    )


# ===================================================================
# Main entry point
# ===================================================================

if __name__ == "__main__":
    mcp.run()
