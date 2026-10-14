from pathlib import Path

root = Path(__file__).resolve().parent.parent
text = (root / ".env.example").read_text(encoding="utf-8")
try:
    with (root / ".env").open("x", encoding="utf-8") as output:
        output.write(text)
    print("Created server .env; configure upstream credentials")
except FileExistsError:
    print(".env already exists; kept unchanged")
