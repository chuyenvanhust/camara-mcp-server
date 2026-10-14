from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_VERSION = "2026-07-28"
SCOPE = "gateway:invoke"
load_dotenv(ROOT / ".env", override=False)


def secure_url(value: str, name: str, allow_local: bool = True) -> str:
    parsed = urlsplit(value)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment or not (
        parsed.scheme == "https" or allow_local and local and parsed.scheme == "http"
    ):
        raise ValueError(f"{name} requires HTTPS or HTTP on loopback without credentials or fragment")
    return value


def integer(env, name, default, minimum, maximum):
    value = int(env.get(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"Invalid {name}")
    return value


def required(env, name):
    value = env.get(name)
    if not value or value == "GENERATE_WITH_SETUP":
        raise ValueError(f"Set {name}; run python scripts/setup.py for local secrets")
    return value


@dataclass(frozen=True)
class ServerConnection:
    resource: str
    issuer: str
    token_url: str
    client_id: str
    client_secret: str
    scope: str
    timeout: float

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        resource = secure_url(env.get("MCP_SERVER_URL", "http://localhost:3000/mcp"), "MCP_SERVER_URL")
        parsed = urlsplit(resource)
        issuer = secure_url(env.get("MCP_ISSUER", f"{parsed.scheme}://{parsed.netloc}"), "MCP_ISSUER")
        return cls(resource, issuer,
                   secure_url(env.get("MCP_TOKEN_URL", f"{issuer}/oauth/token"), "MCP_TOKEN_URL"),
                   env.get("MCP_CLIENT_ID", "local-bridge"), required(env, "MCP_CLIENT_SECRET"),
                   env.get("MCP_SCOPE", SCOPE), integer(env, "REQUEST_TIMEOUT_MS", 10000, 100, 120000) / 1000)


@dataclass(frozen=True)
class ServerConfig:
    bridge: ServerConnection
    port: int
    signing_secret: str
    ttl: int
    mode: str
    modules_file: Path
    environment: dict[str, str] = field(repr=False)
    host: str = "127.0.0.1"
    allowed_hosts: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        bridge = ServerConnection.from_env(env)
        parsed = urlsplit(bridge.resource)
        port = integer(env, "PORT", 3000, 1, 65535)
        if parsed.path != "/mcp" or parsed.query:
            raise ValueError("MCP_SERVER_URL requires path /mcp without query")
        issuer_url = urlsplit(bridge.issuer)
        if issuer_url.path not in {"", "/"} or issuer_url.query:
            raise ValueError("Built-in OAuth issuer must be an origin without a path")
        if bridge.token_url != f"{bridge.issuer}/oauth/token":
            raise ValueError("Built-in OAuth token URL must be MCP_ISSUER/oauth/token")
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} and parsed.scheme != "https":
            raise ValueError("Public MCP URL requires HTTPS")
        hosts = tuple(dict.fromkeys([parsed.netloc, f"localhost:{port}", f"127.0.0.1:{port}", f"[::1]:{port}"]))
        origins = tuple(value.strip() for value in env.get("MCP_ALLOWED_ORIGINS", f"{parsed.scheme}://{parsed.netloc}").split(",") if value.strip())
        for origin in origins:
            secure_url(origin, "MCP_ALLOWED_ORIGINS")
        signing_secret = required(env, "MCP_SIGNING_SECRET")
        if min(len(signing_secret), len(bridge.client_secret)) < 32:
            raise ValueError("Local secrets must contain at least 32 characters")
        return cls(bridge, port, signing_secret, integer(env, "TOKEN_TTL_SECONDS", 600, 30, 7200), "live",
                   ROOT / env.get("GATEWAY_MODULES_FILE", "gateway.toml"), dict(env), env.get("BIND_HOST", "127.0.0.1"), hosts, origins)
