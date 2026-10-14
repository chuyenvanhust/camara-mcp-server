from dataclasses import dataclass
from urllib.parse import quote
import httpx2 as httpx
import jwt
from camara_server.config import integer, required, secure_url
from camara_server.core.contracts import ProviderContext
from camara_server.core.errors import ServiceError
from .signing import ClientAssertionSigner
from .base import CachedTokenProvider


@dataclass(frozen=True)
class ClientCredentialsSettings:
    token_url: str
    client_id: str
    scope: str
    prefix: str
    timeout: float

    @classmethod
    def from_context(cls, context: ProviderContext, options):
        prefix = options["env_prefix"]
        env = context.environment
        return cls(secure_url(required(env, f"{prefix}_TOKEN_URL"), f"{prefix}_TOKEN_URL", False),
                   required(env, f"{prefix}_CLIENT_ID"), required(env, f"{prefix}_SCOPE"), prefix,
                   integer(env, f"{prefix}_TIMEOUT_MS", int(context.timeout * 1000), 100, 120000) / 1000)


class PrivateKeyJwtCredentials(CachedTokenProvider):
    def __init__(self, context: ProviderContext, options):
        self.context = context
        self.settings = ClientCredentialsSettings.from_context(context, options)
        super().__init__(self.settings.scope)
        self.include_client_id = options.get("include_client_id", False)
        env, prefix = context.environment, self.settings.prefix
        self.assertion_path = env.get(f"{prefix}_CLIENT_ASSERTION_PATH")
        self.algorithm = env.get(f"{prefix}_SIGNING_ALGORITHM", "RS256")
        if self.assertion_path:
            self.supplied_assertion()
            self.signer = None
        else:
            self.signer = ClientAssertionSigner(context.root / required(env, f"{prefix}_PRIVATE_KEY_PATH"),
                self.settings.client_id, self.settings.token_url, required(env, f"{prefix}_KEY_ID"), self.algorithm)

    def supplied_assertion(self):
        try:
            assertion = (self.context.root / self.assertion_path).read_text(encoding="utf-8-sig").strip()
            header = jwt.get_unverified_header(assertion)
            claims = jwt.decode(assertion, options={"verify_signature": False})
            if (header.get("alg") != self.algorithm
                or claims.get("iss") != self.settings.client_id or claims.get("sub") != self.settings.client_id
                or claims.get("aud") != self.settings.token_url
                or type(claims.get("exp")) is not int or not claims.get("jti")):
                raise ValueError()
        except (OSError, ValueError, jwt.InvalidTokenError):
            raise ServiceError("UPSTREAM_ASSERTION_INVALID") from None
        # The authorization server verifies the signature and lifetime.
        return assertion

    async def acquire(self):
        assertion = self.supplied_assertion() if self.assertion_path else self.signer.sign()
        data = {"grant_type": "client_credentials", "scope": self.settings.scope,
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": assertion}
        if self.include_client_id:
            data["client_id"] = self.settings.client_id
        return await self.context.http.post(self.settings.token_url, data=data,
            timeout=self.settings.timeout, follow_redirects=False)


class BasicClientCredentials(CachedTokenProvider):
    def __init__(self, context: ProviderContext, options):
        self.context = context
        self.settings = ClientCredentialsSettings.from_context(context, options)
        super().__init__(self.settings.scope)
        self.secret = required(context.environment, f"{self.settings.prefix}_CLIENT_SECRET")

    async def acquire(self):
        return await self.context.http.post(self.settings.token_url,
            auth=httpx.BasicAuth(quote(self.settings.client_id, safe=""), quote(self.secret, safe="")),
            data={"grant_type": "client_credentials", "scope": self.settings.scope},
            timeout=self.settings.timeout, follow_redirects=False)


def build_private_key_jwt(context: ProviderContext, options):
    return PrivateKeyJwtCredentials(context, options)


def build_basic(context: ProviderContext, options):
    return BasicClientCredentials(context, options)
