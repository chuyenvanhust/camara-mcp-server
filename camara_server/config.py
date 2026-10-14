from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_VERSION = "2026-07-28"
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
        raise ValueError(f"Set {name} in server configuration")
    return value


@dataclass(frozen=True)
class ServerConfig:
    resource: str
    timeout: float
    port: int
    mode: str
    modules_file: Path
    environment: dict[str, str] = field(repr=False)
    host: str = "127.0.0.1"
    allowed_hosts: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        resource = secure_url(env.get("MCP_SERVER_URL", "http://localhost:3000/mcp"), "MCP_SERVER_URL")
        parsed = urlsplit(resource)
        if parsed.path != "/mcp" or parsed.query:
            raise ValueError("MCP_SERVER_URL requires path /mcp without query")
        port = integer(env, "PORT", 3000, 1, 65535)
        hosts = tuple(dict.fromkeys([parsed.netloc, f"localhost:{port}", f"127.0.0.1:{port}", f"[::1]:{port}"] +
            [value.strip() for value in env.get("MCP_ALLOWED_HOSTS", "").split(",") if value.strip()]))
        origins = tuple(value.strip() for value in env.get("MCP_ALLOWED_ORIGINS", f"{parsed.scheme}://{parsed.netloc}").split(",") if value.strip())
        for origin in origins:
            secure_url(origin, "MCP_ALLOWED_ORIGINS")
        return cls(resource, integer(env, "REQUEST_TIMEOUT_MS", 10000, 100, 120000)/1000, port, "live",
            ROOT / env.get("GATEWAY_MODULES_FILE", "gateway.toml"), dict(env),
            env.get("BIND_HOST", "127.0.0.1"), hosts, origins)
