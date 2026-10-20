"""No plaintext credentials or reversible password storage."""
import hashlib
import hmac
import re
import secrets

ITERATIONS = 600_000


class AppError(Exception):
    """A safe, user-facing validation or authorization error."""


def validate_pin(pin: str) -> None:
    if not re.fullmatch(r"[0-9]{6}", pin):
        raise AppError("PIN tam olarak 6 rakam olmalı.")
    if len(set(pin)) == 1 or pin in ("123456", "654321", "012345", "543210"):
        raise AppError("Tekrarlanan veya kolay tahmin edilen PIN kullanmayın.")


def validate_password(password: str) -> None:
    if len(password) < 12 or len(password) > 128:
        raise AppError("Yönetici şifresi 12–128 karakter olmalı.")


def hash_secret(secret: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_secret(secret: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, digest = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(rounds) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", secret.encode(), bytes.fromhex(salt), int(rounds)
        ).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False
