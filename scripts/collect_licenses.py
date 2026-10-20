"""Retain installed distribution license metadata beside the application."""
import importlib.metadata
import shutil
import sys
from pathlib import Path

destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
lines = []
for name in ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6",
             "openpyxl", "et_xmlfile", "tzdata", "pyinstaller"):
    dist = importlib.metadata.distribution(name)
    lines.append(f"{dist.metadata['Name']}=={dist.version}\n"
                 f"License: {dist.metadata.get('License-Expression') or dist.metadata.get('License', '')}\n")
    for entry in dist.files or []:
        if any(word in str(entry).lower() for word in ("license", "copying", "copyright", "notice")):
            source = Path(dist.locate_file(entry))
            if source.is_file():
                # Strip package-relative parents; keep nested library names.
                clean_parts = [part for part in entry.parts if part not in (".", "..")]
                target = destination / name / Path(*clean_parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
(destination / "VERSIONS.txt").write_text("\n".join(lines), encoding="utf-8")
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.exists():
    shutil.copy2(python_license, destination / "PYTHON-LICENSE.txt")
