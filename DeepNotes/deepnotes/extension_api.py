"""Additive Chrome integration. The original API/launcher remain unchanged.

Run: python -m uvicorn deepnotes.extension_api:create_app --factory --host 127.0.0.1
Set DEEPNOTES_EXTENSION_ID to the ID shown by chrome://extensions first.
"""
import os
import re
from urllib.parse import urlsplit

from starlette.responses import JSONResponse, Response
from .api import create_app as create_original_app
from .config import Settings

ID_PATTERN = re.compile(r"[a-p]{32}\Z")
IDENTITY_HEADER = b"x-deepnotes-extension"
BRIDGE_HEADER = b"x-deepnotes-extension-bridge"


class ExtensionOriginAdapter:
    """Grant one explicit extension access, then preserve the existing API policy.

The extension ID is public, NOT a secret authentication token. This is a browser
origin boundary for a local single-user service, not protection against local
programs that can already call the original API without an Origin header.
"""
    def __init__(self, app, extension_id):
        self.app = app
        self.extension_id = extension_id
        self.origin = f"chrome-extension://{extension_id}" if extension_id else None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        pairs = scope.get("headers", [])
        headers = {key.lower(): value.decode("latin-1") for key, value in pairs}
        origin = headers.get(b"origin")
        identity = headers.get(IDENTITY_HEADER)
        preflight = scope["method"] == "OPTIONS" and b"access-control-request-method" in headers
        extension_request = identity is not None or (origin or "").startswith("chrome-extension://")
        if not extension_request:
            # Other origins receive exactly the original application's policy.
            await self.app(scope, receive, send)
            return

        async def reject(message, status=403):
            await JSONResponse({"detail": message}, status_code=status, headers={"Cache-Control": "no-store"})(scope, receive, send)

        if not self.extension_id:
            await reject("Extension access is not configured. Set DEEPNOTES_EXTENSION_ID and restart the extension-aware launcher.", 503)
            return
        if any(sum(key.lower() == name for key, _ in pairs) > 1 for name in (b"origin", IDENTITY_HEADER)):
            await reject("Duplicate extension identity or Origin headers are not allowed")
            return
        if origin is not None and origin != self.origin:
            await reject("This browser origin is not allowed")
            return
        if not preflight and identity != self.extension_id:
            await reject("Extension ID does not match DEEPNOTES_EXTENSION_ID")
            return
        if preflight and origin != self.origin:
            await reject("Preflight requires the configured extension origin")
            return
        try:
            host = urlsplit("http://" + headers.get(b"host", ""))
            host_valid = host.hostname in ("127.0.0.1", "localhost", "::1") and host.username is None and host.password is None
            # Accessing .port also rejects malformed/out-of-range ports.
            host.port
        except ValueError:
            host_valid = False
        if not host_valid:
            await reject("The extension adapter only serves a loopback host")
            return
        if not scope.get("path", "").startswith("/api/"):
            await reject("Extension access is limited to /api/ routes")
            return
        if scope["method"] not in ("GET", "POST", "OPTIONS"):
            await reject("Extension request method is not allowed")
            return

        cors = {"Access-Control-Allow-Origin": self.origin,
                "Access-Control-Expose-Headers": "X-DeepNotes-Extension-Bridge",
                "Vary": "Origin", "Cache-Control": "no-store",
                "X-DeepNotes-Extension-Bridge": "1"}
        if preflight:
            method = headers.get(b"access-control-request-method", "").upper()
            requested = {item.strip().lower() for item in headers.get(b"access-control-request-headers", "").split(",") if item.strip()}
            if method not in ("GET", "POST") or not requested <= {"content-type", "x-deepnotes-extension", "accept"}:
                await reject("Preflight method or headers are not allowed")
                return
            cors.update({"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                         "Access-Control-Allow-Headers": "Content-Type, X-DeepNotes-Extension, Accept"})
            if headers.get(b"access-control-request-private-network") == "true":
                cors["Access-Control-Allow-Private-Network"] = "true"
            await Response(status_code=204, headers=cors)(scope, receive, send)
            return

        # Only after exact identity/origin/host/path validation, remove Origin so
        # the original same-origin middleware can handle this trusted addition.
        # Host, content-type validation, request bodies, routes and persistence
        # remain untouched. Ordinary website requests never take this branch.
        inner_scope = dict(scope)
        inner_scope["headers"] = [(key, value) for key, value in pairs if key.lower() not in (b"origin", IDENTITY_HEADER)]

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                replacement = {key.lower().encode(): value.encode() for key, value in cors.items()}
                original = list(message.get("headers", []))
                vary = next((value.decode() for key, value in original if key.lower() == b"vary"), "")
                if vary and "origin" not in {part.strip().lower() for part in vary.split(",")}:
                    replacement[b"vary"] = (vary + ", Origin").encode()
                message["headers"] = [(key, value) for key, value in original if key.lower() not in replacement] + list(replacement.items())
            await send(message)

        await self.app(inner_scope, receive, send_with_cors)


def create_app(settings=None, model=None, start_worker=True, extension_id=None):
    settings = settings or Settings.from_env()
    extension_id = (os.getenv("DEEPNOTES_EXTENSION_ID", "") if extension_id is None else extension_id).strip()
    if extension_id and not ID_PATTERN.fullmatch(extension_id):
        raise ValueError("DEEPNOTES_EXTENSION_ID must be the 32 lowercase a-p characters shown in chrome://extensions")
    app = create_original_app(settings=settings, model=model, start_worker=start_worker)
    app.add_middleware(ExtensionOriginAdapter, extension_id=extension_id)
    return app
