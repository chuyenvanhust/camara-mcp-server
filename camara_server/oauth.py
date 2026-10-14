from .diagnostics import operation
import base64
import binascii
import hmac
import re
import time
from urllib.parse import parse_qs, unquote
from uuid import uuid4
import jwt
from starlette.requests import Request
from starlette.responses import JSONResponse
from camara_server.config import ServerConfig


def endpoints(config: ServerConfig):
    c = config.bridge

    async def resource_metadata(request):
        return JSONResponse({"resource": c.resource, "authorization_servers": [c.issuer],
                             "scopes_supported": c.scope.split(), "bearer_methods_supported": ["header"]})

    async def server_metadata(request):
        return JSONResponse({"issuer": c.issuer, "token_endpoint": c.token_url,
            "grant_types_supported": ["client_credentials"], "scopes_supported": c.scope.split(),
            "token_endpoint_auth_methods_supported": ["client_secret_basic"], "response_types_supported": []})

    async def token(request: Request):
        headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
        def error(name, status=400):
            return JSONResponse({"error": name}, status_code=status,
                headers={**headers, **({"WWW-Authenticate": 'Basic realm="local-mcp"'} if status == 401 else {})})
        try:
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Basic "):
                return error("invalid_client", 401)
            decoded = base64.b64decode(auth[6:], validate=True).decode("utf-8")
            identifier, secret = [unquote(s) for s in decoded.split(":", 1)]
        except (ValueError, UnicodeError, binascii.Error):
            return error("invalid_client", 401)
        if not hmac.compare_digest(identifier.encode(), c.client_id.encode()) or not hmac.compare_digest(secret.encode(), c.client_secret.encode()):
            return error("invalid_client", 401)
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
            return error("invalid_request")
        try:
            fields = parse_qs((await request.body()).decode("utf-8"), max_num_fields=10, keep_blank_values=True)
            if any(len(v) != 1 for v in fields.values()):
                return error("invalid_request")
            body = {k: v[0] for k, v in fields.items()}
        except (ValueError, UnicodeError):
            return error("invalid_request")
        if body.get("grant_type") != "client_credentials":
            return error("unsupported_grant_type")
        if body.get("resource") != c.resource:
            return error("invalid_target")
        if body.get("scope") != c.scope:
            return error("invalid_scope")
        now = int(time.time())
        access = jwt.encode({"iss": c.issuer, "sub": c.client_id, "aud": c.resource,
            "iat": now, "exp": now + config.ttl, "jti": str(uuid4()), "scope": c.scope},
            config.signing_secret, algorithm="HS256", headers={"typ": "at+jwt"})
        return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": config.ttl, "scope": c.scope}, headers=headers)

    return resource_metadata, server_metadata, token


class ServerAuthMiddleware:
    """Pure ASGI middleware preserves request cancellation and streaming semantics."""
    def __init__(self, app, config):
        self.app, self.config = app, config

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/health":
            return await self._handle(scope, receive, send)
        path = scope.get("path", "")
        stage = "mcp" if path == "/mcp" else "oauth.token" if path == "/oauth/token" else "discovery" if path.startswith("/.well-known/") else "other"
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
        c = self.config.bridge
        from urllib.parse import urlsplit
        allowed_hosts = set(self.config.allowed_hosts)
        response = None
        if request.headers.get("host") not in allowed_hosts:
            response = JSONResponse({"error": "invalid_host"}, status_code=403)
        elif request.headers.get("origin") and request.headers["origin"] not in self.config.allowed_origins:
            response = JSONResponse({"error": "invalid_origin"}, status_code=403)
        elif scope["path"] == "/mcp":
            challenge = f'Bearer resource_metadata="{c.issuer}/.well-known/oauth-protected-resource/mcp", scope="{c.scope}"'
            match = re.fullmatch(r"Bearer (\S+)", request.headers.get("authorization", ""))
            try:
                if not match or "access_token" in request.query_params:
                    raise jwt.InvalidTokenError()
                payload = jwt.decode(match[1], self.config.signing_secret, algorithms=["HS256"],
                    issuer=c.issuer, audience=c.resource, options={"require": ["exp", "iat", "sub"]})
                if payload["sub"] != c.client_id:
                    raise jwt.InvalidTokenError()
                if not set(c.scope.split()) <= set(str(payload.get("scope", "")).split()):
                    response = JSONResponse({"error": "insufficient_scope"}, status_code=403,
                        headers={"WWW-Authenticate": f'{challenge}, error="insufficient_scope"'})
            except jwt.InvalidTokenError:
                response = JSONResponse({"error": "invalid_token"}, status_code=401,
                    headers={"WWW-Authenticate": f'{challenge}, error="invalid_token"'})
        if response:
            return await response(scope, receive, send)
        # Bound bodies including chunked transfer without trusting Content-Length.
        if scope["method"] == "POST":
            limit = 8192 if scope["path"] == "/oauth/token" else 65536
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
