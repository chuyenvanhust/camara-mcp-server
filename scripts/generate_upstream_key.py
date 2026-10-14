from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

root = Path(__file__).resolve().parent.parent / "keys"
root.mkdir(exist_ok=True)
private_path, public_path = root / "upstream-private.pem", root / "upstream-public.pem"
if private_path.exists() or public_path.exists():
    raise SystemExit("Existing key found; refusing to replace it")
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
with private_path.open("xb") as output:
    output.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
with public_path.open("xb") as output:
    output.write(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
print("Generated RSA keys; register the public key only and restrict private key ACL")
