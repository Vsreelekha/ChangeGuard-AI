"""ASGI request-body cap for multipart project uploads."""

from starlette.responses import JSONResponse
from threading import Lock

MULTIPART_REQUEST_OVERHEAD_BYTES = 1024 * 1024


class _UploadBodyTooLarge(Exception):
    pass


class ProjectUploadLimitMiddleware:
    """Bound actual request bytes before Starlette spools multipart uploads."""

    def __init__(self, app, *, path: str, max_request_bytes: int, max_concurrent_uploads: int = 2) -> None:
        self.app = app
        self.path = path
        self.max_request_bytes = max_request_bytes
        self.max_concurrent_uploads = max_concurrent_uploads
        self._active_uploads = 0
        self._active_lock = Lock()

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or scope.get("method") != "POST" or scope.get("path") != self.path:
            await self.app(scope, receive, send)
            return

        with self._active_lock:
            capacity_full = self._active_uploads >= self.max_concurrent_uploads
            if not capacity_full:
                self._active_uploads += 1
        if capacity_full:
            response = JSONResponse(
                status_code=429,
                content={"error": "Project upload capacity is busy; retry later.", "status_code": 429, "details": {}},
            )
            await response(scope, receive, send)
            return

        received_bytes = 0
        response_started = False

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_request_bytes:
                    raise _UploadBodyTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _UploadBodyTooLarge:
            if not response_started:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": "Project upload request exceeds the configured size limit.",
                        "status_code": 413,
                        "details": {},
                    },
                )
                await response(scope, receive, send)
        finally:
            with self._active_lock:
                self._active_uploads -= 1
