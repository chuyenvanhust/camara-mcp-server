from dataclasses import dataclass
from uuid import uuid4
from typing import Any
from copy import deepcopy
import httpx2 as httpx
from camara_server.config import secure_url
from .contracts import TokenProvider
from .errors import ServiceError
from camara_server.diagnostics import operation, event


@dataclass(frozen=True)
class ApiResponse:
    data: Any
    correlator: str


class GatewayApiClient:
    """One configured API operation bound to one independent OAuth profile."""
    def __init__(self, http: httpx.AsyncClient, authentication: TokenProvider, endpoint: str, timeout: float):
        self.http, self.authentication = http, authentication
        self.endpoint = secure_url(endpoint, "API endpoint", False)
        self.timeout = timeout

    async def post_json(self, body: dict) -> ApiResponse:
        correlator = str(uuid4())
        body = deepcopy(body)
        for attempt in range(2):
            token = await self.authentication.get()
            try:
                async with operation("upstream.api", attempt=attempt + 1, correlator=correlator) as log:
                    response = await self.http.post(self.endpoint, json=body,
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "x-correlator": correlator},
                        timeout=self.timeout, follow_redirects=False)
                    log.update(status=response.status_code, outcome="ok" if response.status_code == 200 else "error")
            except httpx.HTTPError:
                raise ServiceError("UPSTREAM_UNAVAILABLE", correlator=correlator, request=body) from None
            if response.status_code == 401 and attempt == 0:
                event("upstream.api.retry_auth", correlator=correlator, attempt=attempt + 1)
                self.authentication.invalidate(token)
                continue
            if response.status_code != 200:
                raise ServiceError.from_http(response, correlator=correlator, request=body)
            try:
                return ApiResponse(response.json(), correlator)
            except ValueError:
                raise ServiceError("UPSTREAM_INVALID_RESPONSE") from None
