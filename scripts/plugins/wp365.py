"""
365wp.top plugin - Free Quark/Baidu resource search engine.
No authentication required.
"""

import json
import sys
import time
import urllib.request
import urllib.parse
from typing import Optional

from . import ResourcePlugin, ResourceResult


class Plugin(ResourcePlugin):
    name = "wp365"
    display_name = "365聚合资源站"
    requires_auth = False
    url = "https://pan.365wp.top"

    def _config_int(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _request_json(self, req: urllib.request.Request, action: str) -> Optional[dict]:
        timeout = max(1, self._config_int("request_timeout", 8))
        retries = max(1, self._config_int("retries", 2))
        last_error = None

        for attempt in range(1, retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read())
            except Exception as e:
                last_error = e
                if attempt < retries:
                    time.sleep(0.5)

        print(f"[wp365] {action} error after {retries} attempt(s): {last_error}", file=sys.stderr)
        return None

    def search(self, query: str, page: int = 1) -> list[ResourceResult]:
        params = urllib.parse.urlencode({
            "keyword": query,
            "page": str(page),
            "pageSize": "20",
        })
        url = f"{self.url}/api/interface/search?{params}"

        req = urllib.request.Request(url, headers={
            "Referer": f"{self.url}/",
            "User-Agent": "Mozilla/5.0",
        })

        data = self._request_json(req, "Search")
        if not data:
            return []

        if data.get("code") != 200:
            return []

        results = []
        for item in data.get("data", {}).get("list", []):
            disk_type = item.get("disk_type", "")
            source_map = {"quark": "quark", "baidu": "baidu"}
            source = source_map.get(disk_type, disk_type)

            results.append(ResourceResult(
                title=item.get("title", ""),
                source=source,
                url=item.get("url", ""),  # encrypted URL
                site=self.name,
                extra={
                    "raw_source": item.get("source", ""),
                    "disk_type_label": item.get("disk_type_label", ""),
                },
            ))

        return results

    def extract_link(self, resource: ResourceResult) -> Optional[str]:
        """Decrypt the encrypted URL via 365wp's transfer API."""
        url = f"{self.url}/api/transfer-share/transfer-share"
        payload = json.dumps({"encrypted_url": resource.url}).encode()

        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "Referer": f"{self.url}/",
            "User-Agent": "Mozilla/5.0",
        })

        data = self._request_json(req, "Extract")
        if not data:
            return None

        if data.get("code") != 200:
            return None

        return data.get("data", {}).get("share_url")
