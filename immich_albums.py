#!/usr/bin/env python3
"""Sync Immich photos into albums based on their original folder structure.

Folder layout assumed: <root>/<YYYY>/<MM - Name>/file.ext  or  <root>/<YYYY>/<Name>/file.ext

Album naming rule (deterministic):
    - "MM - Name"  -> "Name"
    - "Name"       -> "Name YYYY"

The script is resumable: progress is persisted to immich_albums.csv after each
album creation and every batch of asset assignments. Re-running picks up where
it left off.

Environment (set in shell or in a .env file next to this script):
    IMMICH_SERVER_URL   e.g. https://immich.example.com
    IMMICH_API_KEY      API key from the Immich web UI

Usage:
    python3 immich_albums.py [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from pathlib import Path
from typing import Iterable

import requests
from dotenv import load_dotenv


CSV_PATH = Path(__file__).resolve().parent / "immich_albums.csv"
PAGE_SIZE = 1000
SAVE_EVERY = 50

CSV_FIELDS = [
    "filename",
    "path",
    "album_name",
    "album_year",
    "album_id",
    "album_is_generated",
    "photo_is_added_to_album",
    "asset_id",
]


# --------------------------------------------------------------------------- #
# Album name derivation
# --------------------------------------------------------------------------- #

_YEAR_RE = re.compile(r"^\d{4}$")
_MM_PREFIX_RE = re.compile(r"^\d{1,2}\s*-\s*(.+)$")

# Special-case folder mappings. Each entry is (path-segment-sequence, album_name).
# The sequence must appear as consecutive folder segments anywhere in the path.
# Checked before the year-based rule and ignores year (album_year is "").
# Longer sequences should come first so more specific matches win.
PATH_OVERRIDES: list[tuple[tuple[str, ...], str]] = [
    (("Case", "Badia"), "Badia"),
    (("Case", "Ciliegio"), "Ciliegio"),
    (("Case", "Remac"), "REMAC"),
    (("Farmacia",), "Farmacia"),
]


def _match_override(parts: tuple[str, ...]) -> str | None:
    for needle, album in PATH_OVERRIDES:
        n = len(needle)
        for i in range(len(parts) - n + 1):
            if parts[i : i + n] == needle:
                return album
    return None


def derive_album(path: str) -> tuple[str, str]:
    """Return (album_display_name, year) for a given asset path.

    Examples:
        /archive/2024/11 - Roma/x.jpg      -> ("Roma", "2024")
        /archive/2024/Varie/x.jpg          -> ("Varie 2024", "2024")
        /archive/Farmacia/x.jpg            -> ("Farmacia", "")
        /archive/Case/Badia/2024/x.jpg     -> ("Badia", "")
    """
    parts = Path(path).parts
    override = _match_override(parts)
    if override is not None:
        return override, ""

    for i, part in enumerate(parts):
        if _YEAR_RE.match(part) and i + 1 < len(parts) - 1:
            year = part
            folder = parts[i + 1]
            m = _MM_PREFIX_RE.match(folder)
            if m:
                return m.group(1).strip(), year
            return f"{folder} {year}", year
    raise ValueError(f"cannot derive album from path: {path!r}")


# --------------------------------------------------------------------------- #
# CSV helpers
# --------------------------------------------------------------------------- #


def load_csv() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_csv(rows: list[dict]) -> None:
    tmp = CSV_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(CSV_PATH)


def to_bool(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


# --------------------------------------------------------------------------- #
# Immich REST client
# --------------------------------------------------------------------------- #


class ImmichClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "x-api-key": api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def iter_assets(self) -> Iterable[dict]:
        page: int | None = 1
        while page is not None:
            r = self.session.post(
                f"{self.base_url}/api/search/metadata",
                json={"page": page, "size": PAGE_SIZE, "withExif": False},
                timeout=120,
            )
            r.raise_for_status()
            data = r.json()
            block = data.get("assets") or {}
            for item in block.get("items", []):
                yield item
            next_page = block.get("nextPage")
            page = int(next_page) if next_page else None

    def list_albums(self) -> list[dict]:
        r = self.session.get(f"{self.base_url}/api/albums", timeout=60)
        r.raise_for_status()
        return r.json()

    def create_album(self, name: str) -> str:
        r = self.session.post(
            f"{self.base_url}/api/albums",
            json={"albumName": name},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["id"]

    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> list[dict]:
        r = self.session.put(
            f"{self.base_url}/api/albums/{album_id}/assets",
            json={"ids": asset_ids},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()


# --------------------------------------------------------------------------- #
# Pipeline steps
# --------------------------------------------------------------------------- #


def step1_collect(client: ImmichClient, rows: list[dict]) -> list[dict]:
    if rows:
        print(f"[1/2] using existing CSV ({len(rows)} rows) at {CSV_PATH.name}")
        return rows

    print("[1/2] fetching assets from Immich…")
    collected: list[dict] = []
    skipped = 0
    for asset in client.iter_assets():
        path = asset.get("originalPath") or ""
        try:
            album_name, year = derive_album(path)
        except ValueError:
            skipped += 1
            continue
        collected.append(
            {
                "filename": Path(path).name,
                "path": path,
                "album_name": album_name,
                "album_year": year,
                "album_id": "",
                "album_is_generated": "False",
                "photo_is_added_to_album": "False",
                "asset_id": asset["id"],
            }
        )
        if len(collected) % 5000 == 0:
            print(f"    fetched {len(collected)} so far…")

    save_csv(collected)
    print(f"    saved {len(collected)} rows (skipped {skipped} unparseable paths)")
    return collected


def step2_assign(
    client: ImmichClient, rows: list[dict], limit: int | None = None
) -> None:
    print("[2/2] creating albums and adding photos…")
    if limit is not None:
        print(f"    will stop after {limit} newly-added photo(s)")

    # Rebuild (name, year) -> album_id from prior runs.
    album_index: dict[tuple[str, str], str] = {}
    for row in rows:
        if row["album_id"]:
            album_index[(row["album_name"], row["album_year"])] = row["album_id"]

    # Existing Immich albums available to claim. A given album_id can only be
    # claimed by one (name, year) pair to honour the "same name different year"
    # rule — once we use one, we won't reuse it for the other year.
    remote = client.list_albums()
    free_by_name: dict[str, list[str]] = {}
    claimed = set(album_index.values())
    for alb in remote:
        if alb["id"] in claimed:
            continue
        free_by_name.setdefault(alb["albumName"], []).append(alb["id"])

    total = len(rows)
    done = sum(1 for r in rows if to_bool(r["photo_is_added_to_album"]))
    print(f"    {done}/{total} already added; processing the remaining {total - done}…")

    processed_since_save = 0
    processed_this_run = 0
    for i, row in enumerate(rows):
        if to_bool(row["photo_is_added_to_album"]):
            continue
        if limit is not None and processed_this_run >= limit:
            save_csv(rows)
            print(f"    reached --limit {limit}; stopping.")
            return

        key = (row["album_name"], row["album_year"])

        if not row["album_id"]:
            if key in album_index:
                row["album_id"] = album_index[key]
                row["album_is_generated"] = "False"
            else:
                available = free_by_name.get(row["album_name"], [])
                if available:
                    album_id = available.pop(0)
                    row["album_id"] = album_id
                    row["album_is_generated"] = "False"
                else:
                    album_id = client.create_album(row["album_name"])
                    row["album_id"] = album_id
                    row["album_is_generated"] = "True"
                    print(f"    + created album {row['album_name']!r} ({row['album_year']})")
                album_index[key] = row["album_id"]
                save_csv(rows)  # persist album_id immediately

        try:
            results = client.add_assets_to_album(row["album_id"], [row["asset_id"]])
            ok = True
            for item in results:
                if not item.get("success") and item.get("error") != "duplicate":
                    ok = False
                    print(
                        f"    ! failed to add {row['filename']}: {item.get('error')}"
                    )
            row["photo_is_added_to_album"] = "True" if ok else "False"
        except requests.HTTPError as e:
            print(f"    ! HTTP error on {row['filename']}: {e}")
            continue

        processed_since_save += 1
        processed_this_run += 1
        if processed_since_save >= SAVE_EVERY:
            save_csv(rows)
            processed_since_save = 0
            print(f"    progress: {i + 1}/{total}")

    save_csv(rows)
    print("    done.")


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="stop after adding N photos to albums in this run (step 2 only).",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    if args.limit is not None and args.limit <= 0:
        print("error: --limit must be a positive integer.", file=sys.stderr)
        return 2

    load_dotenv(Path(__file__).resolve().parent / ".env")
    server = os.environ.get("IMMICH_SERVER_URL")
    api_key = os.environ.get("IMMICH_API_KEY")
    if not server or not api_key:
        print(
            "error: set IMMICH_SERVER_URL and IMMICH_API_KEY in the environment "
            "or in a .env file next to this script.",
            file=sys.stderr,
        )
        return 2

    client = ImmichClient(server, api_key)
    rows = load_csv()
    rows = step1_collect(client, rows)
    step2_assign(client, rows, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
