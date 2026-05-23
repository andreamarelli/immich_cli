#!/usr/bin/env python3
"""Share all Immich albums with a target user.

Step 1: list every album with its current share recipients -> immich_album_shares.csv.
Step 2: for each album where the target user is not yet a recipient, share it.

Resumable: progress is persisted to the CSV after every album-creation/share.
Re-running picks up where the previous run stopped.

Environment (.env next to this script, or shell):
    IMMICH_SERVER_URL
    IMMICH_API_KEY
    IMMICH_SHARE_WITH_USER_ID  target user UUID
    IMMICH_SHARE_ROLE          "viewer" (default) or "editor"

Usage:
    python3 immich_share_albums.py [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


CSV_PATH = Path(__file__).resolve().parent / "immich_album_shares.csv"
SAVE_EVERY = 25

CSV_FIELDS = [
    "album_id",
    "album_name",
    "owner_email",
    "shared_with",
    "target_already_shared",
    "share_added",
    "error",
]


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

    def list_albums(self) -> list[dict]:
        r = self.session.get(f"{self.base_url}/api/albums", timeout=60)
        r.raise_for_status()
        return r.json()

    def get_album(self, album_id: str) -> dict:
        r = self.session.get(
            f"{self.base_url}/api/albums/{album_id}",
            params={"withoutAssets": "true"},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    def share_album(self, album_id: str, user_id: str, role: str) -> None:
        r = self.session.put(
            f"{self.base_url}/api/albums/{album_id}/users",
            json={"albumUsers": [{"userId": user_id, "role": role}]},
            timeout=60,
        )
        r.raise_for_status()


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
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(CSV_PATH)


def to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


def resolve_target_user() -> str:
    """Return the share target's user UUID from the environment."""
    user_id = os.environ.get("IMMICH_SHARE_WITH_USER_ID", "").strip()
    if not user_id:
        raise SystemExit("set IMMICH_SHARE_WITH_USER_ID in .env.")
    return user_id


def _shared_users_summary(album: dict) -> tuple[list[str], list[str]]:
    """Return (user_ids, user_labels) currently sharing the album."""
    ids: list[str] = []
    labels: list[str] = []
    for au in album.get("albumUsers") or []:
        user = au.get("user") or {}
        uid = user.get("id")
        if not uid:
            continue
        ids.append(uid)
        labels.append(user.get("email") or uid)
    return ids, labels


def step1_collect(
    client: ImmichClient, target_id: str, rows: list[dict]
) -> list[dict]:
    if rows:
        print(f"[1/2] using existing CSV ({len(rows)} rows) at {CSV_PATH.name}")
        return rows

    print("[1/2] fetching albums…")
    albums = client.list_albums()

    # Some Immich versions omit albumUsers from the list endpoint. If the first
    # album with non-empty shares looks empty, fall back to per-album fetch.
    need_detail = albums and all(not (a.get("albumUsers") or []) for a in albums)
    if need_detail:
        print("    list endpoint returned no share info; fetching per-album details…")
        albums = [client.get_album(a["id"]) for a in albums]

    new_rows: list[dict] = []
    for alb in albums:
        shared_ids, shared_labels = _shared_users_summary(alb)
        already = target_id in shared_ids
        new_rows.append(
            {
                "album_id": alb["id"],
                "album_name": alb.get("albumName", ""),
                "owner_email": (alb.get("owner") or {}).get("email", ""),
                "shared_with": ";".join(shared_labels),
                "target_already_shared": "True" if already else "False",
                "share_added": "False",
                "error": "",
            }
        )
    save_csv(new_rows)
    print(f"    saved {len(new_rows)} albums to {CSV_PATH.name}")
    return new_rows


def step2_share(
    client: ImmichClient,
    target_id: str,
    role: str,
    rows: list[dict],
    limit: int | None = None,
) -> None:
    print(f"[2/2] sharing albums with target user (role={role})…")
    if limit is not None:
        print(f"    will stop after {limit} newly-shared album(s)")

    pending = [
        r
        for r in rows
        if not to_bool(r["target_already_shared"]) and not to_bool(r["share_added"])
    ]
    print(f"    {len(pending)} album(s) need sharing; {len(rows) - len(pending)} already done")

    processed = 0
    for row in pending:
        if limit is not None and processed >= limit:
            save_csv(rows)
            print(f"    reached --limit {limit}; stopping.")
            return
        try:
            client.share_album(row["album_id"], target_id, role)
            row["share_added"] = "True"
            row["error"] = ""
        except requests.HTTPError as e:
            body = ""
            try:
                body = e.response.text
            except Exception:
                pass
            status = getattr(e.response, "status_code", None)
            if status == 400 and "User already added" in body:
                row["target_already_shared"] = "True"
                row["share_added"] = "True"
                row["error"] = ""
                print(f"    = already shared {row['album_name']!r}; marking as done")
            else:
                row["error"] = f"{status}: {body[:200]}"
                print(f"    ! failed {row['album_name']!r}: {row['error']}")
                save_csv(rows)
                continue
        processed += 1
        if processed % SAVE_EVERY == 0:
            save_csv(rows)
            print(f"    shared {processed}/{len(pending)}…")

    save_csv(rows)
    print(f"    done. shared {processed} album(s) this run.")


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="stop after sharing N albums in this run (step 2 only).",
    )
    return p.parse_args(argv)


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
            "error: set IMMICH_SERVER_URL and IMMICH_API_KEY in .env or env.",
            file=sys.stderr,
        )
        return 2

    role = os.environ.get("IMMICH_SHARE_ROLE", "viewer").strip().lower() or "viewer"
    if role not in ("viewer", "editor"):
        print("error: IMMICH_SHARE_ROLE must be 'viewer' or 'editor'.", file=sys.stderr)
        return 2

    client = ImmichClient(server, api_key)
    target_id = resolve_target_user()
    print(f"target user id: {target_id}; role={role}")

    rows = load_csv()
    rows = step1_collect(client, target_id, rows)
    step2_share(client, target_id, role, rows, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
