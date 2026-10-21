"""Turn a pytest JUnit XML report into GitHub Actions annotations.

Annotations are readable through the checks API even where raw job logs are
not, so CI failures stay diagnosable from restricted environments.
Usage: python scripts/ci_annotate.py test-results.xml
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def escape(text):
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def main(path):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    hang = Path("hang-report.txt")
    if hang.exists():
        print(f"::error title=Takılan test::{escape(hang.read_text(encoding='utf-8', errors='replace')[-3500:])}")
    report = Path(path)
    if not report.exists():
        print("::error title=pytest::Test raporu üretilmedi (kurulum veya toplama hatası).")
        return 1
    root = ET.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    totals = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    print(f"::notice title=pytest::{totals['tests']} test, {totals['failures']} başarısız, "
          f"{totals['errors']} hata, {totals['skipped']} atlandı")
    shown = 0
    for case in root.iter("testcase"):
        for problem in list(case.findall("failure")) + list(case.findall("error")):
            if shown >= 45:
                break
            name = f"{case.get('classname')}::{case.get('name')}"
            body = (problem.get("message") or "") + "\n" + (problem.text or "")
            # Keep the tail: assertion and the innermost frames matter most.
            print(f"::error title={escape(name)}::{escape(body[-1800:])}")
            shown += 1
    return 1 if totals["failures"] or totals["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "test-results.xml"))
