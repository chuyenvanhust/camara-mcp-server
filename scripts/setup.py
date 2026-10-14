import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
text = (root / ".env.example").read_text(encoding="utf-8")
while "GENERATE_WITH_SETUP" in text:
    text = text.replace("GENERATE_WITH_SETUP", secrets.token_urlsafe(32), 1)
try:
    with (root / ".env").open("x", encoding="utf-8") as output:
        output.write(text)
    print("Created .env with independent random local secrets")
except FileExistsError:
    print(".env already exists; kept unchanged")
