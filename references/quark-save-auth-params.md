# Quark save auth false-positive: required query params

Observed during a QQ films-finder session saving `007：无暇赴死` after a fresh QR login.

## Symptom

- `cinema.py login --confirm --timeout 60` succeeds and saves a cookie.
- Share token and folder/list APIs work with the same cookie.
- `share/sharepage/save` returns:

```json
{"status": 401, "code": 31001, "message": "require login [guest]"}
```

This can look like an expired cookie, but the cookie is valid.

## Cause

The raw Quark save endpoint requires the browser-style query params on the POST request:

```text
pr=ucpro&fr=pc&uc_param_str=
```

Without those params, Quark treats the request as guest even when the cookie works for other APIs.

## Fix

When posting to:

```text
https://drive.quark.cn/1/clouddrive/share/sharepage/save
```

include:

```python
params={"pr": "ucpro", "fr": "pc", "uc_param_str": ""}
```

The session patched `scripts/quark.py` in `_save_share_file_batch` to add those params.

## Verification pattern

After patching, run the exact user-selected save again:

```bash
.venv/bin/python scripts/cinema.py save --index N
```

If the command times out while waiting for task completion, verify the Quark target folder contents rather than assuming failure. A successful save may appear as a same-title folder, sometimes with `(1)` appended due to existing-name handling.
