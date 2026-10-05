import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from fastapi import Header, Depends
from app.db import get_connection
from app.errors import APIError

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 16384, 8, 1
    pw_bytes = password.encode("utf-8")
    derived = hashlib.scrypt(pw_bytes, salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${derived.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        parts = stored_hash.split("$")
        if len(parts) != 6 or parts[0] != "scrypt":
            return False
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = bytes.fromhex(parts[4])
        expected_hex = parts[5]
        pw_bytes = password.encode("utf-8")
        derived = hashlib.scrypt(pw_bytes, salt=salt, n=n, r=r, p=p, dklen=32)
        return hmac.compare_digest(derived.hex(), expected_hex)
    except Exception:
        return False

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def generate_token_for_user(conn, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    t_hash = hash_token(token)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO auth_tokens (token_hash, user_id, created_at) VALUES (?, ?, ?)",
        (t_hash, user_id, now)
    )
    conn.commit()
    return token

def get_current_user_id(authorization: str = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise APIError(401, "unauthenticated", "Missing or invalid authorization header")
    
    token = authorization[7:].strip()
    if not token:
        raise APIError(401, "unauthenticated", "Missing bearer token")
    
    t_hash = hash_token(token)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT user_id FROM auth_tokens WHERE token_hash = ?",
            (t_hash,)
        ).fetchone()
        
        if not row:
            raise APIError(401, "unauthenticated", "Invalid or expired token")
        return row["user_id"]
