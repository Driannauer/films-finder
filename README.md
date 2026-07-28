# films-finder

[中文文档](README_CN.md)

`films-finder` is a [Hermes Agent](https://github.com/nousresearch/hermes-agent) skill and Python CLI for searching media sources, saving selected files to Quark Drive, and organizing a personal library for Infuse, Plex, or Jellyfin.

## What it does

- Searches every enabled source plugin and merges the results.
- Scores releases by resolution, source, HDR, audio, codec, subtitles, and drive type.
- Lets you review a numbered result table before saving a specific item.
- Supports terminal QR login and image-based QR login for Hermes chat.
- Remembers a pending save when Quark authentication expires and retries it after login.
- Filters promotional images while preserving the shared folder structure.
- Reuses existing folders and files where possible instead of failing on every name conflict.
- Optionally downloads newly saved files to local storage.
- Organizes movies and TV shows into media-server-friendly folders.

## Requirements

- Python 3.10 or newer
- A Quark Drive account and the Quark mobile app
- Hermes Agent if you want to use the skill conversationally
- An optional [OMDb API key](https://www.omdbapi.com/apikey.aspx) for genre classification

## Installation

```bash
git clone https://github.com/Driannauer/films-finder.git ~/.hermes/skills/films-finder
cd ~/.hermes/skills/films-finder

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.json config.json
.venv/bin/python scripts/setup.py
```

`config.json` contains local credentials and is ignored by Git.

## Quick start

Log in from an interactive terminal:

```bash
.venv/bin/python scripts/cinema.py login
```

Then search, review the ranked results, and save the item you want:

```bash
.venv/bin/python scripts/cinema.py search 'Interstellar'
.venv/bin/python scripts/cinema.py save --index 1
```

The latest search is cached under `~/.films-finder/last_search.json`. If the cache may be stale, search again while saving:

```bash
.venv/bin/python scripts/cinema.py save --index 1 'Interstellar'
```

You can also pass a Quark share link directly:

```bash
.venv/bin/python scripts/cinema.py save 'https://pan.quark.cn/s/your-share-id'
```

## Using it through Hermes

Install the repository under `~/.hermes/skills/films-finder`, then speak naturally:

- “Search for Interstellar.”
- “Save result 2.”
- “Automatically pick the best version of The Wandering Earth 2.”
- “Organize this Quark file as a TV episode.”

For chat-based login, the skill uses a two-step flow:

```bash
# Create a PNG that Hermes can send as a media attachment
.venv/bin/python scripts/cinema.py login --qr

# Run after the user has scanned it with the Quark app
.venv/bin/python scripts/cinema.py login --confirm --timeout 60
```

If a save detects an expired cookie, `films-finder` creates a fresh QR code and records that exact save as pending. `login --confirm` stores the new cookie and retries the pending save automatically.

## Command reference

| Command | Purpose |
|---|---|
| `cinema.py search <query>` | Search enabled plugins, rank results, and cache the latest list |
| `cinema.py save --index N [query]` | Save result `N` from the cache, or search again when `query` is supplied |
| `cinema.py save <share_url>` | Save a direct Quark share link |
| `cinema.py auto <query>` | Pick the highest-ranked Quark result, save it, and organize it as a movie |
| `cinema.py login` | Display a QR code in the terminal and save the returned cookie |
| `cinema.py login --qr` | Create a QR image for Hermes delivery |
| `cinema.py login --confirm` | Confirm the latest QR login and retry any pending save |
| `cinema.py download <fid> [...]` | Download one or more Quark file or folder IDs |
| `cinema.py organize <fid> <title>` | Organize an existing Quark item as a movie or TV episode |
| `cinema.py plugins` | List enabled source plugins |

Useful options:

```bash
# Preview the resolved result and share URL without saving
.venv/bin/python scripts/cinema.py save --index 1 --dry-run

# Override the target folder for one save
.venv/bin/python scripts/cinema.py save --index 1 --folder 'My Library'

# Download a file or folder recursively
.venv/bin/python scripts/cinema.py download <fid> --dir /srv/media

# Organize TV content
.venv/bin/python scripts/cinema.py organize <fid> 'Show Name' \
  --type tv --season 1 --episode 3
```

## Configuration

Run `scripts/setup.py` or edit `config.json`:

```json
{
  "quark": {
    "cookie": "",
    "login_timeout": 300
  },
  "plugins": {
    "wp365": {
      "enabled": true,
      "request_timeout": 8,
      "retries": 2
    },
    "example": {
      "enabled": false
    }
  },
  "save_folder": "夸克影视",
  "download_after_save": false,
  "local_download_folder": "/root/films",
  "plugin_search_timeout": 20,
  "omdb_api_key": ""
}
```

| Setting | Description |
|---|---|
| `quark.cookie` | Quark session cookie; QR login fills this automatically |
| `quark.login_timeout` | Lifetime of a generated login QR code, in seconds |
| `plugins.<name>.enabled` | Enables or disables a source plugin |
| `plugins.wp365.request_timeout` | Timeout for each 365 source request |
| `plugins.wp365.retries` | Maximum number of 365 source request attempts |
| `save_folder` | Destination folder in Quark Drive |
| `download_after_save` | Downloads saved items locally after a successful transfer |
| `local_download_folder` | Local destination for automatic or manual downloads |
| `plugin_search_timeout` | Process-level timeout for plugin search or link extraction |
| `omdb_api_key` | Optional key used to classify titles by genre |

The QR flow keeps local login state under `~/.hermes/cache/films-finder/quark-login/`. Runtime cookies, QR state, virtual environments, and `config.json` are excluded from version control.

## Library layout

Movies are grouped by genre and title:

```text
夸克影视/
└── 科幻/
    └── 流浪地球2 (2023)/
        └── The.Wandering.Earth.II.2023.2160p.WEB-DL.mkv
```

TV episodes use season folders:

```text
夸克影视/
└── 剧情/
    └── Show Name/
        └── Season 01/
            └── Show Name - S01E03.mkv
```

Scene-style filenames are preserved. Less structured filenames are normalized. Genre metadata comes from OMDb when configured, then from compatible plugin metadata when available, and otherwise falls back to `其他`.

## Quality scoring

The score is a sorting aid, not a guarantee of availability.

| Signal | Examples |
|---|---|
| Resolution | 2160p/4K ranks above 1080p, 720p, and 480p |
| Source | BluRay/REMUX ranks above WEB-DL, WEBRip, HDTV, and CAM |
| HDR | Dolby Vision, HDR10+, HDR10, HDR |
| Audio | Atmos, TrueHD, DTS-HD, DTS, EAC3/DDP, AAC |
| Codec | H.265/HEVC/x265 ranks above H.264/x264 |
| Extras | Included subtitles and Quark sources receive bonuses |

## Adding a source plugin

Copy the example and implement `search()` plus `extract_link()`:

```bash
cp scripts/plugins/example.py scripts/plugins/my_source.py
```

```python
from plugins import ResourcePlugin, ResourceResult


class Plugin(ResourcePlugin):
    name = "my_source"
    display_name = "My Source"
    requires_auth = False
    url = "https://example.com"

    def search(self, query: str, page: int = 1) -> list[ResourceResult]:
        ...

    def extract_link(self, resource: ResourceResult) -> str | None:
        ...
```

Enable it in `config.json`:

```json
{
  "plugins": {
    "my_source": {
      "enabled": true
    }
  }
}
```

A compatible plugin must ultimately return a Quark share URL. Streaming-only links such as HLS (`.m3u8`) cannot be transferred to Quark Drive.

## Troubleshooting

- **`auth_required`**: scan the newly generated QR code, then run `login --confirm`. A successful login does not imply the pending save succeeded; check the retry result.
- **`Invalid share URL`**: the source could not resolve its result into a working Quark link. Search again later or choose another result.
- **Name conflict / code `23008`**: the target already contains the item or an active save task is using the same name.
- **Plugin timeout**: increase `plugin_search_timeout`, or adjust that plugin's request timeout and retries.

Only save content that you are authorized to access and store.
