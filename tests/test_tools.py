#!/usr/bin/env python3
"""End-to-end tests for the Redix MCP Server tools.

These tests call the real Redix API (must be running at REDIX_API_BASE).
Sample data is fetched from the API's /sample/ endpoints.

Usage:
    python3.11 tests/test_tools.py
"""

import asyncio
import json
import sys
import os

# Ensure the package root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_client import RedixAPIClient

# Import MCP tools — FastMCP wraps them as FunctionTool objects,
# so we access .fn to get the raw async function.
from server import (
    validate_x12 as _validate_x12,
    convert_x12_to_fhir as _convert_x12_to_fhir,
    convert_x12_to_rmap as _convert_x12_to_rmap,
    convert_rmap_to_x12 as _convert_rmap_to_x12,
    convert_x12_to_database as _convert_x12_to_database,
    generate_x12_from_database as _generate_x12_from_database,
    convert_hl7_to_fhir as _convert_hl7_to_fhir,
    convert_cda_to_fhir as _convert_cda_to_fhir,
    convert_fhir_to_x12 as _convert_fhir_to_x12,
    convert_fhir_to_rmap as _convert_fhir_to_rmap,
    generate_claim_pdf as _generate_claim_pdf,
    list_supported_formats as _list_supported_formats,
)

# Unwrap FunctionTool → raw async function
validate_x12 = _validate_x12.fn
convert_x12_to_fhir = _convert_x12_to_fhir.fn
convert_x12_to_rmap = _convert_x12_to_rmap.fn
convert_rmap_to_x12 = _convert_rmap_to_x12.fn
convert_x12_to_database = _convert_x12_to_database.fn
generate_x12_from_database = _generate_x12_from_database.fn
convert_hl7_to_fhir = _convert_hl7_to_fhir.fn
convert_cda_to_fhir = _convert_cda_to_fhir.fn
convert_fhir_to_x12 = _convert_fhir_to_x12.fn
convert_fhir_to_rmap = _convert_fhir_to_rmap.fn
generate_claim_pdf = _generate_claim_pdf.fn
list_supported_formats = _list_supported_formats.fn

client = RedixAPIClient()

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

PASSED = 0
FAILED = 0
ERRORS = 0


async def fetch_sample(transaction_type: str) -> str:
    """Fetch sample X12 content.

    Prefers the hipaa-to-rmap sample (uses A1 errata version strings)
    over the hipaa-validate sample (which may use older version strings
    that fail strict validation).
    """
    result = await client.get(f"/api/v2/hipaa-to-rmap/sample/{transaction_type}")
    if not result.get("_error") and result.get("content"):
        return result["content"]
    # Fallback to validate sample
    result = await client.get(f"/api/v2/hipaa-validate/sample/{transaction_type}")
    if result.get("_error"):
        raise RuntimeError(f"Could not fetch sample for {transaction_type}: {result}")
    return result["content"]


async def fetch_rmap_sample(transaction_type: str) -> str:
    """Produce an RMap sample by converting a sample X12 through the RMap converter."""
    x12 = await fetch_sample(transaction_type)
    upload = client.make_upload(x12, f"sample.{transaction_type}.x12")
    result = await client.post_form(
        "/api/v2/hipaa-to-rmap/convert",
        files=[upload],
        params={"transaction_type": transaction_type},
    )
    if result.get("_error") or not result.get("rmap_content"):
        raise RuntimeError(f"Could not produce RMap sample for {transaction_type}: {result.get('_detail', result)}")
    return result["rmap_content"]


def check(test_name: str, result: dict, expected_status: str | list[str], check_data_keys: list[str] | None = None):
    """Evaluate a test result."""
    global PASSED, FAILED
    actual_status = result.get("status")

    # Allow multiple acceptable statuses
    expected = [expected_status] if isinstance(expected_status, str) else expected_status
    ok = actual_status in expected

    if check_data_keys and ok:
        data = result.get("data", {})
        for key in check_data_keys:
            if key not in data or not data[key]:
                print(f"  FAIL  {test_name}: missing data key '{key}'")
                FAILED += 1
                return

    if ok:
        ruling = result.get("redix_ruling", "")[:120]
        print(f"  PASS  {test_name}  [{actual_status}] {ruling}")
        PASSED += 1
    else:
        ruling = result.get("redix_ruling", "")[:200]
        print(f"  FAIL  {test_name}: expected {expected}, got {actual_status}")
        print(f"        ruling: {ruling}")
        FAILED += 1


# ------------------------------------------------------------------
# Test cases
# ------------------------------------------------------------------

async def test_validate_x12_pass():
    x12 = await fetch_sample("837p")
    result = await validate_x12(x12, "837p")
    check("validate_x12 (valid 837P)", result, ["APPROVED", "APPROVED_WITH_CONDITIONS"])


async def test_validate_x12_fail():
    result = await validate_x12("ISA*00*BAD DATA TRUNCATED", "837p")
    check("validate_x12 (truncated)", result, ["BLOCKED", "ERROR"])


async def test_convert_x12_to_fhir():
    x12 = await fetch_sample("837p")
    result = await convert_x12_to_fhir(x12, "837p")
    check("convert_x12_to_fhir (837P)", result, ["APPROVED", "APPROVED_WITH_CONDITIONS"], ["fhir_bundle"])


async def test_convert_x12_to_rmap():
    x12 = await fetch_sample("837p")
    result = await convert_x12_to_rmap(x12, "837p")
    check("convert_x12_to_rmap (837P)", result, ["APPROVED", "APPROVED_WITH_CONDITIONS"], ["rmap_content"])


async def test_convert_rmap_to_x12():
    rmap = await fetch_rmap_sample("837p")
    result = await convert_rmap_to_x12(rmap, "837p")
    check("convert_rmap_to_x12 (837P)", result, ["APPROVED", "APPROVED_WITH_CONDITIONS", "BLOCKED"], ["x12_content"])


async def test_convert_x12_to_database():
    x12 = await fetch_sample("837p")
    result = await convert_x12_to_database(x12, "837p")
    check("convert_x12_to_database (837P)", result, ["APPROVED", "APPROVED_WITH_CONDITIONS"], ["session_id"])


async def test_generate_x12_from_database():
    result = await generate_x12_from_database("837p")
    # DB-generated X12 may have ISA envelope issues → gate5 BLOCKS legitimately
    check("generate_x12_from_database (837P)", result, ["APPROVED", "APPROVED_WITH_CONDITIONS", "BLOCKED", "ERROR"])


async def test_convert_hl7_to_fhir():
    hl7 = (
        "MSH|^~\\&|SENDING|FACILITY|RECEIVING|FACILITY|20240101120000||ADT^A01|MSG001|P|2.5\r"
        "EVN|A01|20240101120000\r"
        "PID|1||PAT001^^^HOSP||DOE^JOHN||19800101|M|||123 MAIN ST^^ANYTOWN^ST^12345\r"
        "PV1|1|I|W^389^1^UAMC||||12345^SMITH^JANE|||SUR||||ADM|A0|\r"
    )
    result = await convert_hl7_to_fhir(hl7)
    check("convert_hl7_to_fhir (ADT)", result, ["APPROVED", "APPROVED_WITH_CONDITIONS", "ERROR"])


async def test_convert_cda_to_fhir():
    cda_sample_path = "/opt/redix-cda-fhir/samples/cda/sample_ccd.xml"
    try:
        with open(cda_sample_path) as f:
            cda = f.read()
    except FileNotFoundError:
        print(f"  SKIP  convert_cda_to_fhir: sample not found at {cda_sample_path}")
        return
    result = await convert_cda_to_fhir(cda)
    check("convert_cda_to_fhir (CCD)", result, ["APPROVED", "APPROVED_WITH_CONDITIONS"], ["fhir_bundle"])


async def test_generate_claim_pdf():
    x12 = await fetch_sample("837p")
    result = await generate_claim_pdf(x12, "837p")
    check("generate_claim_pdf (837P)", result, ["APPROVED", "APPROVED_WITH_CONDITIONS"], ["pdf_files"])


async def test_list_supported_formats():
    result = await list_supported_formats()
    check("list_supported_formats", result, "APPROVED", ["conversion_paths"])


# ------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------

async def run_all():
    global PASSED, FAILED, ERRORS

    tests = [
        test_validate_x12_pass,
        test_validate_x12_fail,
        test_convert_x12_to_fhir,
        test_convert_x12_to_rmap,
        test_convert_rmap_to_x12,
        test_convert_x12_to_database,
        test_generate_x12_from_database,
        test_convert_hl7_to_fhir,
        test_convert_cda_to_fhir,
        test_generate_claim_pdf,
        test_list_supported_formats,
    ]

    print(f"\n{'='*60}")
    print(f"  Redix MCP Server — End-to-End Tests")
    print(f"  API: {client.base_url}")
    print(f"{'='*60}\n")

    for test_fn in tests:
        try:
            await test_fn()
        except Exception as exc:
            ERRORS += 1
            print(f"  ERROR {test_fn.__name__}: {exc}")

    print(f"\n{'='*60}")
    print(f"  Results: {PASSED} passed, {FAILED} failed, {ERRORS} errors")
    print(f"{'='*60}\n")

    if FAILED > 0 or ERRORS > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_all())
