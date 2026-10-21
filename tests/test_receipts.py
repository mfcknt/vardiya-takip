"""Payment receipts: amount in Turkish words, voided payments refused."""
import uuid

import pytest

from conftest import ts
from vardiya.receipts import amount_words, number_words, receipt_html
from vardiya.security import AppError


@pytest.mark.parametrize("n, words", [
    (0, "sıfır"), (1, "bir"), (10, "on"), (19, "on dokuz"), (100, "yüz"), (101, "yüz bir"),
    (250, "iki yüz elli"), (1000, "bin"), (1250, "bin iki yüz elli"), (2000, "iki bin"),
    (11000, "on bir bin"), (100000, "yüz bin"), (101001, "yüz bir bin bir"), (1000000, "bir milyon"),
    (2345678, "iki milyon üç yüz kırk beş bin altı yüz yetmiş sekiz"),
])
def test_number_words(n, words):
    assert number_words(n) == words


def test_amount_words():
    assert amount_words(125030) == "bin iki yüz elli Türk lirası otuz kuruş"
    assert amount_words(50000) == "beş yüz Türk lirası"
    assert amount_words(5) == "sıfır Türk lirası beş kuruş"


def test_receipt_contains_payment_and_escapes_text(system):
    s, c, token, eid = system
    pid = s.add_payment(token, eid, ts("2026-10-15T18:30"), 125030, "Avans", "Ekim <avans>", str(uuid.uuid4()))
    payment = next(p for p in s.payments(token) if p["id"] == pid)
    html = receipt_html(s, payment)
    for part in (f"Ö-{pid:05d}", "15.10.2026 18:30", "Ayşe Yılmaz", "1.250,30 TL",
                 "bin iki yüz elli Türk lirası otuz kuruş", "Ekim &lt;avans&gt;", "avans olarak teslim aldım"):
        assert part in html
    s.void_payment(token, pid, "Yanlış")
    with pytest.raises(AppError, match="İptal edilmiş"):
        receipt_html(s, next(p for p in s.payments(token) if p["id"] == pid))
