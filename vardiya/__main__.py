import argparse
import getpass
import logging
import sqlite3
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .backup import closing_backup, restore_database
from .security import AppError
from .service import Service
from .storage import Database, FileLock, default_data_dir, inspect_database


def safe_console():
    """Never crash on Turkish text when output is redirected (cp1252 etc.).

    An interactive Windows console is written as Unicode by Python itself;
    redirected/piped output is forced to UTF-8. The windowed build has no
    streams at all (None) and is left alone.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            if stream.isatty():
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


LOG_BYTES, LOG_KEEP = 1_000_000, 3


def configure_logging(directory: Path):
    """Warnings to application.log, capped at ~4 MB in total (current + 3 older files)."""
    handler = RotatingFileHandler(directory / "application.log", maxBytes=LOG_BYTES,
                                  backupCount=LOG_KEEP, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    for old in [h for h in root.handlers if isinstance(h, RotatingFileHandler)]:
        root.removeHandler(old)
        old.close()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    return handler


def main():
    safe_console()
    parser = argparse.ArgumentParser(description="Çevrimdışı Vardiya Takip")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir(),
                        help="Yerel veri klasörü (ağ/senkronizasyon klasörü kullanmayın)")
    parser.add_argument("--restore", type=Path, help="Uygulama kapalıyken yedekten kurtar")
    parser.add_argument("--check", action="store_true", help="Veri bütünlüğünü denetle")
    parser.add_argument("--upgrade", action="store_true",
                        help="Eski sürüm veriyi güncelle (program açılınca da kendiliğinden yapılır)")
    args = parser.parse_args()
    directory = args.data_dir.resolve()
    db_path = directory / "vardiya.sqlite3"
    try:
        lock = FileLock(directory)
    except (AppError, OSError) as exc:
        if not args.check and not args.restore and not args.upgrade:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication(sys.argv[:1])
            QMessageBox.warning(None, "Vardiya Takip", str(exc))
        else:
            print(str(exc), file=sys.stderr)
        return 1
    configure_logging(directory)
    db = None
    try:
        if args.check:
            errors = inspect_database(db_path)
            print("\n".join(errors) if errors else "Bütünlük kontrolü: sağlam.")
            return int(bool(errors))
        if args.upgrade:
            if not db_path.exists():
                print("Veri dosyası bulunamadı.", file=sys.stderr)
                return 1
            db = Database(db_path)
            print(f"Veri şeması güncellendi. Önceki dosya: {db.upgraded_from}" if db.upgraded_from
                  else "Veri şeması zaten güncel.")
            return 0
        if args.restore:
            password = getpass.getpass("Yönetici şifresi: ")
            archive = restore_database(args.restore.resolve(), db_path, password)
            print(f"Kurtarma tamamlandı. Önceki veriler: {archive}")
            return 0
        from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
        from .ui import CodeDialog, MainWindow, RecoveryKeyDialog, apply_theme, setup_dialog
        app = QApplication(sys.argv[:1])
        app.setApplicationName("VardiyaTakip")
        app.setApplicationDisplayName("Ó'is · Vardiya")
        apply_theme(app)
        try:
            db = Database(db_path)
        except (AppError, sqlite3.Error, OSError) as exc:
            choice = QMessageBox.critical(
                None, "Veri dosyası açılamadı",
                str(exc) + "\n\nVeri silinmedi. Doğrulanmış bir yedekten kurtarma seçmek ister misiniz?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if choice != QMessageBox.StandardButton.Yes:
                return 1
            source, _ = QFileDialog.getOpenFileName(None, "Yedek seç", "", "SQLite (*.sqlite3)")
            if not source:
                return 1
            dialog = CodeDialog("Yedekteki yönetici şifresiyle kurtar", ["yönetici şifresini gir"],
                                lambda codes: restore_database(Path(source), db_path, codes[0]))
            if not dialog.exec():
                return 1
            db = Database(db_path)
        service = Service(db)
        apply_theme(app, service.theme)
        if not service.configured:
            dialog = setup_dialog(service)
            if not dialog.exec():
                return 0
            RecoveryKeyDialog(dialog.result_value).exec()
        window = MainWindow(service)
        window.showMaximized()      # the kiosk fills the screen on any resolution
        result = app.exec()
        if not window.restoring:
            try:
                closing_backup(db)
            except (AppError, sqlite3.Error, OSError):
                logging.exception("Kapanış yedeği alınamadı")
        return result
    except (AppError, sqlite3.Error, OSError) as exc:
        logging.exception("Uygulama işlemi başarısız")
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if db:
            db.close()
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
