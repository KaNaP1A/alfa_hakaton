import hashlib


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
