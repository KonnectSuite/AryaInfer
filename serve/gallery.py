"""serve/gallery.py - the images AryaInfer generated, kept on disk beside the app.

One folder with `index.json` and one file per image named by 32 hex digits (the name is the access, as
`/v1/images/files/` does it).  The index carries what the grid shows - the prompt, the workflow, the seed, the timings,
the source image an edit came from, a favourite flag - so the gallery survives a restart and is the same in every
browser, which a localStorage list would not be.

A file with no record is left alone and not listed: hand-copied images are the user's, and nothing here deletes what it
did not write.  The index is written atomically (a temporary file moved over the old one), and an unreadable one is
moved aside rather than lost, as serve/webconf.py does for the MCP servers.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

FILE = "index.json"
VERSION = 1
NAME = re.compile(r"^[0-9a-f]{32}\.png$")
DEFAULTS = {"max_files": 500, "max_mib": 8192}


class Gallery:
    """The generated images: files on disk, records in one JSON index."""

    def __init__(self, path: str | Path, settings: dict | None = None, log=None):
        self.dir = Path(path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.settings = {**DEFAULTS, **(settings or {})}
        self.log = log
        self.index_path = self.dir / FILE
        self.items: list[dict] = self._load()

    # ----------------------------------------------------------------------------- the index
    def _load(self) -> list[dict]:
        try:
            with open(self.index_path, encoding="utf-8-sig") as f:
                data = json.load(f)
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            self._aside(str(e))
            return []
        block = data.get("items") if isinstance(data, dict) else None
        if not isinstance(block, list):
            self._aside('expected {"items": [...]}')
            return []
        return [r for r in block if isinstance(r, dict) and NAME.match(str(r.get("file") or ""))]

    def _aside(self, why: str) -> None:
        """Keep an unreadable index under another name; the files stay where they are."""
        target = self.index_path.with_name(f"{FILE}.corrupt-{int(time.time())}")
        try:
            os.replace(self.index_path, target)
            where = f"moved to {target.name}"
        except OSError:
            where = "left as it is"
        self._say(f"the image gallery index could not be read ({why}); {where}")

    def _write(self) -> None:
        body = json.dumps({"version": VERSION, "items": self.items}, indent=1) + "\n"
        tmp = self.index_path.with_name(FILE + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        os.replace(tmp, self.index_path)

    def _say(self, text: str) -> None:
        print(f"[strata] {text}", flush=True)
        if self.log is not None:
            with contextlib.suppress(OSError, ValueError):
                self.log.write(f"[gallery] {text}\n")
                self.log.flush()

    # ----------------------------------------------------------------------------- records
    def add(self, png: bytes, record: dict) -> dict:
        """Keep one PNG and its record -> the record, with its id and file name."""
        if not isinstance(png, (bytes, bytearray)) or not png:
            raise ValueError("the image is empty")
        name = secrets.token_hex(16) + ".png"
        item = {"id": name[:-4], "file": name, "created": int(time.time()), "favorite": False, **record}
        with self.lock:
            (self.dir / name).write_bytes(bytes(png))
            self.items.append(item)
            self.prune()
            self._write()
        return item

    def get(self, image_id: str) -> dict | None:
        with self.lock:
            return next((r for r in self.items if r.get("id") == image_id), None)

    def file(self, name: str) -> Path | None:
        """One stored image by its file name, or None; the name cannot leave the folder."""
        if not NAME.match(name or ""):
            return None
        p = self.dir / name
        return p if p.is_file() else None

    def delete(self, image_ids) -> list[str]:
        """Remove records and files -> the ids that were there."""
        removed = []
        with self.lock:
            keep = []
            for r in self.items:
                if r.get("id") in image_ids:
                    removed.append(r["id"])
                    with contextlib.suppress(OSError):
                        (self.dir / r["file"]).unlink()
                else:
                    keep.append(r)
            if removed:
                self.items = keep
                self._write()
        return removed

    def favorite(self, image_id: str, on: bool | None = None) -> dict | None:
        with self.lock:
            r = self.get(image_id)
            if r is None:
                return None
            r["favorite"] = (not r.get("favorite")) if on is None else bool(on)
            self._write()
            return r

    def list(self, limit: int = 60, before: int | None = None, favorites: bool = False,
             query: str = "") -> dict:
        """Newest first, paged by `created`: -> {items, total, favorites, more}."""
        q = str(query or "").strip().lower()
        with self.lock:
            rows = [r for r in self.items
                    if (not favorites or r.get("favorite"))
                    and (not q or q in str(r.get("prompt") or "").lower())]
            rows.sort(key=lambda r: (int(r.get("created") or 0), str(r.get("id"))), reverse=True)
            page = [r for r in rows if before is None or int(r.get("created") or 0) < int(before)]
            page = page[:max(1, int(limit))]
            favs = sum(1 for r in self.items if r.get("favorite"))
        return {"items": page, "total": len(rows), "favorites": favs,
                "more": len(rows) > len(page)}

    def prune(self) -> list[str]:
        """Hold the folder to max_files / max_mib, oldest first; a favourite goes only when it is all that is left."""
        removed = []
        limit = int(self.settings.get("max_files") or 0)
        max_mib = float(self.settings.get("max_mib") or 0)
        with self.lock:
            def size_of(r) -> int:
                with contextlib.suppress(OSError):
                    return (self.dir / r["file"]).stat().st_size
                return 0
            total = sum(size_of(r) for r in self.items)

            def over() -> bool:
                nonlocal total
                return (limit > 0 and len(self.items) > limit) or (max_mib > 0 and total > max_mib * 1048576)

            if not over():
                return removed
            ordered = sorted(self.items, key=lambda r: (bool(r.get("favorite")), int(r.get("created") or 0)))
            for r in ordered:
                if not over():
                    break
                if r.get("favorite") and any(not x.get("favorite") for x in self.items):
                    continue                        # favourites last, and only when nothing else is left
                total -= size_of(r)
                with contextlib.suppress(OSError):
                    (self.dir / r["file"]).unlink()
                self.items.remove(r)
                removed.append(r["id"])
        if removed:
            self._say(f"pruned {len(removed)} old image(s) to keep the gallery within its limit")
        return removed

    def status(self) -> dict:
        with self.lock:
            return {"files": len(self.items), "favorites": sum(1 for r in self.items if r.get("favorite")),
                    "dir": str(self.dir), "max_files": int(self.settings.get("max_files") or 0),
                    "max_mib": float(self.settings.get("max_mib") or 0)}
