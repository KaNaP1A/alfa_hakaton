import hashlib
import hmac
import secrets
import time

from .database import SessionToken


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def password_matches(password, encoded):
    try:
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db, user_id, ttl):
    token = secrets.token_urlsafe(32)
    db.add(SessionToken(digest=token_digest(token), user_id=user_id, expires_at=time.time() + ttl))
    db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_in": ttl}
