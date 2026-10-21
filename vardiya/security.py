"""No plaintext credentials or reversible password storage."""
import hashlib
import hmac
import re
import secrets

ITERATIONS = 600_000


class AppError(Exception):
    """A safe, user-facing validation or authorization error."""


PIN_LENGTH = 4


def weak_pin(pin: str) -> bool:
    """1111, 1234 / 4321 style runs, 1212 (abab) and 1122 (aabb)."""
    digits = [int(c) for c in pin]
    steps = {b - a for a, b in zip(digits, digits[1:])}
    return (len(set(pin)) == 1 or steps in ({1}, {-1})
            or (pin[0] == pin[2] and pin[1] == pin[3])
            or (pin[0] == pin[1] and pin[2] == pin[3]))


def validate_pin(pin: str, who="PIN") -> None:
    if not re.fullmatch(r"[0-9]{%d}" % PIN_LENGTH, pin or ""):
        raise AppError(f"{who} tam olarak {PIN_LENGTH} rakam olmalı.")
    if weak_pin(pin):
        raise AppError("1111, 1234, 1212 gibi tekrarlanan veya sıralı şifre kullanmayın.")


def validate_password(password: str) -> None:
    """The admin password is a 4-digit code too (escalating lock compensates)."""
    validate_pin(password, "Yönetici şifresi")


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
