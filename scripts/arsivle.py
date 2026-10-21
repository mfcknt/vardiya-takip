"""Copy the published Windows release (and its source code) into an archive outside GitHub.

Usage:
  python scripts/arsivle.py <arşiv-klasörü>            # son-surum'u arşive ekle
  python scripts/arsivle.py <arşiv-klasörü> --dogrula  # arşivdeki tüm sürümleri denetle

Each release goes into its own folder "<tarih>_v<sürüm>_<commit>" with the installer, the
portable zip, the source code of that exact commit, SHA256SUMS and a BENIOKU.txt. Nothing in
the archive is ever overwritten or deleted. Standard library only, so it keeps working
without this project's environment. Point it at a USB disk or a cloud-synced folder.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "mfcknt/vardiya-takip"
TAG = "son-surum"
SUMS = "SHA256SUMS"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "vardiya-arsiv"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.read()
    except urllib.error.URLError as exc:
        if not isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise SystemExit(f"İndirilemedi ({exc.reason}): {url}")
    # python.org Python on macOS ships without CA certificates; the system curl
    # (macOS, Windows 10+) verifies against the operating system's store instead.
    try:
        return subprocess.run(["curl", "-fsSL", "--max-time", "600", url],
                              capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"İndirilemedi ({exc}): {url}")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def release_info(get, repo=REPO, tag=TAG):
    """(folder name, commit, [(file name, url, expected sha256 or None)])."""
    release = json.loads(get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}"))
    commit = release["target_commitish"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit(f"Sürümün commit bilgisi beklenmedik: {commit}")
    pyproject = get(f"https://raw.githubusercontent.com/{repo}/{commit}/pyproject.toml").decode()
    version = re.search(r'^version = "(.+)"', pyproject, re.M).group(1)
    files = [(a["name"], a["browser_download_url"], (a.get("digest") or "").removeprefix("sha256:") or None)
             for a in release["assets"]]
    files.append((f"kaynak-{commit[:7]}.zip", f"https://github.com/{repo}/archive/{commit}.zip", None))
    return f"{release['published_at'][:10]}_v{version}_{commit[:7]}", commit, files


def readme(name, commit, repo=REPO):
    return f"""Vardiya Takip · arşivlenmiş sürüm {name}

Kurulum (Windows 10/11): VardiyaTakip-Kurulum.exe → çift tıklayın → İleri → Kur.
Kurulumsuz: VardiyaTakip-Windows-x64.zip → Tümünü ayıkla → VardiyaTakip.exe.
Kayıtlar programla değil %LOCALAPPDATA%\\VardiyaTakip klasöründe durur; yeniden kurmak onları silmez.

Kaynak kod: kaynak-{commit[:7]}.zip (commit {commit}).
Yeniden derlemek için içindeki docs/WINDOWS.md'ye bakın.
Çevrimiçi karşılığı: https://github.com/{repo}/commit/{commit}

Dosyalar bozulmamış mı? SHA256SUMS içindeki değerlerle karşılaştırın:
  Windows:  certutil -hashfile VardiyaTakip-Kurulum.exe SHA256
  macOS:    shasum -a 256 -c SHA256SUMS
ya da: python scripts/arsivle.py <arşiv-klasörü> --dogrula
"""


def archive(root: Path, get=fetch, out=print):
    root = Path(root)
    name, commit, files = release_info(get)
    target = root / name
    if target.exists():
        problems = verify_folder(target)
        out(f"Zaten arşivde: {target}" + (" (UYARI: " + "; ".join(problems) + ")" if problems else ""))
        return target
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".{name}.yarim"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        sums = []
        for file_name, url, expected in files:
            out(f"İndiriliyor: {file_name}")
            data = get(url)
            digest = sha256(data)
            if expected and digest != expected:
                raise SystemExit(f"{file_name} doğrulanamadı (SHA-256 uyuşmuyor); arşive eklenmedi.")
            (staging / file_name).write_bytes(data)
            sums.append(f"{digest}  {file_name}\n")
        (staging / SUMS).write_text("".join(sums), encoding="utf-8")
        (staging / "BENIOKU.txt").write_text(readme(name, commit), encoding="utf-8")
        for path in staging.iterdir():
            with open(path, "r+b") as handle:
                os.fsync(handle.fileno())
        staging.rename(target)          # the folder appears only when complete
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    out(f"Arşivlendi: {target}")
    return target


def verify_folder(folder: Path):
    sums = folder / SUMS
    if not sums.exists():
        return [f"{SUMS} yok"]
    problems = []
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, _, file_name = line.partition("  ")
        path = folder / file_name
        if not path.exists():
            problems.append(f"{file_name} eksik")
        elif sha256(path.read_bytes()) != digest:
            problems.append(f"{file_name} bozulmuş")
    return problems


def verify(root: Path, out=print):
    folders = sorted(p for p in Path(root).iterdir() if p.is_dir() and not p.name.startswith("."))
    bad = 0
    for folder in folders:
        problems = verify_folder(folder)
        bad += bool(problems)
        out(f"{'SORUN' if problems else 'sağlam'}  {folder.name}" + (": " + "; ".join(problems) if problems else ""))
    out(f"{len(folders)} sürüm, {bad} sorunlu.")
    return bad


def main(argv=None):
    parser = argparse.ArgumentParser(description="Yayımlanan sürümü GitHub dışında arşivle")
    parser.add_argument("hedef", type=Path, help="Arşiv klasörü (USB disk veya bulutla eşitlenen klasör)")
    parser.add_argument("--dogrula", action="store_true", help="Arşivdeki sürümleri SHA-256 ile denetle")
    args = parser.parse_args(argv)
    if args.dogrula:
        return int(bool(verify(args.hedef)))
    archive(args.hedef)
    return 0


if __name__ == "__main__":
    sys.exit(main())
