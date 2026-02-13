"""REST API client for calling the Redix AnyToAny engine."""

import logging
from typing import Any, Optional

import httpx

from config import REDIX_API_BASE, REDIX_API_KEY, REQUEST_TIMEOUT

logger = logging.getLogger("redix-mcp")


class RedixAPIClient:
    """Thin HTTP client wrapping the Redix AnyToAny REST API.

    Three methods match the API's input patterns:
      - post_form: multipart/form-data (most conversions accept file uploads)
      - post_json: JSON body (validation, FHIR-to-HIPAA)
      - get: query-string only (supported-transactions, samples)
    """

    def __init__(
        self,
        base_url: str = REDIX_API_BASE,
        api_key: str = REDIX_API_KEY,
        timeout: int = REQUEST_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {
            "Accept": "application/json",
            "X-Submission-Method": "mcp",
        }
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    # ------------------------------------------------------------------
    # POST multipart/form-data
    # ------------------------------------------------------------------
    async def post_form(
        self,
        endpoint: str,
        files: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, str]] = None,
    ) -> dict:
        """POST with multipart/form-data.

        ``files`` is passed directly to httpx — use the tuple format
        ``("filename", content, "mime/type")`` for in-memory uploads.
        ``data`` contains plain form fields.
        ``params`` are query-string parameters.
        """
        url = f"{self.base_url}{endpoint}"
        logger.info("POST form %s params=%s", url, params)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    url,
                    headers=self._headers(),
                    files=files,
                    data=data,
                    params=params,
                )
                resp.raise_for_status()
                # Some endpoints return plain text (database-to-hipaa)
                content_type = resp.headers.get("content-type", "")
                if "application/json" in content_type:
                    return resp.json()
                return {"_raw_text": resp.text, "_status_code": resp.status_code}
        except httpx.HTTPStatusError as exc:
            logger.error("HTTP %s from %s: %s", exc.response.status_code, url, exc.response.text[:500])
            return self._error_dict(exc.response.status_code, exc.response.text, url)
        except httpx.RequestError as exc:
            logger.error("Request error for %s: %s", url, exc)
            return self._error_dict(0, str(exc), url)

    # ------------------------------------------------------------------
    # POST JSON body
    # ------------------------------------------------------------------
    async def post_json(
        self,
        endpoint: str,
        json_body: Optional[dict | list | str] = None,
        params: Optional[dict[str, str]] = None,
    ) -> dict:
        """POST with a JSON body (and optional query params)."""
        url = f"{self.base_url}{endpoint}"
        logger.info("POST json %s params=%s", url, params)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    url,
                    headers=self._headers(),
                    json=json_body,
                    params=params,
                )
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                if "application/json" in content_type:
                    return resp.json()
                return {"_raw_text": resp.text, "_status_code": resp.status_code}
        except httpx.HTTPStatusError as exc:
            logger.error("HTTP %s from %s: %s", exc.response.status_code, url, exc.response.text[:500])
            return self._error_dict(exc.response.status_code, exc.response.text, url)
        except httpx.RequestError as exc:
            logger.error("Request error for %s: %s", url, exc)
            return self._error_dict(0, str(exc), url)

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------
    async def get(
        self,
        endpoint: str,
        params: Optional[dict[str, str]] = None,
    ) -> dict:
        """GET with optional query params."""
        url = f"{self.base_url}{endpoint}"
        logger.info("GET %s params=%s", url, params)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    url,
                    headers=self._headers(),
                    params=params,
                )
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                if "application/json" in content_type:
                    return resp.json()
                return {"_raw_text": resp.text, "_status_code": resp.status_code}
        except httpx.HTTPStatusError as exc:
            logger.error("HTTP %s from %s: %s", exc.response.status_code, url, exc.response.text[:500])
            return self._error_dict(exc.response.status_code, exc.response.text, url)
        except httpx.RequestError as exc:
            logger.error("Request error for %s: %s", url, exc)
            return self._error_dict(0, str(exc), url)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _error_dict(status_code: int, detail: str, url: str) -> dict:
        return {
            "_error": True,
            "_status_code": status_code,
            "_detail": detail[:2000],
            "_url": url,
        }

    @staticmethod
    def make_upload(content: str, filename: str = "input.txt", mime: str = "text/plain"):
        """Wrap a string as an in-memory file tuple for httpx multipart upload."""
        return ("file", (filename, content.encode("utf-8"), mime))
