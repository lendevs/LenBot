import hashlib
import hmac
import json
import os
import secrets
import re
import time
from pathlib import Path
from typing import Optional
from fastapi import HTTPException, status

# Active sessions by token digest: digest -> {"username": str, "expires_at": float}
_ACTIVE_SESSIONS: dict[str, dict] = {}
SESSION_TTL = 7 * 86400.0  # 7 days
# When set, sessions are kept in this file so a restart or an update keeps the panel signed in.
_SESSION_FILE: Path | None = None


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def keep_sessions(path: Path) -> None:
    """Load the sessions saved at ``path`` and save later changes there."""
    global _SESSION_FILE
    _SESSION_FILE = path
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        # No file yet, or one that a power cut left empty or half written: everyone signs in again.
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    now = time.time()
    _ACTIVE_SESSIONS.clear()
    for key, value in saved.items():
        expires_at = value.get("expires_at") if isinstance(value, dict) else None
        if isinstance(value, dict) and isinstance(value.get("username"), str) \
                and isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool) and expires_at > now:
            _ACTIVE_SESSIONS[key] = value


def _save_sessions() -> None:
    if _SESSION_FILE is None:
        return
    _SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = _SESSION_FILE.with_name(_SESSION_FILE.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(_ACTIVE_SESSIONS, output)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(_SESSION_FILE)
    if os.name != "nt":
        try:
            directory = os.open(_SESSION_FILE.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass  # the rename is already done; some file systems cannot sync a directory


def revoke_all_sessions() -> None:
    _ACTIVE_SESSIONS.clear()
    _save_sessions()

# Failed-login throttle: client identity -> recent failure timestamps.  The
# dashboard port may be reachable beyond localhost, and PBKDF2 alone does not
# stop an online guessing loop.
_FAILED_LOGINS: dict[str, list[float]] = {}
LOGIN_ATTEMPT_WINDOW = 900.0
LOGIN_ATTEMPT_LIMIT = 5


def login_blocked(key: str) -> bool:
    now = time.time()
    attempts = [moment for moment in _FAILED_LOGINS.get(key, []) if now - moment < LOGIN_ATTEMPT_WINDOW]
    if attempts:
        _FAILED_LOGINS[key] = attempts
    else:
        _FAILED_LOGINS.pop(key, None)
    return len(attempts) >= LOGIN_ATTEMPT_LIMIT


def record_login_failure(key: str) -> None:
    now = time.time()
    if len(_FAILED_LOGINS) > 10000:
        for stale in [name for name, moments in _FAILED_LOGINS.items()
                      if not moments or now - moments[-1] >= LOGIN_ATTEMPT_WINDOW]:
            _FAILED_LOGINS.pop(stale, None)
    attempts = [moment for moment in _FAILED_LOGINS.get(key, []) if now - moment < LOGIN_ATTEMPT_WINDOW]
    attempts.append(now)
    _FAILED_LOGINS[key] = attempts


def clear_login_failures(key: str) -> None:
    _FAILED_LOGINS.pop(key, None)


MAX_PASSWORD_ITERATIONS = 10_000_000
# The digit count is bounded first; the value is converted and range-checked afterwards.
PASSWORD_HASH_PATTERN = r"pbkdf2_sha256\$[1-9][0-9]{0,7}\$[^$]+\$[0-9a-f]{64}"


def password_hash_valid(stored_hash: str) -> bool:
    """A pbkdf2_sha256$iterations$salt$hash record with 1 to 10,000,000 iterations."""
    if re.fullmatch(PASSWORD_HASH_PATTERN, stored_hash) is None:
        return False
    return int(stored_hash.split("$")[1]) <= MAX_PASSWORD_ITERATIONS


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """PBKDF2-HMAC-SHA256 password hasher with random salt."""
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 600_000)
    return f"pbkdf2_sha256$600000${salt}${dk.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a pbkdf2_sha256$iterations$salt$hash record."""
    if not password_hash_valid(stored_hash):
        return False
    _, iterations, salt, expected_hex = stored_hash.split("$")
    try:
        secret, salt_bytes = password.encode("utf-8"), salt.encode("utf-8")
    except UnicodeEncodeError:
        # A lone surrogate (JSON "\ud800") cannot be UTF-8; no stored password contains one.
        return False
    dk = hashlib.pbkdf2_hmac("sha256", secret, salt_bytes, int(iterations))
    return hmac.compare_digest(dk.hex(), expected_hex)

def create_session(username: str) -> str:
    """Creates a new session token for the user."""
    now = time.time()
    for expired in [key for key, session in _ACTIVE_SESSIONS.items() if session['expires_at'] <= now]:
        del _ACTIVE_SESSIONS[expired]
    token = secrets.token_urlsafe(32)
    _ACTIVE_SESSIONS[_digest(token)] = {
        "username": username,
        "expires_at": time.time() + SESSION_TTL
    }
    _save_sessions()
    return token

def revoke_session(token: str) -> None:
    """Revokes a session token on logout."""
    if _ACTIVE_SESSIONS.pop(_digest(token), None) is not None:
        _save_sessions()

def session_user(token: str | None) -> str:
    """Validate an existing cookie session without depending on a runtime store."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    session = _ACTIVE_SESSIONS.get(_digest(token))
    if not session or session["expires_at"] < time.time():
        _ACTIVE_SESSIONS.pop(_digest(token), None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid"
        )

    return session["username"]
