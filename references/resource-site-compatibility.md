# Content source compatibility findings

Verified notes for evaluating new content sources and diagnosing the default 365 source.

## Compatibility rule

`films-finder` can transfer a search result only when the source ultimately exposes a Quark share URL.

- Compatible: `https://pan.quark.cn/s/...`
- Not compatible with the current save workflow: HLS (`.m3u8`), direct CDN video URLs, and playback-only pages

Probe a source before writing a plugin:

```bash
# 1. Check whether the site is reachable without a JavaScript challenge.
curl -sL "https://site/" \
  -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
  --max-time 15 | head -3

# 2. Inspect one search result and its URL fields.
curl -sL "https://site/api/search?q=test" \
  -A "Mozilla/5.0" --max-time 15
```

If the first request returns a Cloudflare "Just a moment..." page, a normal `urllib` or `requests` plugin will not work without browser automation.

## 365 source

Base URL: `https://pan.365wp.top`

### Search

```text
GET /api/interface/search?keyword=<KEYWORD>&page=1&pageSize=20
```

The response shape is:

```json
{
  "code": 200,
  "data": {
    "list": [
      {
        "url": "encrypted value",
        "title": "result title",
        "disk_type": "quark"
      }
    ]
  }
}
```

### Resolve a result

```text
POST /api/transfer-share/transfer-share
Content-Type: application/json
```

```json
{
  "encrypted_url": "<url from the search result>"
}
```

A successful response includes `data.share_url`.

The endpoint has been observed to fail temporarily and recover without code changes. Before changing the plugin:

1. Call the transfer endpoint directly with a fresh search result.
2. If it returns a valid `share_url`, inspect plugin timeouts and headers or retry later.
3. If it also fails, treat the source as temporarily unavailable.

## Sources that do not fit

Streaming aggregators that return only `.m3u8` episode URLs cannot be used by `save --index N`; there is no Quark share item to transfer.

Sites behind a mandatory JavaScript challenge are also unsuitable for a lightweight HTTP plugin unless the project adopts browser automation.
