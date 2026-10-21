"""scripts/arsivle.py: release archive outside GitHub (network replaced by a fake)."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("arsivle", Path(__file__).parents[1] / "scripts" / "arsivle.py")
arsivle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arsivle)

COMMIT = "3d16ed62701240a4fd10f22b2bbbc221c0dd172d"
SETUP, PORTABLE, SOURCE = b"setup-exe", b"portable-zip", b"source-zip"


def fake_github(setup_digest=None):
    release = {"target_commitish": COMMIT, "published_at": "2026-10-21T20:37:27Z", "assets": [
        {"name": "VardiyaTakip-Kurulum.exe", "browser_download_url": "u/setup",
         "digest": "sha256:" + (setup_digest or hashlib.sha256(SETUP).hexdigest())},
        {"name": "VardiyaTakip-Windows-x64.zip", "browser_download_url": "u/portable", "digest": None}]}
    calls = []

    def get(url):
        calls.append(url)
        if url.endswith("/releases/tags/son-surum"):
            return json.dumps(release).encode()
        if url.endswith("/pyproject.toml"):
            assert COMMIT in url
            return b'[project]\nversion = "0.2.0"\n'
        return {"u/setup": SETUP, "u/portable": PORTABLE}.get(url) or (SOURCE if COMMIT in url else None)
    return get, calls


def test_archive_stores_release_source_and_checksums(tmp_path):
    get, _ = fake_github()
    folder = arsivle.archive(tmp_path, get, out=lambda _: None)
    assert folder.name == "2026-10-21_v0.2.0_3d16ed6"
    assert (folder / "VardiyaTakip-Kurulum.exe").read_bytes() == SETUP
    assert (folder / "kaynak-3d16ed6.zip").read_bytes() == SOURCE
    assert COMMIT in (folder / "BENIOKU.txt").read_text(encoding="utf-8")
    assert len((folder / "SHA256SUMS").read_text().splitlines()) == 3
    assert arsivle.verify(tmp_path, out=lambda _: None) == 0


def test_archive_is_never_overwritten(tmp_path):
    get, _ = fake_github()
    folder = arsivle.archive(tmp_path, get, out=lambda _: None)
    get, calls = fake_github()
    messages = []
    assert arsivle.archive(tmp_path, get, out=messages.append) == folder
    assert "Zaten arşivde" in messages[0] and not any("u/setup" in c for c in calls)


def test_wrong_download_leaves_no_folder(tmp_path):
    get, _ = fake_github(setup_digest="0" * 64)
    with pytest.raises(SystemExit, match="doğrulanamadı"):
        arsivle.archive(tmp_path, get, out=lambda _: None)
    assert list(tmp_path.iterdir()) == []


def test_verify_finds_damaged_and_missing_files(tmp_path):
    get, _ = fake_github()
    folder = arsivle.archive(tmp_path, get, out=lambda _: None)
    (folder / "VardiyaTakip-Kurulum.exe").write_bytes(b"damaged")
    (folder / "kaynak-3d16ed6.zip").unlink()
    lines = []
    assert arsivle.verify(tmp_path, out=lines.append) == 1
    assert "Kurulum.exe bozulmuş" in lines[0] and "kaynak-3d16ed6.zip eksik" in lines[0]


def test_fetch_falls_back_to_system_curl_on_missing_certificates(monkeypatch):
    import ssl
    import subprocess
    import urllib.error

    def no_certificates(*_, **__):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer certificate"))
    monkeypatch.setattr(arsivle.urllib.request, "urlopen", no_certificates)
    seen = []
    monkeypatch.setattr(arsivle.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, stdout=b"data"))
    assert arsivle.fetch("https://example.invalid/x") == b"data"
    assert seen[0][0] == "curl" and seen[0][-1] == "https://example.invalid/x"
    monkeypatch.setattr(arsivle.urllib.request, "urlopen",
                        lambda *_, **__: (_ for _ in ()).throw(urllib.error.URLError("offline")))
    with pytest.raises(SystemExit, match="İndirilemedi"):
        arsivle.fetch("https://example.invalid/x")
