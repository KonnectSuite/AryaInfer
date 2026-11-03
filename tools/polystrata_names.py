#!/usr/bin/env python3
"""Update current product branding to AryaInfer; preserve lineage and compatibility names.

Historical filename retained for existing workflows. Credits, inherited evidence,
URLs, engine identifiers, saved-data paths and historical benchmark records stay intact.
The prose in the docs is tools/aryainfer_names.py's job (this tool skips docs/); this one covers code files.
"""
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
SKIP = ("third_party/", "bench/", "docs/", "src/", "include/", "tests/", "cmake/", "sycl/", "tools/vision/")
KINDS = (".py", ".html", ".js", ".css", ".bat", ".sh", ".yml", ".yaml")
PRODUCT = "AryaInfer"
def rename(text):
    lines = []
    for line in text.splitlines(keepends=True):
        # Credits and compatibility state are intentional upstream references.
        if any(s in line for s in ("github.com/", "settings.json", "PolyStrata-data", "fork of", "lineage", "PolyStrata\"", "PolyStrata'")):
            lines.append(line)
        else:
            lines.append(line.replace("PolyStrata", PRODUCT))
    return "".join(lines)
def files():
    names = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    return [n for n in names if not n.startswith(SKIP) and n.endswith(KINDS)
            and n not in ("tools/polystrata_names.py", "tools/test_polystrata_names.py",
                          "tools/aryainfer_names.py", "tools/test_aryainfer_names.py")]
def read_text(path):
    # newline="": the launchers keep their platform line endings (.sh LF, .bat CRLF), a rename must not convert them
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()
def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
def main():
    check = "--check" in sys.argv[1:]
    changed = 0
    for name in files():
        p = ROOT / name
        old = read_text(p)
        new = rename(old)
        if old != new:
            changed += 1
            print(name)
            if not check:
                write_text(p, new)
    return int(check and changed > 0)
def demo():
    assert rename("PolyStrata web app") == f"{PRODUCT} web app"
    for text in ("fork of PolyStrata", "https://github.com/VecSzn/PolyStrata", "PolyStrata-data"):
        assert rename(text) == text
    assert rename(rename("PolyStrata web app")) == f"{PRODUCT} web app"
if __name__ == "__main__":
    demo()
    sys.exit(main())
