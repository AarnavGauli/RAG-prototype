"""Owner (browser-session) isolation, rate limiting, request-size limiting and security headers.

The owner cookie is a random 128-bit *capability token*, not authentication. It separates the data of different
browsers on the same install; it is not a substitute for real user accounts.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, Request, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.context import AppContext
from app.errors import RateLimited, error_body

COOKIE_NAME = "pdfi_session"
_COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{22,64}$")


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_owner(request: Request, response: Response, ctx: AppContext = Depends(get_ctx)) -> str:
    token = request.cookies.get(COOKIE_NAME, "")
    if not _COOKIE_RE.match(token):
        token = secrets.token_urlsafe(16)
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            samesite="lax",
            secure=ctx.settings.cookie_secure,
            path="/",
        )
    return token


class RateLimiter:
    """Sliding-window limiter, in-process (documented development-safe equivalent; use a proxy in production)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        if self.per_minute <= 0:
            return
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                retry = int(60 - (now - q[0])) + 1
                raise RateLimited(f"Too many requests. Try again in {retry}s.", details={"retry_after": retry})
            q.append(now)


def rate_limit(request: Request, owner: str = Depends(get_owner)) -> None:
    request.app.state.limiter.check(f"{owner}:{request.url.path}")


class _TooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Rejects oversized request bodies (declared or streamed) before they are fully buffered."""

    def __init__(self, app: ASGIApp, upload_limit: int, json_limit: int) -> None:
        self.app = app
        self.upload_mb = upload_limit // (1024 * 1024)
        self.upload_limit = upload_limit + 64 * 1024  # multipart framing overhead
        self.json_limit = json_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS", "DELETE"):
            await self.app(scope, receive, send)
            return
        is_upload = scope["path"].rstrip("/").endswith("/documents") and scope["method"] == "POST"
        limit = self.upload_limit if is_upload else self.json_limit
        declared = dict(scope["headers"]).get(b"content-length")
        started = False

        async def too_large() -> None:
            import json

            message = (
                f"The file exceeds the {self.upload_mb} MB upload limit."
                if is_upload
                else "The request body is too large."
            )
            body = json.dumps(error_body("file_too_large" if is_upload else "request_too_large", message)).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                }
            )
            await send({"type": "http.response.body", "body": body})

        if declared and declared.isdigit() and int(declared) > limit:
            await too_large()
            return
        seen = 0

        async def limited_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await too_large()


class SecurityHeadersMiddleware:
    HEADERS = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cross-origin-resource-policy", b"same-site"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    ]

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        docs = path.startswith(("/docs", "/redoc", "/openapi"))

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}
                for k, v in self.HEADERS:
                    if k not in existing:
                        headers.append((k, v))
                if not docs:
                    headers.append((b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"))
                if b"cache-control" not in existing:
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped)
