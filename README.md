# immich_cli

Two small Python utilities for bulk-managing an [Immich](https://immich.app) library through its REST API:

- **`immich_albums.py`** — scans every asset in Immich, derives the right album from the file's original folder path, creates the album if it doesn't exist, and adds the asset to it.
- **`immich_share_albums.py`** — shares every album in the library with a given user.

Both scripts are **resumable**: progress is persisted to a CSV after every meaningful step, so you can interrupt and restart at any time without redoing work.

## Requirements

- Python 3.10+
- Network access to your Immich server
- An Immich **API key** (Account Settings → API Keys)

## Setup

```bash
git clone https://github.com/andreamarelli/immich_cli.git
cd immich_cli

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with your real values
```

`.env` variables:

| Variable | Used by | Notes |
|---|---|---|
| `IMMICH_SERVER_URL` | both | e.g. `https://immich.example.com` |
| `IMMICH_API_KEY` | both | API key from the Immich web UI |
| `IMMICH_SHARE_WITH_USER_ID` | share script | UUID of the user to share albums with |
| `IMMICH_SHARE_ROLE` | share script | `viewer` (default) or `editor` |

## `immich_albums.py` — file paths into albums

### Folder convention

The script assumes an archive organised in a two-level hierarchy: `YEAR / GROUP / files…`. Examples:

```
/archive/2024/11 - Roma/2024-11-30_16.42.36.jpg
/archive/2024/Varie/2024-12-24_22.38.24.jpg
/archive/2020/Varie/2020-02-16_10.59.32.jpg
```

### Album naming rule

| Folder pattern | Album name |
|---|---|
| `YYYY/MM - Name/` | `Name` (e.g. `Roma`) |
| `YYYY/Name/` (no `MM - ` prefix) | `Name YYYY` (e.g. `Varie 2024`) |

Same-named folders from different years produce two distinct albums (`Varie 2020` and `Varie 2024`).

### Path overrides

A few folders don't fit the year-based pattern and are mapped explicitly. Defined in `PATH_OVERRIDES` (see `immich_albums.py`):

| Path segments | Album |
|---|---|
| `Case / Badia` | `Badia` |
| `Case / Ciliegio` | `Ciliegio` |
| `Case / Remac` | `REMAC` |
| `Farmacia` | `Farmacia` |

Overrides are matched by **consecutive path segments**, so they work regardless of where the archive is mounted and even when there's deeper nesting below.

### Usage

```bash
python3 immich_albums.py               # full run
python3 immich_albums.py --limit 50    # stop after 50 newly-added photos
```

### CSV: `immich_albums.csv`

Columns: `filename, path, album_name, album_year, album_id, album_is_generated, photo_is_added_to_album, asset_id`.

Delete the file to force a full re-scan of the library on the next run.

## `immich_share_albums.py` — share every album

### What it does

1. Lists every album and records its current share recipients.
2. For every album where the target user isn't already a recipient, calls `PUT /api/albums/{id}/users` to add them.
3. Treats Immich's `400 "User already added"` response as success.

### Usage

```bash
python3 immich_share_albums.py              # share everything
python3 immich_share_albums.py --limit 5    # stop after 5 newly-shared albums
```

### CSV: `immich_album_shares.csv`

Columns: `album_id, album_name, owner_email, shared_with, target_already_shared, share_added, error`.

Delete the file to re-scan album state from Immich on the next run.

## Resumability and safety

- The CSV is rewritten atomically (via a `.tmp` then `rename`) so an interrupted run never leaves a half-written file.
- Both scripts flush progress every 25–50 records and after each album creation / share.
- `.env` and `*.csv` are in `.gitignore` so credentials and local state don't get committed.

## Project layout

```
immich_cli/
├── immich_albums.py          # photos → albums
├── immich_share_albums.py    # share albums with a user
├── requirements.txt
├── .env.example
├── immich_prompt.md          # original spec for the album script
└── README.md
```
