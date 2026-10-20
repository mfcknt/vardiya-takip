# Build on the target OS; Windows binaries cannot be cross-built from macOS.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=[],
    datas=collect_data_files("tzdata"),
    hiddenimports=["openpyxl", *collect_submodules("tzdata")],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
app = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VardiyaTakip",
          debug=False, strip=False, upx=False, console=False)
maintenance = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VardiyaBakim",
                  debug=False, strip=False, upx=False, console=True)
coll = COLLECT(app, maintenance, a.binaries, a.datas,
               strip=False, upx=False, name="VardiyaTakip")
