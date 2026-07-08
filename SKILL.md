---
name: films-finder
description: Personal media library management — discover content, save to Quark cloud drive, auto-organize for Infuse/Plex. Plugin system for content sources. Use when user wants to find/watch movies, save to cloud drive, or manage media library.
---

# films-finder

Media discovery → Cloud save → Library organization.

## Quick Start

```bash
python3 scripts/cinema.py search 电影名     # search only
python3 scripts/cinema.py save --index 1    # save from latest search result list
python3 scripts/cinema.py login --qr         # create Quark QR image for chat delivery
python3 scripts/cinema.py login --confirm    # confirm scanned QR and save cookie
python3 scripts/cinema.py auto 电影名       # explicit auto-pick + save + organize
python3 scripts/cinema.py plugins           # list plugins
```

## Hermes Terminal Calls

When using the Hermes `terminal` tool for this skill, emit a real tool call. Do not print `[调用 terminal] {...}` or `[Tool call: terminal] {...}` as chat text. The user has explicitly complained about pseudo tool-call text; for QQ films-finder requests, a chat message that contains the tool-call JSON instead of a real tool call is a failure.

Use `workdir` for the per-command working directory. Do not use `cwd`; do not prepend `cd ... &&` unless `workdir` is unavailable. After a tool result, report only the useful outcome/table/error; do not narrate intended future calls when the next real tool call can be made now.

Search tool arguments:

```json
{
  "command": ".venv/bin/python scripts/cinema.py search 电影名",
  "workdir": "/root/.hermes/skills/films-finder",
  "timeout": 60,
  "background": false,
  "pty": false
}
```

Save the user's selected result number from the latest search:

```json
{
  "command": ".venv/bin/python scripts/cinema.py save --index 1",
  "workdir": "/root/.hermes/skills/films-finder",
  "timeout": 60,
  "background": false,
  "pty": false
}
```

`search` prints a Markdown table with `序号`, `内容`, `大小`, and `得分`, and caches the full latest result list. `save --index N` reads that cached list. Use it immediately after the matching search; if the cache may be stale, run `search 电影名` again first or pass the title after the index.

If Quark login is missing or expired, `save` returns `auth_required` and prints a `MEDIA:/root/.hermes/cache/films-finder/quark-login/...png` QR image path. Include that exact bare `MEDIA:` line in the final chat reply so the gateway sends the QR image, and ask the user to scan it with the Quark App and reply "已扫码".

**Timing note**: The QR has a 300-second lifetime from generation. If the user takes 30+ seconds to open the Quark App and scan, the remaining time plus the 60-second confirm loop may cause the login to timeout. If `confirm` times out, generate a fresh QR with `login --qr` immediately and ask the user to scan and reply again.

When the user replies that they scanned the Quark QR code (for example "已扫码", "扫码了", "已登录"), run `login --confirm` immediately:

```json
{
  "command": ".venv/bin/python scripts/cinema.py login --confirm --timeout 60",
  "workdir": "/root/.hermes/skills/films-finder",
  "timeout": 90,
  "background": false,
  "pty": false
}
```

`login --confirm` saves the new cookie and automatically retries any pending save from the expired-cookie turn. Report the retry result to the user.

Pitfall: if `login --confirm` succeeds but the retry still reports `Quark login expired or invalid`, verify whether the save endpoint is missing required Quark query params before asking the user to rescan repeatedly. The raw `share/sharepage/save` POST needs `params={"pr":"ucpro","fr":"pc","uc_param_str":""}`; see `references/quark-save-auth-params.md`. After patching or retrying, confirm success by listing the target folder if the save command times out while waiting for completion.

## Config

`config.json` (not committed, create from `config.example.json`):
- `quark.cookie` — Quark session cookie (login to pan.quark.cn, copy cookie from browser DevTools)
- `plugins` — enable/disable content source plugins
- `save_folder` — Quark folder name (default: "影视资源")

## Adding Content Sources

1. Copy `scripts/plugins/example.py` to `scripts/plugins/your_site.py`
2. Implement `search()` and `extract_link()`
3. Add `"your_site": {"enabled": true}` to config.json

## Library Management

`cinema.py organize <fid> <title> --type movie|tv`

Organizes files into Infuse/Plex-compatible structure:
- Movies: `影视资源/Movie Name (Year)/Movie Name (Year).ext`
- TV: `影视资源/Show Name/Season XX/Show Name - SXXEXX.ext`

## Workflow

1. User says "I want to watch X"
2. Run search only: `.venv/bin/python scripts/cinema.py search X` through the real terminal tool with `workdir=/root/.hermes/skills/films-finder` and `timeout=60`
3. Search output is a numbered table (`序号`, `内容`, `大小`, `得分`) and caches the full latest result list
4. If the user picks a result number, run `.venv/bin/python scripts/cinema.py save --index N` through the real terminal tool; do not pass `N` as a share URL
5. Do not run `save` or `auto` in the same turn as a plain "I want to watch X" request unless the user explicitly asked for auto-save/best-pick
6. If `save --index N` fails, report that result's error and ask the user to choose another index; do not try other indexes autonomously. `--force` is not supported; never retry with `save --index N --force`.
7. If save fails with Quark auth required, send the QR `MEDIA:` line and wait for the user's scan confirmation; do not call `login --confirm` before the user says they scanned it. If the user asks for “失效自动给我发二维码重登”, this is permission to immediately send the QR whenever `auth_required` appears, but still wait for “已扫码” before confirming.
8. When the user replies “已扫码”, run the real `login --confirm --timeout 60` tool call immediately with `timeout=90`. Do not print pseudo tool-call text. If confirmation succeeds and there is a pending save, the command may retry it automatically; report that retry result. If it only saves the cookie but no retry happens, retry the exact user-selected index/share once.
9. If a selected save fails with Quark auth, name conflict, or any other error, do **not** try other result indexes unless the user explicitly chooses them. Preserve the user’s chosen index through login/confirm/retry. Suggest alternatives in text only.
10. A successful Quark QR confirmation only proves a cookie was saved; the subsequent save endpoint can still return `auth_required`. Treat the actual `save --index N` result as authoritative. If it returns a new QR, send that latest `MEDIA:` line and continue the login loop rather than claiming the movie was saved.
11. Use `cinema.py auto` only when the user explicitly requests automatic best-pick + save + organize, or `cinema.py organize` on a saved fid when manual organization is needed
12. Infuse/Plex auto-detects and fetches metadata

## Query Notes

- Use shell single quotes in terminal commands so JSON command strings do not need nested double-quote escaping.
- Do not put unescaped double quotes inside the terminal tool's JSON `command` value. For Chinese titles without spaces, omit quotes: `python3 scripts/cinema.py search 窃听风云`. For titles with spaces, use shell single quotes: `python3 scripts/cinema.py search '007 James Bond'`.
- For "007" / "James Bond" requests, prefer `007系列` or `詹姆斯邦德`. The CLI also falls back from `007 James Bond` to those Chinese keywords automatically.

## Pitfalls

### QR login timing — confirm may timeout if QR was generated too early

When the user scans a QR image and replies "已扫码", time has already elapsed between QR generation and the `login --confirm` call. The `--timeout 60` counts from when the command starts, but the QR only has a limited remaining lifetime (300 seconds from generation). If the user takes 30+ seconds to open the Quark App and scan, the QR may be nearly expired when `--confirm` starts polling, and the 60-second confirm window may not be enough.

**Mitigation**: If `login --confirm` returns `RuntimeError: QR login timed out or failed` after a successful scan, generate a fresh QR immediately with `cinema.py login --qr` and ask the user to scan again, then call `login --confirm` with a larger timeout (e.g., `--timeout 120`). Alternatively, instruct the user to reply "已扫码" immediately after scanning to minimize delay.

### 同名冲突 (code 23008) — popular movies may have all 4K results pointing to the same files

When saving a popular movie like 007 or 哪吒, it's common for the top-ranked 4K REMUX results (indices 1, 2, 6, etc.) to all fail with `code: 23008, message: 'file is doloading[同名冲突]'`. This means the file already exists in your Quark drive — the different share URLs all point to the same file names.

**Mitigation**: 
- Report the selected result's conflict and ask the user what to do next; do not keep trying indices 1, 2, 6 in sequence unless the user explicitly picks each one.
- Suggest the user try a lower-ranked result (e.g., a 1080p version or a source with different file naming) that hasn't been saved yet.
- If ALL user-selected results have 同名冲突, the movie may already be in the Quark library. Ask the user whether they'd like to reorganize an existing save, or pick a different quality source.

### Cookie stored in two places — ensure both are in sync

The `login --confirm` command writes the cookie to both:
- `~/.films-finder/quark_cookies.json` (via `quark.py`'s `_save_cookie_cache`)
- `config.json` (via `cinema.py`'s `save_quark_cookie`)

Both files must contain the full, untruncated cookie string for saves to work. If `config.json` ends up with a shorter or malformed cookie while `~/.films-finder/quark_cookies.json` has the full one, the `save` command may still use the broken cookie from config.json. Verify the cookie lengths match after login.
