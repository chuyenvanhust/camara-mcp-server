import asyncio
import time
from abc import ABC, abstractmethod
from camara_server.diagnostics import operation
import httpx2 as httpx
from camara_server.auth.token_response import validate_token
from camara_server.core.errors import ServiceError


class CachedTokenProvider(ABC):
    """Each profile owns its cache and lock; profiles never share access tokens."""
    def __init__(self, scope: str, clock=time.monotonic):
        self.scope, self.clock = scope, clock
        self.cached = None
        self.lock = asyncio.Lock()

    @abstractmethod
    async def acquire(self) -> httpx.Response: ...

    async def get(self) -> str:
        async with operation("upstream.token") as log:
            started = time.perf_counter()
            async with self.lock:
                log["lock_wait_ms"] = round((time.perf_counter()-started)*1000, 2)
                if self.cached and self.clock() < self.cached[1]:
                    log["cache_hit"] = True
                    return self.cached[0]
                log["cache_hit"] = False
                try:
                    async with operation("upstream.oauth") as oauth_log:
                        response = await self.acquire()
                        oauth_log.update(status=response.status_code, outcome="ok" if response.status_code == 200 else "error")
                except httpx.HTTPError:
                    raise ServiceError("UPSTREAM_TOKEN_UNAVAILABLE") from None
                if response.status_code != 200:
                    raise ServiceError.from_http(response, source="oauth")
                try:
                    token, expiry = validate_token(response.json(), self.scope)
                except (ValueError, TypeError, KeyError, AttributeError):
                    raise ServiceError("UPSTREAM_TOKEN_INVALID") from None
                self.cached = (token, self.clock() + expiry - min(300, expiry * .1))
                return token


    def invalidate(self, token: str) -> None:
        if self.cached and self.cached[0] == token:
            self.cached = None
