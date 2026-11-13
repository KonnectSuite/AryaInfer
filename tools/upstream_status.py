#!/usr/bin/env python3
r"""Report which Strata and PolyStrata sources this tree builds, and what upstream has released since.

setup.py --build compiles src/ (Strata's engine) and src/poly (PolyStrata) from this checkout, not from
upstream, so a build is only as new as the last merge into this repository.  upstream.json records that
merge; this tool reads it and, with --check, compares it with each project's newest release.  A pin that
is behind means the engine setup compiles here is older than the one upstream ships - the merge, not a
build option, is what closes the gap.

    python tools/upstream_status.py            # the pin, no network
    python tools/upstream_status.py --check    # compare with upstream; 1 when either has released since

The newest release comes from GitHub's Atom feed: no token, no rate limit, and the feed lists the newest
release first.  The tag it names is compared with a leading "v" ignored, because the two projects tag
"v0.2.13" and "0.1.45-poly.9".
"""
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S)
TAG = re.compile(r'/releases/tag/([^"<>]+)')
DATE = re.compile(r"<updated>([^<]+)</updated>")
PROJECTS = ("strata", "polystrata")


def norm(tag):
    """A tag for comparison: the projects differ in case and in the leading "v"."""
    return tag.strip().lstrip("vV").lower()


def pin():
    return json.loads((ROOT / "upstream.json").read_text(encoding="utf-8"))


def parse_newest(body):
    """(tag, date) of the first entry in a releases feed, or None when the feed has no entry."""
    entry = ENTRY.search(body)
    if entry is None:
        return None
    e = entry.group(1)
    tag, date = TAG.search(e), DATE.search(e)
    return (tag.group(1) if tag else "?"), (date.group(1)[:10] if date else "?")


def newest(repo, timeout=20):
    """The newest release of `repo`, or None when the feed cannot be read."""
    url = f"https://github.com/{repo}/releases.atom"
    req = urllib.request.Request(url, headers={"User-Agent": "aryainfer-upstream-status"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return parse_newest(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError):
        return None


def main(argv):
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__.strip())
        return 0
    unknown = [a for a in argv if a != "--check"]
    if unknown:
        print(f"unknown option: {unknown[0]} (try --check)")
        return 2
    check = "--check" in argv
    pinned = pin()
    rows, behind, unread = [], 0, []
    for key in PROJECTS:
        entry = pinned.get(key) or {}
        repo, tag, commit = entry.get("repo", "?"), entry.get("tag", "?"), (entry.get("commit") or "")[:8]
        latest = newest(repo) if check else None
        if check and latest is None:
            unread.append(repo)
        newer = check and latest is not None and norm(latest[0]) != norm(tag)
        behind += 1 if newer else 0
        state = "" if not check else ("newer release" if newer else "newest release")
        rows.append((key, f"{tag} ({commit})", f"{latest[0]} ({latest[1]})" if latest else "-", state))
    width = max(len(r[0]) for r in rows) + 2
    print(f"{'project':<{width}}{'this tree builds':<28}{'upstream':<28}state" if check
          else f"{'project':<{width}}this tree builds")
    for key, mine, theirs, state in rows:
        print(f"{key:<{width}}{mine:<28}{theirs:<28}{state}" if check else f"{key:<{width}}{mine}")
    if not check:
        print("\n--check reads both projects' release feeds and says which have released since.")
        return 0
    if unread:
        print(f"\n  [!]  could not read the release feed of {', '.join(unread)} - the pin above is all this says")
        return 2
    if behind:
        print(f"\n  {behind} of {len(PROJECTS)} upstream projects have released since the merge in upstream.json:")
        print("  the sources this tree builds are older than upstream's.  Merge, then update upstream.json")
        print("  in the same commit (docs/INSTALL.md, 'Building from source').")
        return 1
    print(f"\n  Both projects are at their newest release: this tree builds what upstream ships.")
    return 0


def demo():
    assert norm("v0.2.13") == norm("0.2.13") == "0.2.13"
    assert norm("0.1.45-poly.9") == "0.1.45-poly.9" != norm("0.1.45-poly.6")
    feed = ('<feed><entry><id>tag:github.com,2008:Repository/1/v0.2.13.1</id>'
            '<updated>2026-11-09T17:45:46Z</updated>'
            '<link rel="alternate" type="text/html" href="https://github.com/Niko1221/Strata/releases/tag/v0.2.13.1"/>'
            '<title>Strata 0.2.13</title></entry></feed>')
    assert parse_newest(feed) == ("v0.2.13.1", "2026-11-09")
    assert parse_newest("<feed></feed>") is None
    pinned = pin()                                     # both projects are recorded, with what a merge changes
    for key in PROJECTS:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+", pinned[key]["repo"]), key
        assert re.fullmatch(r"[0-9a-f]{40}", pinned[key]["commit"]), key
        assert pinned[key]["tag"], key


if __name__ == "__main__":
    demo()
    sys.exit(main(sys.argv[1:]))
