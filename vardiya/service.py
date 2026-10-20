import secrets
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from .security import AppError, hash_secret, validate_password, validate_pin, verify_secret
from .storage import Database, canonical


class SystemClock:
    def wall(self):
        return int(time.time())

    def monotonic(self):
        return time.monotonic()


def valid_cents(value, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= 100_000_000:
        raise AppError("Tutar 0–1.000.000 TL aralığında olmalı.")
    return value


LOCK_AFTER = 5            # failed attempts before a lock
ADMIN_LOCK_SECONDS = 300
STAFF_LOCK_STEPS = (30, 60, 120, 240, 300)   # escalating staff PIN locks
LONG_GAP_SECONDS = 36 * 3600


def staff_lock_seconds(failures):
    """Lock length after `failures` consecutive wrong PINs (0 = no lock)."""
    if failures < LOCK_AFTER:
        return 0
    return STAFF_LOCK_STEPS[min(failures - LOCK_AFTER, len(STAFF_LOCK_STEPS) - 1)]


def reason_text(reason):
    reason = reason.strip()
    if not 5 <= len(reason) <= 500:
        raise AppError("İşlem gerekçesi 5–500 karakter olmalı.")
    return reason


def lock_message(seconds):
    minutes, rest = divmod(max(1, int(seconds)), 60)
    wait = f"{minutes} dk {rest} sn" if minutes else f"{rest} sn"
    return (f"Çok sayıda hatalı deneme. Yeniden denemek için {wait} bekleyin. "
            "Yönetici kilidi kaldırabilir.")


class Service:
    """All mutations are transactions. UI passes no SQL and cannot bypass admin checks."""
    def __init__(self, db: Database, clock=None):
        self.db = db
        self.clock = clock or SystemClock()
        self._tokens = {}
        self._sample = None

    @property
    def configured(self):
        return self.db.conn.execute(
            "SELECT 1 FROM credentials WHERE subject='admin'"
        ).fetchone() is not None

    @property
    def zone(self):
        return ZoneInfo(self.db.meta("timezone", "Europe/Istanbul"))

    def setup(self, password, timezone="Europe/Istanbul"):
        validate_password(password)
        ZoneInfo(timezone)
        encoded = hash_secret(password)
        with self.db.transaction():
            if self.configured:
                raise AppError("İlk kurulum zaten tamamlanmış.")
            self.db.conn.execute("INSERT INTO credentials(subject,secret) VALUES('admin',?)",
                                 (encoded,))
            self.db.set_meta("timezone", timezone)
            self.db.set_meta("last_wall", self.clock.wall())
            self.db.audit(self.clock.wall(), "admin", "SETUP", "system", after={"timezone": timezone})

    def tick(self):
        """Detect backward time and wall/monotonic drift; note long offline gaps.

        A clock alert never stops staff from recording work: while it is active,
        every start/finish is flagged for admin review instead. A long gap since
        the last use (holiday, closed day) is only an informational notice.
        Returns the active clock alert text ("" when none).
        """
        now, mono = self.clock.wall(), self.clock.monotonic()
        with self.db.transaction():
            last = int(self.db.meta("last_wall", now))
            cause = notice = ""
            if now < last - 5:
                cause = "Bilgisayar saati geriye alındı."
            elif self._sample and abs((now - self._sample[0]) - (mono - self._sample[1])) > 120:
                cause = "Bilgisayar saati ile geçen süre uyuşmuyor."
            elif not self._sample and now - last > LONG_GAP_SECONDS:
                notice = ("Uygulama uzun süre kapalı kaldı "
                          f"({(now - last) // 3600} saat). Bilgisayar saatini doğrulayın.")
            if cause and not self.db.meta("clock_alert", ""):
                self.db.set_meta("clock_alert", cause)
                self.db.audit(now, "system", "CLOCK_ALERT", "clock",
                              after={"last": last, "current": now}, reason=cause)
            if notice and not self.db.meta("clock_notice", ""):
                self.db.set_meta("clock_notice", notice)
                self.db.audit(now, "system", "CLOCK_NOTICE", "clock",
                              after={"last": last, "current": now}, reason=notice)
            self.db.set_meta("last_wall", max(now, last))
            alert = self.db.meta("clock_alert", "")
        self._sample = (now, mono)
        return alert

    def clock_status(self):
        """(blocking-free alert, informational notice) as stored."""
        return self.db.meta("clock_alert", ""), self.db.meta("clock_notice", "")

    def _authenticate(self, subject, secret):
        # Persist failed attempts even when the caller receives an exception.
        error = None
        now = max(self.clock.wall(), int(self.db.meta("last_wall", self.clock.wall())))
        with self.db.transaction():
            row = self.db.conn.execute("SELECT * FROM credentials WHERE subject=?", (subject,)).fetchone()
            if row is None or len(secret) > 128:
                error = "Kimlik bilgisi doğrulanamadı."
            elif row["locked_until"] > now:
                error = lock_message(row["locked_until"] - now)
            elif not verify_secret(secret, row["secret"]):
                failures = row["failures"] + 1
                if subject == "admin":
                    seconds = ADMIN_LOCK_SECONDS if failures >= LOCK_AFTER else 0
                    stored = 0 if seconds else failures
                else:
                    # Staff locks escalate and the counter only resets on a
                    # correct PIN, an admin unlock or a PIN change.
                    seconds, stored = staff_lock_seconds(failures), failures
                locked = now + seconds if seconds else 0
                self.db.conn.execute(
                    "UPDATE credentials SET failures=?,locked_until=? WHERE subject=?",
                    (stored, locked, subject),
                )
                if locked:
                    self.db.audit(now, "system", "AUTH_LOCK", subject,
                                  after={"failures": failures, "seconds": seconds},
                                  reason=f"{failures} hatalı deneme")
                    error = lock_message(seconds)
                else:
                    error = "Kimlik bilgisi doğrulanamadı."
            else:
                self.db.conn.execute(
                    "UPDATE credentials SET failures=0,locked_until=0 WHERE subject=?", (subject,)
                )
        if error:
            raise AppError(error)

    def login_admin(self, password):
        self._authenticate("admin", password)
        token = secrets.token_urlsafe(32)
        self._tokens[token] = self.clock.monotonic()
        return token

    def require_admin(self, token):
        last = self._tokens.get(token)
        if last is None or self.clock.monotonic() - last > 300:
            self.logout(token)
            raise AppError("Yönetici oturumu kapandı. Yeniden giriş yapın.")
        self._tokens[token] = self.clock.monotonic()

    def logout(self, token):
        self._tokens.pop(token, None)

    def change_password(self, token, old, new):
        self.require_admin(token)
        self._authenticate("admin", old)
        validate_password(new)
        encoded = hash_secret(new)
        with self.db.transaction():
            self.db.conn.execute("UPDATE credentials SET secret=? WHERE subject='admin'", (encoded,))
            self.db.audit(self.clock.wall(), "admin", "PASSWORD_CHANGE", "admin")
        self._tokens.clear()

    def acknowledge_clock(self, token, reason):
        self.require_admin(token)
        reason = reason_text(reason)
        with self.db.transaction():
            self.db.audit(self.clock.wall(), "admin", "CLOCK_ACK", "clock",
                          before={"alert": self.db.meta("clock_alert", ""),
                                  "notice": self.db.meta("clock_notice", "")}, reason=reason)
            self.db.set_meta("clock_alert", "")
            self.db.set_meta("clock_notice", "")
            self.db.set_meta("last_wall", self.clock.wall())
        self._sample = (self.clock.wall(), self.clock.monotonic())

    def kiosk_employees(self):
        return [dict(r) for r in self.db.conn.execute("""SELECT e.id,e.name,
            s.id AS session_id,s.start_at,c.locked_until FROM employees e
            LEFT JOIN sessions s ON s.employee_id=e.id AND s.end_at IS NULL AND s.voided=0
            LEFT JOIN credentials c ON c.subject='staff:'||e.id
            WHERE e.active=1 ORDER BY e.name COLLATE NOCASE,e.id""")]

    def employees(self, token):
        self.require_admin(token)
        return [dict(r) for r in self.db.conn.execute("""SELECT e.*,c.failures,c.locked_until
            FROM employees e LEFT JOIN credentials c ON c.subject='staff:'||e.id
            ORDER BY e.name,e.id""")]

    def unlock_employee(self, token, eid, reason):
        self.require_admin(token)
        reason = reason_text(reason)
        with self.db.transaction():
            row = self.db.conn.execute("SELECT failures,locked_until FROM credentials WHERE subject=?",
                                       (f"staff:{eid}",)).fetchone()
            if not row:
                raise AppError("Personel bulunamadı.")
            self.db.conn.execute("UPDATE credentials SET failures=0,locked_until=0 WHERE subject=?",
                                 (f"staff:{eid}",))
            self.db.audit(self.clock.wall(), "admin", "AUTH_UNLOCK", f"staff:{eid}",
                          before=dict(row), reason=reason)

    def add_employee(self, token, name, pin, rate_cents):
        self.require_admin(token)
        name = name.strip()
        if not 1 <= len(name) <= 80:
            raise AppError("Ad soyad 1–80 karakter olmalı.")
        validate_pin(pin)
        valid_cents(rate_cents)
        encoded, now = hash_secret(pin), self.clock.wall()
        with self.db.transaction():
            eid = self.db.conn.execute(
                "INSERT INTO employees(name,rate_cents,created_at) VALUES(?,?,?)",
                (name, rate_cents, now),
            ).lastrowid
            self.db.conn.execute("INSERT INTO credentials(subject,secret) VALUES(?,?)",
                                 (f"staff:{eid}", encoded))
            self.db.conn.execute(
                "INSERT INTO rate_history(employee_id,effective_at,rate_cents) VALUES(?,?,?)",
                (eid, now, rate_cents),
            )
            self.db.audit(now, "admin", "EMPLOYEE_ADD", f"employee:{eid}",
                          after={"name": name, "rate_cents": rate_cents})
        return eid

    def update_employee(self, token, eid, name, rate_cents, active, reason, pin=None):
        self.require_admin(token)
        reason = reason_text(reason)
        name = name.strip()
        if not 1 <= len(name) <= 80:
            raise AppError("Ad soyad 1–80 karakter olmalı.")
        valid_cents(rate_cents)
        encoded = None
        if pin:
            validate_pin(pin)
            encoded = hash_secret(pin)
        with self.db.transaction():
            before = self.db.conn.execute("SELECT * FROM employees WHERE id=?", (eid,)).fetchone()
            if not before:
                raise AppError("Personel bulunamadı.")
            if not active and self.db.conn.execute(
                "SELECT 1 FROM sessions WHERE employee_id=? AND end_at IS NULL AND voided=0", (eid,)
            ).fetchone():
                raise AppError("Önce açık çalışma kaydını kapatın.")
            self.db.conn.execute("UPDATE employees SET name=?,rate_cents=?,active=? WHERE id=?",
                                 (name, rate_cents, int(bool(active)), eid))
            if before["rate_cents"] != rate_cents:
                self.db.conn.execute(
                    "INSERT INTO rate_history(employee_id,effective_at,rate_cents) VALUES(?,?,?)",
                    (eid, self.clock.wall(), rate_cents),
                )
            if encoded:
                self.db.conn.execute(
                    "UPDATE credentials SET secret=?,failures=0,locked_until=0 WHERE subject=?",
                    (encoded, f"staff:{eid}"),
                )
            self.db.audit(self.clock.wall(), "admin", "EMPLOYEE_UPDATE", f"employee:{eid}",
                          before=dict(before), after={"name": name, "rate_cents": rate_cents,
                                                     "active": bool(active), "pin_reset": bool(encoded)},
                          reason=reason)

    def _no_overlap(self, eid, start, end, exclude=0):
        if self.db.conn.execute("""SELECT 1 FROM sessions WHERE employee_id=? AND voided=0
            AND id<>? AND start_at<COALESCE(?,9223372036854775807)
            AND COALESCE(end_at,9223372036854775807)>? LIMIT 1""",
                                (eid, exclude, end, start)).fetchone():
            raise AppError("Bu personelin çalışma saatleri başka bir kayıtla çakışıyor.")

    def attendance(self, eid, pin, action, expected_session, request_id):
        if action not in ("start", "end"):
            raise AppError("Geçersiz işlem.")
        try:
            uuid.UUID(request_id)
        except (ValueError, TypeError, AttributeError):
            raise AppError("Geçersiz işlem kimliği.")
        self._authenticate(f"staff:{eid}", pin)
        self.tick()
        fingerprint = canonical([eid, action, expected_session])
        now = self.clock.wall()
        with self.db.transaction():
            # Under a clock alert the work is still recorded, but flagged.
            review = self.db.meta("clock_alert", "")
            receipt = self.db.conn.execute("SELECT * FROM receipts WHERE request_id=?",
                                           (request_id,)).fetchone()
            if receipt:
                if receipt["fingerprint"] != fingerprint:
                    raise AppError("İşlem kimliği başka bir işlemde kullanılmış.")
                return receipt["result_id"]
            employee = self.db.conn.execute(
                "SELECT * FROM employees WHERE id=? AND active=1", (eid,)
            ).fetchone()
            if not employee:
                raise AppError("Personel aktif değil.")
            opened = self.db.conn.execute(
                "SELECT * FROM sessions WHERE employee_id=? AND end_at IS NULL AND voided=0", (eid,)
            ).fetchone()
            if action == "start":
                if opened or expected_session is not None:
                    raise AppError("Zaten açık bir çalışma kaydı var. Ekranı yenileyin.")
                self._no_overlap(eid, now, None)
                sid = self.db.conn.execute(
                    "INSERT INTO sessions(employee_id,start_at,rate_cents,review) VALUES(?,?,?,?)",
                    (eid, now, employee["rate_cents"], review),
                ).lastrowid
            else:
                if not opened or opened["id"] != expected_session:
                    raise AppError("Açık kayıt değişti veya kapandı. Ekranı yenileyin.")
                if now <= opened["start_at"]:
                    raise AppError("Bilgisayar saati giriş saatinden önce görünüyor. "
                                   "Çıkışı yönetici kaydetmeli.")
                if now - opened["start_at"] > 24 * 3600:
                    raise AppError("24 saati aşan açık kayıt yönetici tarafından düzeltilmeli.")
                sid = opened["id"]
                self.db.conn.execute(
                    """UPDATE sessions SET end_at=?,revision=revision+1,
                       review=CASE WHEN review='' THEN ? ELSE review END WHERE id=?""",
                    (now, review, sid))
            after = dict(self.db.conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
            self.db.audit(now, f"staff:{eid}", action.upper(), f"session:{sid}",
                          before=dict(opened) if opened else None, after=after)
            self.db.conn.execute("INSERT INTO receipts VALUES(?,?,?)", (request_id, fingerprint, sid))
        return sid

    def sessions(self, token, eid=None, since=None, until=None, review_only=False):
        """Records overlapping [since, until); open records always overlap `now`."""
        self.require_admin(token)
        return [dict(r) for r in self.db.conn.execute("""SELECT s.*,e.name FROM sessions s
            JOIN employees e ON e.id=s.employee_id WHERE (? IS NULL OR employee_id=?)
            AND s.start_at < COALESCE(?, 9223372036854775807)
            AND COALESCE(s.end_at, 9223372036854775807) > COALESCE(?, -1)
            AND (? = 0 OR (s.review <> '' AND s.voided = 0))
            ORDER BY start_at DESC,id DESC""", (eid, eid, until, since, int(bool(review_only))))]

    def pending_reviews(self, token):
        self.require_admin(token)
        return self.db.conn.execute(
            "SELECT count(*) FROM sessions WHERE review<>'' AND voided=0").fetchone()[0]

    def correct_session(self, token, sid, revision, start, end, reason, void=False):
        self.require_admin(token)
        reason = reason_text(reason)
        with self.db.transaction():
            row = self.db.conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
            if not row or row["revision"] != revision:
                raise AppError("Kayıt değişmiş. Ekranı yenileyip tekrar deneyin.")
            if row["voided"]:
                raise AppError("İptal edilmiş kayıt yeniden düzenlenemez.")
            if void:
                start, end = row["start_at"], row["end_at"]
            else:
                self._validate_times(start, end)
                if end is None and not self.db.conn.execute(
                    "SELECT 1 FROM employees WHERE id=? AND active=1", (row["employee_id"],)
                ).fetchone():
                    raise AppError("Arşivdeki personel için açık kayıt bırakılamaz.")
                self._no_overlap(row["employee_id"], start, end, sid)
            # Saving a correction (or a void) is the admin's review of the record.
            self.db.conn.execute(
                """UPDATE sessions SET start_at=?,end_at=?,voided=?,revision=revision+1,review=''
                   WHERE id=?""",
                (start, end, int(bool(void)), sid),
            )
            after = dict(self.db.conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
            self.db.audit(self.clock.wall(), "admin", "SESSION_VOID" if void else "SESSION_CORRECT",
                          f"session:{sid}", dict(row), after, reason)

    def _validate_times(self, start, end):
        now = self.clock.wall()
        if type(start) is not int or not 946684800 <= start <= now:
            raise AppError("Giriş 2000 yılından sonra ve gelecekte olmayan bir saat olmalı.")
        if end is not None and (type(end) is not int or not start < end <= now):
            raise AppError("Çıkış girişten sonra olmalı ve gelecekte olamaz.")
        if (end if end is not None else now) - start > 7 * 86400:
            raise AppError("Tek kayıt 7 günü aşamaz; tarihleri kontrol edin.")

    def manual_session(self, token, eid, start, end, rate_cents, reason, request_id):
        self.require_admin(token)
        reason = reason_text(reason)
        self._validate_times(start, end)
        valid_cents(rate_cents)
        fingerprint = canonical(["manual", eid, start, end, rate_cents, reason])
        with self.db.transaction():
            duplicate = self._receipt(request_id, fingerprint)
            if duplicate is not None:
                return duplicate
            employee = self.db.conn.execute("SELECT active FROM employees WHERE id=?", (eid,)).fetchone()
            if not employee:
                raise AppError("Personel bulunamadı.")
            if end is None and not employee["active"]:
                raise AppError("Arşivdeki personel için açık kayıt bırakılamaz.")
            self._no_overlap(eid, start, end)
            sid = self.db.conn.execute(
                "INSERT INTO sessions(employee_id,start_at,end_at,rate_cents) VALUES(?,?,?,?)",
                (eid, start, end, rate_cents),
            ).lastrowid
            after = dict(self.db.conn.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
            self.db.audit(self.clock.wall(), "admin", "SESSION_MANUAL", f"session:{sid}",
                          after=after, reason=reason)
            self.db.conn.execute("INSERT INTO receipts VALUES(?,?,?)", (request_id, fingerprint, sid))
        return sid

    def _receipt(self, request_id, fingerprint):
        try:
            uuid.UUID(request_id)
        except (ValueError, TypeError, AttributeError):
            raise AppError("Geçersiz işlem kimliği.")
        row = self.db.conn.execute("SELECT * FROM receipts WHERE request_id=?", (request_id,)).fetchone()
        if row and row["fingerprint"] != fingerprint:
            raise AppError("İşlem kimliği başka bir işlemde kullanılmış.")
        return row["result_id"] if row else None

    def add_payment(self, token, eid, paid_at, cents, kind, note, request_id):
        self.require_admin(token)
        valid_cents(cents, positive=True)
        note = reason_text(note)
        if kind not in ("Ödeme", "Avans"):
            raise AppError("Ödeme türünü seçin.")
        if type(paid_at) is not int or not 946684800 <= paid_at <= self.clock.wall():
            raise AppError("Ödeme tarihi geçersiz veya gelecekte.")
        fingerprint = canonical(["payment", eid, paid_at, cents, kind, note])
        with self.db.transaction():
            duplicate = self._receipt(request_id, fingerprint)
            if duplicate is not None:
                return duplicate
            if not self.db.conn.execute("SELECT 1 FROM employees WHERE id=?", (eid,)).fetchone():
                raise AppError("Personel bulunamadı.")
            recent = self.db.conn.execute("""SELECT id FROM payments WHERE employee_id=?
                AND amount_cents=? AND kind=? AND paid_at=? AND voided=0""",
                                         (eid, cents, kind, paid_at)).fetchone()
            if recent:
                raise AppError("Aynı personel, saat, tutar ve türde ödeme zaten var.")
            pid = self.db.conn.execute("""INSERT INTO payments
                (employee_id,paid_at,amount_cents,kind,note) VALUES(?,?,?,?,?)""",
                                      (eid, paid_at, cents, kind, note)).lastrowid
            self.db.audit(self.clock.wall(), "admin", "PAYMENT_ADD", f"payment:{pid}",
                          after={"employee_id": eid, "paid_at": paid_at, "amount_cents": cents,
                                 "kind": kind, "note": note})
            self.db.conn.execute("INSERT INTO receipts VALUES(?,?,?)", (request_id, fingerprint, pid))
        return pid

    def void_payment(self, token, pid, reason):
        self.require_admin(token)
        reason = reason_text(reason)
        with self.db.transaction():
            row = self.db.conn.execute("SELECT * FROM payments WHERE id=? AND voided=0", (pid,)).fetchone()
            if not row:
                raise AppError("Ödeme bulunamadı veya zaten iptal edilmiş.")
            self.db.conn.execute("UPDATE payments SET voided=1 WHERE id=?", (pid,))
            self.db.audit(self.clock.wall(), "admin", "PAYMENT_VOID", f"payment:{pid}",
                          before=dict(row), after={"voided": True}, reason=reason)

    def payments(self, token, eid=None, since=None, until=None):
        self.require_admin(token)
        return [dict(r) for r in self.db.conn.execute("""SELECT p.*,e.name FROM payments p
            JOIN employees e ON e.id=p.employee_id WHERE (? IS NULL OR p.employee_id=?)
            AND p.paid_at >= COALESCE(?, -1) AND p.paid_at < COALESCE(?, 9223372036854775807)
            ORDER BY paid_at DESC,p.id DESC""", (eid, eid, since, until))]

    def audit_rows(self, token, limit=None):
        self.require_admin(token)
        return [dict(r) for r in self.db.conn.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (-1 if limit is None else int(limit),))]

    def display_time(self, timestamp):
        if timestamp is None:
            return "Açık"
        return datetime.fromtimestamp(timestamp, self.zone).strftime("%d.%m.%Y %H:%M:%S")
