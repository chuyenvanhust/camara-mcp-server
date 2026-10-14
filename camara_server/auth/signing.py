"""Python equivalent of authUtils.setClientAssertionForTokenEndpoint."""
import time
from pathlib import Path
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class ClientAssertionSigner:
    def __init__(self, key_path: Path, client_id: str, audience: str, key_id: str,
                 algorithm: str = "RS256", clock=time.time):
        if algorithm not in {"RS256", "PS256"}:
            raise ValueError("UPSTREAM_SIGNING_ALGORITHM must be RS256 or PS256")
        if not client_id or not audience or not key_id:
            raise ValueError("JWT signing requires client ID, token endpoint and registered key ID")
        self.key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(self.key, rsa.RSAPrivateKey) or self.key.key_size < 2048:
            raise ValueError("Signing requires an RSA private key of at least 2048 bits")
        self.client_id, self.audience, self.key_id = client_id, audience, key_id
        self.algorithm, self.clock = algorithm, clock

    def sign(self) -> str:
        now = int(self.clock())
        claims = {"iss": self.client_id, "sub": self.client_id, "aud": self.audience,
                  "exp": now + 120, "nbf": now - 120, "iat": now, "jti": str(uuid4())}
        return jwt.encode(claims, self.key, algorithm=self.algorithm,
                          headers={"alg": self.algorithm, "typ": "JWT", "kid": self.key_id})
