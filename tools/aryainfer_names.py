#!/usr/bin/env python3
r"""Update current product branding to AryaInfer; preserve lineage, URLs, identifiers and saved-data paths.

AryaInfer is this fork's product name.  The repository it lives in is still KonnectSuite/AryaInfer, so a
pass over the docs renames the name *where it stands for the product* and leaves alone:

- the two projects this fork came from (Strata, PolyStrata) and any github.com URL;
- a folder named after the repository: "the AryaStrata folder", "the AryaStrata checkout" - a reader who
  cloned the repository has a folder with that name, and telling them to rename it would break the steps;
- file names and saved paths: `AryaStrata-Tray.vbs`, `AryaStrata*.md`, `AryaStrata.json`, and every
  `AryaStrata` that follows a `/` or a `\` in a path or URL;
- text inside a code span or a fenced code block - a reader copies those as they are, and the programs and
  options they name keep their names.

Run it over the markdown docs; `--check` prints the files that still need the rename and changes nothing.

    python tools/aryainfer_names.py            # rename
    python tools/aryainfer_names.py --check    # report, write nothing

The file rename itself is a separate step (git mv docs/ARYASTRATA.md docs/ARYAINFER.md); this tool rewrites
the links to it.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME, NEW = "AryaStrata", "AryaInfer"

# a reader follows these literally: they name a path, a file or a folder, not the product
KEEP_AFTER = re.compile(r"(?: Data|-Tray|\.md\b|\.py\b|\.bat\b|\.vbs\b|\.json\b|\.log\b|\.zip\b|"
                        r"\s+(?:folder|folder's|data folder|checkout|clone))", re.IGNORECASE)
CODE_SPAN = re.compile(r"(`[^`\n]*`)")
FENCE = re.compile(r"^\s*(?:```|~~~)")

SKIP = ("bench/", "third_party/", "docs/paper/", "docs/UPSTREAM_README.md", ".venv/", "build-env/", "tmp/")
KINDS = (".md",)


def _outside_code(line):
    """(part, is_code) for one line: the pieces outside a `code span` alternate with the spans themselves."""
    parts = CODE_SPAN.split(line)
    return [(part, i % 2 == 1) for i, part in enumerate(parts)]


def rename(text):
    out, fenced = [], False
    for line in text.splitlines(keepends=True):
        if FENCE.match(line):
            fenced = not fenced
            out.append(line)
            continue
        if fenced:
            out.append(line)
            continue
        new_line = "".join(part if is_code else _rename_outside(part) for part, is_code in _outside_code(line))
        out.append(new_line)
    return "".join(out)


def _rename_outside(part):
    def keep(m):
        before = part[:m.start()]
        if before.endswith("/") or before.endswith("\\"):
            return True                     # a path or a URL's last segment
        return bool(KEEP_AFTER.match(part, m.end()))

    def sub(m):
        return NEW if not keep(m) else m.group(0)

    return re.sub(NAME, sub, part)


def rename_links(text):
    """docs/ARYASTRATA.md -> docs/ARYAINFER.md: the file was renamed with git mv, the links follow it."""
    return re.sub(r"ARYASTRATA\.md", "ARYAINFER.md", text)


def read_text(path: Path) -> str:
    """A file's text with its own line endings: the docs mix LF and CRLF, and a pass must not convert them."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def files():
    """The markdown the pass owns: the docs and the front pages, the historical records left out."""
    try:
        names = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    except (OSError, subprocess.CalledProcessError):
        names = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*.md")]
    return [n for n in names
            if n.endswith(KINDS) and not n.startswith(SKIP)
            and n not in ("tools/aryainfer_names.py", "tools/test_aryainfer_names.py")]


def main():
    check = "--check" in sys.argv[1:]
    changed = 0
    for name in files():
        p = ROOT / name
        try:
            old = read_text(p)
        except (OSError, UnicodeDecodeError) as e:
            print(f"{name}: skipped ({e})", file=sys.stderr)
            continue
        new = rename_links(rename(old))
        if old != new:
            changed += 1
            print(name)
            if not check:
                write_text(p, new)
    return int(check and changed > 0)


def demo():
    assert rename("AryaStrata web app") == "AryaInfer web app"
    assert rename(rename("AryaStrata web app")) == "AryaInfer web app"       # a second pass changes nothing
    # the lineage and the repository are named by their URLs
    for text in ("fork of [PolyStrata](https://github.com/VecSzn/PolyStrata)",
                 "clone https://github.com/KonnectSuite/AryaInfer",
                 "an [issue](https://github.com/KonnectSuite/AryaInfer/issues)"):
        assert rename(text) == text
    # a folder the reader really has, a file name, and the tray script
    for text in ("run `./setup.sh` in the AryaStrata folder",
                 "the AryaStrata data folder",
                 "move the AryaStrata checkout elsewhere",
                 r"C:\Users\you\AryaStrata\tools\strata_mcp.py",
                 "AryaStrata-Tray.vbs starts it again",
                 "the record AryaStrata.md stays"):
        assert rename(text) == text
    # a code span and a fenced block are left as a reader copies them; the product mentioned next to them is renamed
    for text in ("a new folder whose name starts with `AryaStrata`",
                 "```\nStart AryaStrata from the folder\n```"):
        assert rename(text) == text
    assert rename('add `"mcp_servers"` to a AryaStrata run config') == \
        'add `"mcp_servers"` to a AryaInfer run config'
    assert rename_links("[host findings](ARYASTRATA.md)") == "[host findings](ARYAINFER.md)"


if __name__ == "__main__":
    demo()
    sys.exit(main())
