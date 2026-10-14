import math

def validate_token(data: dict, requested_scope: str) -> tuple[str, float]:
    expiry = data.get("expires_in")
    if (not isinstance(data.get("access_token"), str) or not data["access_token"]
        or str(data.get("token_type", "")).lower() != "bearer"
        or type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= 0
        or data.get("scope") and not set(requested_scope.split()) <= set(data["scope"].split())):
        raise ValueError("Invalid OAuth token response")
    return data["access_token"], expiry


