"""Export only Kubernetes credential fields; never print credential values."""
from pathlib import Path
from dotenv import dotenv_values

root = Path(__file__).resolve().parent.parent
values = dotenv_values(root / ".env")
names = ("MCP_CLIENT_SECRET", "MCP_SIGNING_SECRET", "UPSTREAM_CLIENT_ID", "UPSTREAM_KEY_ID")
for name in names:
    value = values.get(name)
    if not value or value == "GENERATE_WITH_SETUP" or "\n" in value or "\r" in value:
        raise SystemExit(f"Set a valid {name} in server .env first")
    if name in {"MCP_CLIENT_SECRET", "MCP_SIGNING_SECRET"} and len(value) < 32:
        raise SystemExit(f"{name} must contain at least 32 characters")
output = root / "k8s" / "credentials.env"
try:
    with output.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(f"{name}={values[name]}" for name in names) + "\n")
except FileExistsError:
    raise SystemExit("k8s/credentials.env already exists; kept unchanged")
print("Created k8s/credentials.env. Restrict file permissions and keep it out of Git.")
