"""Qt-free display helpers: Turkish money format and amount parsing."""
import re
from decimal import Decimal, InvalidOperation

from .security import AppError


def tl(cents_value):
    """Turkish display format: 1.440,50"""
    sign = "-" if cents_value < 0 else ""
    whole, rest = divmod(abs(int(cents_value)), 100)
    return f"{sign}{whole:,}".replace(",", ".") + f",{rest:02d}"


def normalize_amount(text):
    """Accept 1.500,50 / 1500,50 / 1500.50 / 1.500 (thousands) / 150."""
    text = text.strip().replace(" ", "").replace("₺", "").replace("TL", "").replace("tl", "")
    if "," in text:
        return text.replace(".", "").replace(",", ".")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        return text.replace(".", "")
    return text


def cents(text):
    try:
        value = Decimal(normalize_amount(text))
        if not value.is_finite() or value < 0 or value.as_tuple().exponent < -2:
            raise InvalidOperation
        return int(value * 100)
    except (InvalidOperation, ValueError):
        raise AppError("Tutarı en çok iki ondalıkla yazın. Örnek: 150,50 veya 1.500,00") from None
