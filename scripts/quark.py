"""
Quark cloud drive client.
Handles login, cookie management, and file saving.

Uses the quarkpan library if available, falls back to raw HTTP.
"""

import json
import os
import re
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import Optional

import httpx

QUARK_API = "https://drive-pc.quark.cn/1/clouddrive"
QUARK_SHARE_API = "https://drive.quark.cn/1/clouddrive"

COOKIE_CACHE = os.path.expanduser("~/.films-finder/quark_cookies.json")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
QUARKPAN_CONFIG_DIR = os.path.join(PROJECT_DIR, ".quarkpan")
HERMES_HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
QUARK_LOGIN_DIR = HERMES_HOME / "cache" / "films-finder" / "quark-login"
QUARK_LOGIN_STATE = QUARK_LOGIN_DIR / "state.json"
DEFAULT_QR_LOGIN_TIMEOUT = 300
SKIP_DOWNLOAD_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
}
SKIP_DOWNLOAD_KEYWORDS = [
    "广告", "推广", "更多资源", "更多汁源", "进群", "进裙", "加群", "加裙",
    "扫码", "二维码", "公众号", "微信", "qq群", "qq裙", "获取资源",
]
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v",
    ".ts", ".m2ts", ".mts", ".iso", ".rmvb", ".mpg", ".mpeg",
}
AUTH_ERROR_RE = re.compile(
    r"(not\s*logged\s*in|login|cookie|unauthori[sz]ed|forbidden|expired|"
    r"未登录|登录|登陆|过期|失效|无效|鉴权|认证|授权)",
    re.IGNORECASE,
)
NAME_CONFLICT_RE = re.compile(
    r"(同名冲突|doloading|downloading|duplicate|already\s+exists|file\s+exists|name\s+conflict)",
    re.IGNORECASE,
)


class QuarkAuthRequired(RuntimeError):
    """Raised when Quark requires a fresh login."""


class QuarkNameConflict(RuntimeError):
    """Raised when Quark refuses a save because a same-name item exists."""

    def __init__(self, message: str, payload: Optional[dict] = None):
        super().__init__(message)
        self.payload = payload or {}


class QuarkClient:
    """Quark cloud drive client with cookie-based authentication."""

    def __init__(self, cookie: str = ""):
        self._cookie = cookie
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=30,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://pan.quark.cn/",
            },
        )

    @property
    def cookie(self) -> str:
        if self._cookie:
            return self._cookie
        # Try loading cached cookie
        self._load_cookie_cache()
        return self._cookie

    def _load_cookie_cache(self):
        if os.path.exists(COOKIE_CACHE):
            try:
                with open(COOKIE_CACHE) as f:
                    data = json.load(f)
                if data.get("expires_at", 0) > time.time():
                    self._cookie = data.get("cookie", "")
            except Exception:
                pass

    def _save_cookie_cache(self):
        os.makedirs(os.path.dirname(COOKIE_CACHE), exist_ok=True)
        with open(COOKIE_CACHE, "w") as f:
            json.dump({
                "cookie": self._cookie,
                "expires_at": time.time() + 86400 * 7,  # 7 days
            }, f)
        self._save_quarkpan_cookie_file()

    def _save_quarkpan_cookie_file(self):
        """Mirror cookies into quarkpan's own config file for library fallbacks."""
        if not self._cookie:
            return
        cookies = []
        for pair in self._cookie.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": ".quark.cn",
                "path": "/",
            })
        if not cookies:
            return

        config_dir = Path(QUARKPAN_CONFIG_DIR)
        config_dir.mkdir(parents=True, exist_ok=True)
        with open(config_dir / "cookies.json", "w", encoding="utf-8") as f:
            json.dump({
                "cookies": cookies,
                "timestamp": int(time.time()),
                "expires_at": int(time.time() + 86400 * 7),
            }, f, ensure_ascii=False, indent=2)

    def login(self, force: bool = False, timeout: int = 300) -> str:
        """Log in with Quark app QR scan and cache the returned cookie."""
        if self.cookie and not force:
            return self.cookie

        os.environ.setdefault("QUARK_CONFIG_DIR", QUARKPAN_CONFIG_DIR)

        try:
            from quark_client.auth.api_login import APILogin
            from quark_client.utils.qr_code import display_qr_from_url
        except ImportError as e:
            raise RuntimeError("QR login requires the quarkpan package. Run: pip install quarkpan") from e

        login_manager = APILogin(timeout=timeout)
        qr_token, qr_url = login_manager.get_qr_code()

        print("\n请使用夸克 App 扫描下面二维码登录。")
        print("如果二维码在当前终端显示不完整，可以复制下面的临时登录链接到浏览器打开：")
        print(qr_url)
        print()

        display_qr_from_url(qr_url)

        if not login_manager.wait_for_login(qr_token):
            raise RuntimeError("QR login timed out or failed")

        cookies = []
        for cookie in login_manager.client.cookies.jar:
            if cookie.domain and "quark.cn" in cookie.domain:
                cookies.append(f"{cookie.name}={cookie.value}")

        cookie_string = "; ".join(cookies)
        if not cookie_string:
            raise RuntimeError("QR login succeeded but no Quark cookies were returned")

        self._cookie = cookie_string
        self._save_cookie_cache()
        return cookie_string

    def start_login_qr(self, timeout: int = DEFAULT_QR_LOGIN_TIMEOUT, pending: Optional[dict] = None) -> dict:
        """Create a QR login image and persist login state for later confirmation."""
        os.environ.setdefault("QUARK_CONFIG_DIR", QUARKPAN_CONFIG_DIR)

        try:
            from quark_client.auth.api_login import APILogin
        except ImportError as e:
            raise RuntimeError("QR login requires the quarkpan package. Run: pip install quarkpan") from e

        login_manager = APILogin(timeout=timeout)
        qr_token, qr_url = login_manager.get_qr_code()
        created_at = int(time.time())
        expires_at = created_at + timeout

        QUARK_LOGIN_DIR.mkdir(parents=True, exist_ok=True)
        qr_path = QUARK_LOGIN_DIR / f"quark-login-{created_at}.png"
        write_qr_png(qr_url, qr_path)

        state = {
            "token": qr_token,
            "qr_url": qr_url,
            "qr_path": str(qr_path),
            "created_at": created_at,
            "expires_at": expires_at,
            "timeout": timeout,
            "pending": pending or {},
        }
        self._write_login_state(state)
        return {
            "status": "qr_ready",
            "qr_path": str(qr_path),
            "media": f"MEDIA:{qr_path}",
            "expires_at": expires_at,
            "expires_in_seconds": timeout,
            "confirm_command": ".venv/bin/python scripts/cinema.py login --confirm --timeout 60",
            "pending": pending or {},
        }

    def confirm_login(self, token: str = "", timeout: int = 60) -> str:
        """Wait for the latest QR login to be scanned and cache the new cookie."""
        state = self._read_login_state()
        qr_token = token or state.get("token", "")
        if not qr_token:
            raise RuntimeError("No pending Quark QR login. Run: cinema.py login --qr")
        if state.get("expires_at", 0) and time.time() > state["expires_at"]:
            raise RuntimeError("Quark QR login expired. Run: cinema.py login --qr")

        os.environ.setdefault("QUARK_CONFIG_DIR", QUARKPAN_CONFIG_DIR)
        try:
            from quark_client.auth.api_login import APILogin
        except ImportError as e:
            raise RuntimeError("QR login requires the quarkpan package. Run: pip install quarkpan") from e

        login_manager = APILogin(timeout=timeout)
        if not login_manager.wait_for_login(qr_token):
            raise RuntimeError("QR login timed out or failed")

        cookies = []
        for cookie in login_manager.client.cookies.jar:
            if cookie.domain and "quark.cn" in cookie.domain:
                cookies.append(f"{cookie.name}={cookie.value}")

        cookie_string = "; ".join(cookies)
        if not cookie_string:
            raise RuntimeError("QR login succeeded but no Quark cookies were returned")

        self._cookie = cookie_string
        self._save_cookie_cache()
        state["confirmed_at"] = int(time.time())
        state["cookie_length"] = len(cookie_string)
        self._write_login_state(state)
        return cookie_string

    def get_pending_login_action(self) -> dict:
        state = self._read_login_state()
        pending = state.get("pending", {})
        return pending if isinstance(pending, dict) else {}

    def clear_pending_login_action(self) -> None:
        state = self._read_login_state()
        if not state:
            return
        state["pending"] = {}
        self._write_login_state(state)

    def _read_login_state(self) -> dict:
        try:
            with open(QUARK_LOGIN_STATE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_login_state(self, state: dict) -> None:
        QUARK_LOGIN_DIR.mkdir(parents=True, exist_ok=True)
        with open(QUARK_LOGIN_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def save_share(self, share_url: str, folder_name: str = "", title: str = "") -> dict:
        """Save a quark share link to drive."""
        if not self.cookie:
            return auth_required_result("Not logged in")

        try:
            target_fid = self._get_or_create_folder_id(folder_name) if folder_name else "0"
            return self._save_filtered(share_url, target_fid, title=title)
        except QuarkAuthRequired as e:
            return auth_required_result(str(e))
        except QuarkNameConflict as e:
            return name_conflict_result(str(e), payload=e.payload)
        except Exception as e:
            if text_is_auth_error(str(e)):
                return auth_required_result("Quark login expired or invalid")
            if text_is_name_conflict(str(e)):
                return name_conflict_result(str(e))
            return {"error": f"Filtered save failed: {e}"}

    def _save_with_quarkpan(self, share_url: str, target_fid: str) -> dict:
        """Save a share link via quarkpan and wait for the save task to finish."""
        from quark_client import create_client

        client = create_client(cookies=self.cookie, auto_login=False)
        return client.save_shared_files(
            share_url,
            target_folder_id=target_fid,
            save_all=True,
            wait_for_completion=True,
            timeout=120,
        )

    def _save_filtered(self, share_url: str, target_fid: str, title: str = "") -> dict:
        """Save share contents through quarkpan APIs while skipping promotional image files."""
        import re

        from quark_client import create_client

        drive = create_client(cookies=self.cookie, auto_login=False)
        try:
            pwd_id, password = drive.parse_share_url(share_url)
        except Exception:
            pwd_match = re.search(r"pan\.quark\.cn/s/([a-zA-Z0-9]+)", share_url)
            if not pwd_match:
                return {"error": "Invalid share URL"}
            pwd_id, password = pwd_match.group(1), None

        stoken = self._get_share_token(drive, pwd_id, password)
        saved_fids = []
        filtered_files = []
        existing_files = []
        root_files = self._list_share_files(drive, pwd_id, stoken, "0")
        root_folder = None
        target_root_fid = target_fid
        create_root_dirs = True

        if self._has_direct_save_files(root_files):
            root_folder_name = self._infer_root_folder_name(title, root_files, fallback=pwd_id)
            root_folder = self._get_or_create_drive_folder(
                drive,
                root_folder_name,
                target_fid,
                existing_files=existing_files,
            )
            target_root_fid = root_folder["fid"]
            saved_fids.append(root_folder["fid"])
            create_root_dirs = False

        self._save_share_dir_filtered(
            drive=drive,
            pwd_id=pwd_id,
            stoken=stoken,
            share_dir_fid="0",
            target_dir_fid=target_root_fid,
            saved_fids=saved_fids,
            filtered_files=filtered_files,
            existing_files=existing_files,
            create_root_dirs=create_root_dirs,
            initial_files=root_files,
        )

        return {
            "status": 200,
            "message": "ok",
            "saved_as_folder": bool(root_folder),
            "root_folder": root_folder,
            "filtered_files": filtered_files,
            "existing_files": existing_files,
            "task_result": {
                "status": 200,
                "data": {
                    "save_as": {
                        "save_as_top_fids": saved_fids,
                    }
                },
            },
        }

    def _save_share_dir_filtered(
        self,
        drive,
        pwd_id: str,
        stoken: str,
        share_dir_fid: str,
        target_dir_fid: str,
        saved_fids: list[str],
        filtered_files: list[str],
        existing_files: list[dict],
        create_root_dirs: bool,
        initial_files: Optional[list[dict]] = None,
    ):
        files = initial_files if initial_files is not None else self._list_share_files(drive, pwd_id, stoken, share_dir_fid)
        if not files:
            return

        batch = []
        for item in files:
            name = item.get("file_name", "")
            if self._should_skip_download(name):
                filtered_files.append(name)
                print(f"🚫 Skipping ad file during Quark save: {name}", file=sys.stderr)
                continue
            if item.get("dir"):
                folder = self._get_or_create_drive_folder(
                    drive,
                    name,
                    target_dir_fid,
                    existing_files=existing_files,
                )
                child_target_fid = folder["fid"]
                if create_root_dirs:
                    saved_fids.append(child_target_fid)
                self._save_share_dir_filtered(
                    drive=drive,
                    pwd_id=pwd_id,
                    stoken=stoken,
                    share_dir_fid=item["fid"],
                    target_dir_fid=child_target_fid,
                    saved_fids=saved_fids,
                    filtered_files=filtered_files,
                    existing_files=existing_files,
                    create_root_dirs=False,
                )
            else:
                batch.append(item)

        if batch:
            batch = self._skip_existing_drive_files(
                drive=drive,
                target_dir_fid=target_dir_fid,
                files=batch,
                saved_fids=saved_fids,
                existing_files=existing_files,
            )
        if batch:
            saved = self._save_share_file_batch(
                drive=drive,
                pwd_id=pwd_id,
                stoken=stoken,
                source_dir_fid=share_dir_fid,
                target_dir_fid=target_dir_fid,
                files=batch,
            )
            if create_root_dirs:
                saved_fids.extend(saved)

    def _get_share_token(self, drive, pwd_id: str, password: Optional[str] = None) -> str:
        try:
            return drive.shares.get_share_token(pwd_id, password)
        except Exception as e:
            payload = exception_payload(e)
            if text_is_auth_error(str(e)) or response_payload_is_auth_error(payload):
                raise QuarkAuthRequired("Quark login expired or invalid") from e
            raise RuntimeError(f"Failed to get share token: {e}") from e

    def _list_share_files(self, drive, pwd_id: str, stoken: str, pdir_fid: str) -> list[dict]:
        all_files = []
        page = 1
        page_size = 100
        while True:
            try:
                result = drive.shares.client.get(
                    "share/sharepage/detail",
                    params={
                        "pwd_id": pwd_id,
                        "stoken": stoken,
                        "pdir_fid": pdir_fid,
                        "force": "0",
                        "_page": page,
                        "_size": page_size,
                        "_fetch_banner": "1",
                        "_fetch_share": "1",
                        "_fetch_total": "1",
                        "_sort": "file_type:asc,file_name:asc",
                    },
                    base_url=QUARK_SHARE_API,
                )
            except Exception as e:
                payload = exception_payload(e)
                if text_is_auth_error(str(e)) or response_payload_is_auth_error(payload):
                    raise QuarkAuthRequired("Quark login expired or invalid") from e
                raise RuntimeError(f"Failed to list share files: {e}") from e
            files = result.get("data", {}).get("list", [])
            all_files.extend(files)
            if len(files) < page_size:
                break
            page += 1
        return all_files

    def _create_drive_folder(self, drive, name: str, parent_fid: str) -> str:
        folder_name = self._safe_path_component(name)
        result = drive.create_folder(folder_name, parent_fid)
        if response_payload_is_name_conflict(result):
            existing = self._find_drive_child(drive, parent_fid, folder_name, is_dir=True)
            if existing:
                return existing["fid"]
            raise QuarkNameConflict(f"Folder already exists: {folder_name}", result)
        data = result.get("data", {})
        fid = data.get("fid") or data.get("file", {}).get("fid")
        if not fid:
            raise RuntimeError(f"Failed to create folder '{folder_name}': {result}")
        return fid

    def _get_or_create_drive_folder(
        self,
        drive,
        name: str,
        parent_fid: str,
        existing_files: Optional[list[dict]] = None,
    ) -> dict:
        folder_name = self._safe_path_component(name)
        existing = self._find_drive_child(drive, parent_fid, folder_name, is_dir=True)
        if existing:
            folder = {
                "name": folder_name,
                "fid": existing["fid"],
                "dir": True,
                "existing": True,
            }
            if existing_files is not None:
                existing_files.append(folder)
            return folder

        fid = self._create_drive_folder(drive, folder_name, parent_fid)
        return {
            "name": folder_name,
            "fid": fid,
            "dir": True,
            "existing": False,
        }

    @classmethod
    def _has_direct_save_files(cls, files: list[dict]) -> bool:
        return any(
            not item.get("dir") and not cls._should_skip_download(item.get("file_name", ""))
            for item in files
        )

    def _infer_root_folder_name(self, title: str, files: list[dict], fallback: str = "resource") -> str:
        direct_files = [
            item for item in files
            if not item.get("dir") and not self._should_skip_download(item.get("file_name", ""))
        ]
        media_files = [
            item for item in direct_files
            if os.path.splitext(item.get("file_name", ""))[1].lower() in VIDEO_EXTENSIONS
        ]
        if media_files:
            largest = max(media_files, key=self._file_size)
            stem = os.path.splitext(largest.get("file_name", ""))[0].strip()
            if stem:
                return stem

        cleaned_title = self._clean_title_for_folder(title)
        if cleaned_title:
            return cleaned_title

        if direct_files:
            stem = os.path.splitext(direct_files[0].get("file_name", ""))[0].strip()
            if stem:
                return stem
        return fallback

    @staticmethod
    def _clean_title_for_folder(title: str) -> str:
        cleaned = re.sub(
            r"^\s*(?:[【\[]\s*)?(?:名称|标题|资源标题)(?:\s*[】\]])?\s*[:：]\s*",
            "",
            title or "",
        ).strip()
        cleaned = re.sub(r"\s*[【\[]\s*描述\s*[】\]]\s*[:：].*$", "", cleaned).strip()
        cleaned = re.sub(r"https?://\S+", "", cleaned).strip()
        return " ".join(cleaned.split())

    def _skip_existing_drive_files(
        self,
        drive,
        target_dir_fid: str,
        files: list[dict],
        saved_fids: list[str],
        existing_files: list[dict],
    ) -> list[dict]:
        target_files = self._list_drive_children(drive, target_dir_fid)
        existing_by_name = {
            self._safe_path_component(item.get("file_name", "")): item
            for item in target_files
            if not item.get("dir")
        }

        pending = []
        for item in files:
            name = self._safe_path_component(item.get("file_name", ""))
            existing = existing_by_name.get(name)
            if existing:
                fid = existing.get("fid")
                if fid:
                    saved_fids.append(fid)
                existing_files.append({
                    "name": name,
                    "fid": fid,
                    "dir": False,
                })
                continue
            pending.append(item)
        return pending

    def _find_drive_child(self, drive, parent_fid: str, name: str, is_dir: Optional[bool] = None) -> Optional[dict]:
        safe_name = self._safe_path_component(name)
        for item in self._list_drive_children(drive, parent_fid):
            item_name = self._safe_path_component(item.get("file_name", ""))
            if item_name != safe_name:
                continue
            if is_dir is not None and bool(item.get("dir")) != is_dir:
                continue
            return item
        return None

    @staticmethod
    def _list_drive_children(drive, parent_fid: str) -> list[dict]:
        all_files = []
        page = 1
        page_size = 100
        while True:
            paged = True
            try:
                result = drive.list_files(parent_fid, page=page, size=page_size)
            except TypeError:
                result = drive.list_files(parent_fid)
                paged = False
            files = result.get("data", {}).get("list", []) if isinstance(result, dict) else []
            all_files.extend(files)
            if not paged or len(files) < page_size:
                break
            page += 1
        return all_files

    def _save_share_file_batch(
        self,
        drive,
        pwd_id: str,
        stoken: str,
        source_dir_fid: str,
        target_dir_fid: str,
        files: list[dict],
    ) -> list[str]:
        try:
            result = drive.shares.client.post(
                "share/sharepage/save",
                json_data={
                    "fid_list": [f["fid"] for f in files],
                    "fid_token_list": [f.get("share_fid_token", "") for f in files],
                    "to_pdir_fid": target_dir_fid,
                    "pwd_id": pwd_id,
                    "stoken": stoken,
                    "pdir_fid": source_dir_fid,
                    "pdir_save_all": False,
                    "exclude_fids": [],
                    "scene": "link",
                },
                base_url=QUARK_SHARE_API,
            )
        except Exception as e:
            payload = exception_payload(e)
            if text_is_auth_error(str(e)) or response_payload_is_auth_error(payload):
                raise QuarkAuthRequired("Quark login expired or invalid") from e
            if text_is_name_conflict(str(e)) or response_payload_is_name_conflict(payload):
                raise QuarkNameConflict("Quark target already has a same-name file or active save task", payload) from e
            raise RuntimeError(f"Save failed: {e}") from e

        if response_payload_is_auth_error(result):
            raise QuarkAuthRequired("Quark login expired or invalid")
        if response_payload_is_name_conflict(result):
            raise QuarkNameConflict("Quark target already has a same-name file or active save task", result)
        if result.get("status") != 200 and result.get("code") not in (0, None):
            raise RuntimeError(f"Save failed: {result}")

        task_id = result.get("data", {}).get("task_id")
        if not task_id:
            return []
        task_result = self._wait_for_task(drive, task_id)
        return self._extract_saved_fids(task_result)

    def _wait_for_task(self, drive, task_id: str, timeout: int = 120) -> dict:
        start = time.time()
        retry_index = 0
        while time.time() - start < timeout:
            try:
                result = drive.shares.client.get(
                    "task",
                    params={"task_id": task_id, "retry_index": retry_index},
                    base_url=QUARK_API,
                )
            except Exception as e:
                payload = exception_payload(e)
                if text_is_auth_error(str(e)) or response_payload_is_auth_error(payload):
                    raise QuarkAuthRequired("Quark login expired or invalid") from e
                if text_is_name_conflict(str(e)) or response_payload_is_name_conflict(payload):
                    raise QuarkNameConflict(
                        "Quark target already has a same-name file or active save task",
                        payload,
                    ) from e
                raise RuntimeError(f"Save task check failed: {e}") from e
            if response_payload_is_auth_error(result):
                raise QuarkAuthRequired("Quark login expired or invalid")
            data = result.get("data", {})
            status = data.get("status")
            if status == 2:
                return result
            if status == 3:
                message = data.get("message", "unknown")
                if response_payload_is_name_conflict(result) or text_is_name_conflict(message):
                    raise QuarkNameConflict(
                        f"Quark target already has a same-name file or active save task: {message}",
                        result,
                    )
                raise RuntimeError(f"Save task failed: {message}")
            retry_index += 1
            time.sleep(1)
        raise RuntimeError(f"Save task timed out: {task_id}")

    @staticmethod
    def _extract_saved_fids(result: dict) -> list[str]:
        save_as = result.get("data", {}).get("save_as", {})
        fids = save_as.get("save_as_top_fids") or []
        if isinstance(fids, str):
            return [fids]
        return [fid for fid in fids if fid]

    def _get_or_create_folder_id(self, folder_name: str) -> str:
        """Resolve a slash-separated folder path, creating missing folders."""
        folder_parts = [part.strip() for part in folder_name.split("/") if part.strip()]
        if not folder_parts:
            return "0"

        try:
            from quark_client import create_client

            client = create_client(cookies=self.cookie, auto_login=False)
            parent_id = "0"

            for name in folder_parts:
                result = client.list_files(parent_id)
                files = result.get("data", {}).get("list", [])
                existing = next(
                    (f for f in files if f.get("file_name") == name and f.get("dir")),
                    None,
                )

                if existing:
                    parent_id = existing["fid"]
                    continue

                created = client.create_folder(name, parent_id)
                data = created.get("data", {})
                parent_id = data.get("fid") or data.get("file", {}).get("fid")
                if not parent_id:
                    if response_payload_is_name_conflict(created):
                        raise QuarkNameConflict(f"Folder already exists or is being created: {name}", created)
                    raise RuntimeError(f"folder creation returned no fid: {created}")

            return parent_id
        except QuarkNameConflict:
            raise
        except Exception as e:
            if text_is_auth_error(str(e)):
                raise QuarkAuthRequired("Quark login expired or invalid") from e
            print(f"⚠️  Failed to resolve save folder '{folder_name}': {e}", file=sys.stderr)
            return "0"

    def download_fids(self, fids: list[str], target_dir: str = "/root/films") -> dict:
        """Download Quark file or folder IDs into a local directory."""
        if not self.cookie:
            return auth_required_result("Not logged in")

        if not fids:
            return {"error": "No file ids provided"}

        from quark_client import create_client

        root = Path(target_dir).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        client = create_client(cookies=self.cookie, auto_login=False)

        entries = []
        for fid in fids:
            entries.extend(self._download_fid(client, fid, root))

        errors = [entry for entry in entries if entry.get("status") == "error"]
        downloaded = [entry for entry in entries if entry.get("status") == "downloaded"]
        skipped = [entry for entry in entries if entry.get("status") == "skipped"]
        filtered = [entry for entry in entries if entry.get("status") == "filtered"]

        status = "ok"
        if errors and (downloaded or skipped):
            status = "partial"
        elif errors:
            status = "error"

        return {
            "status": status,
            "target_dir": str(root),
            "downloaded": len(downloaded),
            "skipped": len(skipped),
            "filtered": len(filtered),
            "errors": errors,
            "files": downloaded + skipped,
            "filtered_files": filtered,
        }

    def _download_fid(self, client, fid: str, target_dir: Path, file_info: Optional[dict] = None) -> list[dict]:
        try:
            info = self._normalize_file_info(file_info or client.get_file_info(fid))
            if info.get("fid") != fid:
                info = self._find_file_info_by_fid(client, fid) or {"fid": fid, "file_name": fid, "dir": False}
            name = self._safe_path_component(info.get("file_name") or fid)
            if self._should_skip_download(name):
                print(f"🚫 Skipping filtered file: {name}", file=sys.stderr)
                return [{"status": "filtered", "fid": fid, "path": str(target_dir / name)}]

            if info.get("dir"):
                folder = target_dir / name
                folder.mkdir(parents=True, exist_ok=True)
                entries = []
                page = 1
                page_size = 100
                while True:
                    result = client.list_files(fid, page=page, size=page_size)
                    children = result.get("data", {}).get("list", [])
                    if not children:
                        break
                    for child in children:
                        entries.extend(self._download_fid(client, child["fid"], folder, child))
                    if len(children) < page_size:
                        break
                    page += 1
                return entries

            target_path = target_dir / name
            file_size = self._file_size(info)
            if target_path.exists() and file_size and target_path.stat().st_size == file_size:
                print(f"⏭️  Skipping existing file: {target_path}", file=sys.stderr)
                return [{"status": "skipped", "fid": fid, "path": str(target_path)}]

            target_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"⬇️  Downloading: {name}", file=sys.stderr)
            last_percent = -1

            def progress(downloaded: int, total: int):
                nonlocal last_percent
                if total <= 0:
                    return
                percent = int(downloaded * 100 / total)
                if percent == 100 or percent >= last_percent + 10:
                    last_percent = percent
                    sys.stderr.write(f"\r   {percent:3d}% {downloaded}/{total} bytes")
                    sys.stderr.flush()

            saved_path = client.download_file(fid, str(target_path), progress_callback=progress)
            if last_percent >= 0:
                sys.stderr.write("\n")
                sys.stderr.flush()

            return [{"status": "downloaded", "fid": fid, "path": saved_path}]
        except Exception as e:
            return [{"status": "error", "fid": fid, "error": str(e)}]

    def _find_file_info_by_fid(self, client, fid: str, start_fid: str = "0", max_depth: int = 8) -> Optional[dict]:
        queue = [(start_fid, 0)]
        while queue:
            current_fid, depth = queue.pop(0)
            if depth > max_depth:
                continue
            page = 1
            page_size = 100
            while True:
                result = client.list_files(current_fid, page=page, size=page_size)
                children = result.get("data", {}).get("list", [])
                for child in children:
                    if child.get("fid") == fid:
                        return child
                    if child.get("dir"):
                        queue.append((child["fid"], depth + 1))
                if len(children) < page_size:
                    break
                page += 1
        return None

    @staticmethod
    def _normalize_file_info(info: dict) -> dict:
        data = info.get("data") if isinstance(info, dict) else None
        if isinstance(data, dict):
            if isinstance(data.get("list"), list) and data["list"]:
                return data["list"][0]
            return data
        return info or {}

    @staticmethod
    def _file_size(info: dict) -> int:
        for key in ("size", "file_size"):
            try:
                value = int(info.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
        return 0

    @staticmethod
    def _safe_path_component(name: str) -> str:
        import re

        cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip().strip(".")
        if not cleaned:
            return "unnamed"
        if len(cleaned) <= 180:
            return cleaned
        stem, ext = os.path.splitext(cleaned)
        return f"{stem[: max(1, 180 - len(ext))]}{ext}"

    @staticmethod
    def _should_skip_download(name: str) -> bool:
        lower_name = name.lower()
        _, ext = os.path.splitext(lower_name)
        if ext in SKIP_DOWNLOAD_EXTENSIONS:
            return True
        return any(keyword.lower() in lower_name for keyword in SKIP_DOWNLOAD_KEYWORDS)


def write_qr_png(text: str, path: Path, box_size: int = 10, border: int = 4) -> None:
    """Write a QR code PNG without requiring Pillow or pypng."""
    import qrcode

    qr = qrcode.QRCode(border=border)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    module_count = len(matrix)
    width = module_count * box_size
    height = width

    rows = []
    for matrix_row in matrix:
        pixel_row = bytearray()
        for dark in matrix_row:
            pixel_row.extend((b"\x00\x00\x00" if dark else b"\xff\xff\xff") * box_size)
        row = b"\x00" + bytes(pixel_row)
        rows.extend(row for _ in range(box_size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    png = [
        b"\x89PNG\r\n\x1a\n",
        chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
        chunk(b"IDAT", zlib.compress(b"".join(rows), level=9)),
        chunk(b"IEND", b""),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"".join(png))


def auth_required_result(message: str) -> dict:
    return {
        "error": message,
        "auth_required": True,
        "code": "QUARK_AUTH_REQUIRED",
    }


def name_conflict_result(message: str, existing_files: Optional[list[dict]] = None, payload: Optional[dict] = None) -> dict:
    result = {
        "error": message,
        "name_conflict": True,
        "code": "QUARK_NAME_CONFLICT",
        "message": "Quark target already has a same-name file/folder or an active save task.",
    }
    if existing_files:
        result["existing_files"] = existing_files
    if payload:
        quark_code = payload.get("code") or payload.get("data", {}).get("code")
        quark_message = payload.get("message") or payload.get("data", {}).get("message")
        if quark_code:
            result["quark_code"] = quark_code
        if quark_message:
            result["quark_message"] = quark_message
    return result


def response_json(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def exception_payload(exc: Exception) -> dict:
    data = getattr(exc, "response_data", None)
    return data if isinstance(data, dict) else {}


def response_is_auth_error(response: httpx.Response, data: Optional[dict] = None) -> bool:
    if response.status_code in (401, 403):
        return True
    return response_payload_is_auth_error(data or response_json(response))


def response_payload_is_auth_error(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    code = data.get("code")
    status = data.get("status")
    if code in (401, 403) or status in (401, 403):
        return True
    text = json.dumps(data, ensure_ascii=False)
    return text_is_auth_error(text)


def response_payload_is_name_conflict(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    code = data.get("code") or data.get("data", {}).get("code")
    if str(code) == "23008":
        return True
    text = json.dumps(data, ensure_ascii=False)
    return text_is_name_conflict(text)


def text_is_auth_error(text: str) -> bool:
    return bool(AUTH_ERROR_RE.search(str(text or "")))


def text_is_name_conflict(text: str) -> bool:
    return bool(NAME_CONFLICT_RE.search(str(text or "")))
