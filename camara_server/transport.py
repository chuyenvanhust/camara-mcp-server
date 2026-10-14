from .diagnostics import operation
from starlette.requests import Request
from starlette.responses import JSONResponse


class TransportMiddleware:
    """Pure ASGI middleware preserves request cancellation and streaming semantics."""
    def __init__(self, app, config):
        self.app, self.config = app, config

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/health":
            return await self._handle(scope, receive, send)
        path = scope.get("path", "")
        stage = "mcp" if path == "/mcp" else "other"
        async with operation("http.request", method=scope.get("method"), stage=stage) as log:
            async def capture(message):
                if message["type"] == "http.response.start":
                    status = message["status"]
                    log.update(status=status, outcome="error" if status >= 400 else "ok")
                await send(message)
            return await self._handle(scope, receive, capture)

    async def _handle(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        allowed_hosts = set(self.config.allowed_hosts)
        response = None
        if request.headers.get("host") not in allowed_hosts:
            response = JSONResponse({"error": "invalid_host"}, status_code=403)
        elif request.headers.get("origin") and request.headers["origin"] not in self.config.allowed_origins:
            response = JSONResponse({"error": "invalid_origin"}, status_code=403)
        if response:
            return await response(scope, receive, send)
        # Bound bodies including chunked transfer without trusting Content-Length.
        if scope["method"] == "POST":
            limit = 65536
            chunks = []
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                size += len(message.get("body", b""))
                if size > limit:
                    return await JSONResponse({"error": "request_too_large"}, status_code=413)(scope, receive, send)
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            body = b"".join(chunks)
            delivered = False
            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()
            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)
