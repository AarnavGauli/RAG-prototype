"""Domain errors and the consistent ``{"error": {...}}`` response structure."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "file_too_large"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class ProviderError(AppError):
    """Raised by embedding/LLM providers. Messages must never contain secrets."""

    status_code = 502
    code = "provider_error"


class ProviderNotConfigured(ProviderError):
    status_code = 503
    code = "provider_not_configured"


class PdfRejected(AppError):
    status_code = 422
    code = "invalid_pdf"


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    return {"error": body}
