# Vardiya Takip · Ó'is coffee & eatery

Offline staff time tracking for a café/restaurant (Windows 10/11 kiosk, also runs on macOS from source).
Python 3.12, PySide6 (Qt), SQLite, openpyxl. All user-facing text is **Turkish**; talk to the owner in Turkish.

## Layout

| Path | Role |
|---|---|
| `vardiya/service.py` | Business rules: auth, locks, attendance, corrections, payments, clock checks, business day |
| `vardiya/storage.py` | SQLite schema (version 2), transactions, append-only hashed audit chain, integrity check |
| `vardiya/reports.py` | Business-day split, exact money (Fraction → kuruş), CSV/XLSX export |
| `vardiya/backup.py` | Verified backups, retention, restore |
| `vardiya/security.py` | 4-digit codes (`PIN_LENGTH`), weak-code rules, PBKDF2 |
| `vardiya/theme.py` | Qt-free: colour tokens (dark/night/light), Turkish casing, stylesheet |
| `vardiya/widgets.py` | Custom-painted Qt widgets: Ó ring, keypad (RoundKey), timeline, heatmap, welcome |
| `vardiya/ui.py` | Screens: kiosk `MainWindow`, `PinDialog`, `CodeDialog`, `AdminDialog` |
| `installer/VardiyaTakip.iss` | Inno Setup installer (per-user, Turkish, UTF-8 **with BOM**) |
| `scripts/screenshots.py` | Renders all screens with sample data (CI publishes them) |

## Decisions already made with the owner (do not undo without asking)

- Staff PIN **and** admin code are 4 digits. Weak codes (1111, 1234/4321, 1212, 1122) rejected.
  Duplicate codes are allowed on purpose: rejecting "same as admin/other staff" would leak that code.
  Never reveal anything about other people's codes in any message.
- Locks escalate: staff 30 s → 5 min; admin 5 → 15 → 30 min → 1 h per attempt.
- Business day starts 05:00 (configurable 0–12); the café opens 09:00 and closes ~01:00.
  Open records past the boundary are flagged "çıkış unutuldu"; the app never invents an exit time.
- Clock alerts never block staff; records are flagged for admin review instead.
- Visual identity: logo colour bordo `#3a0300` + cream; Jost (display) and Quicksand (text) are bundled.
  Each person is a thin "Ó" ring. **No decorative brand copy** ("şapka yandı" etc. was removed on request);
  screens show plain information only.
- Kiosk: full screen, own on-screen keypad. Text fields in PIN/admin code dialogs must never take focus
  (Windows touch keyboard must not pop up). Touch feedback = short self-completing pulse/ripple.
- Must fit small laptop screens (use `fit_to_screen`, scrollable admin pages).

## Working rules

- Tests: `python -m pytest -q` (Qt tests need PySide6; core tests run without it).
  Every behaviour change gets a test. Qt tests run offscreen; conftest has watchdogs that turn
  unexpected `QMessageBox`es, hangs and native crashes into readable failures.
- CI (`.github/workflows/windows.yml`, Windows) runs tests, screenshots, PyInstaller package,
  installer build, silent install/uninstall smoke tests, and publishes the `son-surum` release.
  Raw job logs may be unreadable from restricted environments; read results via check-run
  **annotations** (`gh api repos/mfcknt/vardiya-takip/check-runs/<job>/annotations`).
  Screenshots are force-pushed to branch `ci-screenshots`; review them visually before reporting UI work.
- Qt stylesheet rules override `setFont`; style labels through object names in `theme.stylesheet`.
- Schema changes need a migration plan once real data exists (currently none in production).
- Commit messages in Turkish.

## Open items discussed but not done

Off-machine backup (USB reminder/copy), admin recovery key, schema migration framework,
period closing (lock paid months; also speeds up reports), compressed backups, background
heavy work, staff self-view, payment receipts, code signing.
