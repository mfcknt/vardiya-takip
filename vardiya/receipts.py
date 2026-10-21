"""Qt-free payment receipt: one A4 page with the amount in figures and in Turkish words."""
from datetime import datetime
from html import escape

from .formatting import tl
from .security import AppError

ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
GROUPS = ["", "bin", "milyon", "milyar"]
BUSINESS = "Ó'is coffee & eatery"


def _hundreds(n):
    hundreds, rest = divmod(n, 100)
    words = []
    if hundreds:
        words += ([ONES[hundreds]] if hundreds > 1 else []) + ["yüz"]
    words += [w for w in (TENS[rest // 10], ONES[rest % 10]) if w]
    return words


def number_words(n):
    """1250 → "bin iki yüz elli" ("bir bin"/"bir yüz" are not used in Turkish)."""
    if n == 0:
        return "sıfır"
    words, group = [], 0
    while n:
        n, chunk = divmod(n, 1000)
        if chunk:
            part = ["bin"] if group == 1 and chunk == 1 else _hundreds(chunk) + ([GROUPS[group]] if group else [])
            words = part + words
        group += 1
    return " ".join(words)


def amount_words(cents):
    lira, kurus = divmod(cents, 100)
    text = f"{number_words(lira)} Türk lirası"
    return text + (f" {number_words(kurus)} kuruş" if kurus else "")


def receipt_html(service, payment):
    """`payment` is a row from Service.payments (with the person's name)."""
    if payment["voided"]:
        raise AppError("İptal edilmiş ödeme için makbuz verilemez.")
    paid = datetime.fromtimestamp(payment["paid_at"], service.zone)
    printed = datetime.fromtimestamp(service.clock.wall(), service.zone)
    kind = "Avans" if payment["kind"] == "Avans" else "Ücret ödemesi"
    row = "<tr><td style='padding:6px 18px 6px 0; color:#555'>{}</td><td style='padding:6px 0'>{}</td></tr>"
    rows = "".join(row.format(k, v) for k, v in [
        ("Makbuz no", f"Ö-{payment['id']:05d}"),
        ("Tarih", paid.strftime("%d.%m.%Y %H:%M")),
        ("Personel", escape(payment["name"])),
        ("Tür", kind),
        ("Tutar", f"<b style='font-size:16pt'>{tl(payment['amount_cents'])} TL</b>"),
        ("Yazıyla", amount_words(payment["amount_cents"])),
        ("Açıklama", escape(payment["note"])),
    ])
    sign = ("<td width='50%' style='padding-top:60px; padding-right:30px'>"
            "______________________________<br>{}<br><span style='color:#555'>ad soyad · imza</span></td>")
    return (f"<h2 style='margin-bottom:0'>{escape(BUSINESS)}</h2>"
            f"<p style='margin-top:4px; color:#555'>Personel ödeme makbuzu</p>"
            f"<table style='margin-top:18px'>{rows}</table>"
            f"<p style='margin-top:18px'>Yukarıdaki tutarı {kind.lower()} olarak teslim aldım.</p>"
            f"<table width='100%' style='margin-top:30px'><tr>{sign.format('Ödeyen')}"
            f"{sign.format('Teslim alan · ' + escape(payment['name']))}</tr></table>"
            f"<p style='margin-top:40px; color:#888; font-size:8pt'>Vardiya Takip · yazdırma "
            f"{printed:%d.%m.%Y %H:%M} · ön hak ediş kaydıdır, resmî bordro değildir.</p>")
