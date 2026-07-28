#!/usr/bin/env python3
"""
films-finder - Search content sources and save to Quark cloud drive.

Usage:
    cinema.py login                    Terminal QR login and save Quark cookie
    cinema.py login --qr               Create QR image for Hermes media delivery
    cinema.py login --confirm          Confirm latest QR login and save Quark cookie
    cinema.py search <query>           Search all enabled plugins
    cinema.py save <quark_url>         Save a quark share link
    cinema.py save --index N [query]   Save selected search result by index
    cinema.py auto <query>             Search + auto-save best version
    cinema.py download <fid> [...]     Download Quark file/folder IDs locally
    cinema.py organize <fid> <title>   Organize saved file into library
    cinema.py plugins                  List available plugins
"""

import json
import multiprocessing as mp
import os
import queue
import re
import sys
import time
import importlib
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from plugins import ResourcePlugin, ResourceResult
from quark import QuarkClient
from library import LibraryManager

CONFIG_PATHS = [
    SCRIPT_DIR.parent / "config.json",
    Path.home() / ".films-finder" / "config.json",
]
DEFAULT_LOCAL_DOWNLOAD_DIR = "/root/films"
DEFAULT_PLUGIN_SEARCH_TIMEOUT = 20
DEFAULT_QUARK_LOGIN_TIMEOUT = 300
DEFAULT_QUARK_CONFIRM_TIMEOUT = 60
SEARCH_CACHE_PATH = Path.home() / ".films-finder" / "last_search.json"
MAX_TABLE_TITLE_WIDTH = 120
SIZE_RE = re.compile(
    r"(?i)(\d+(?:\.\d+)?)\s*(TB|GB|MB|G|M)(?=$|[\s\]\)】）._-]|[^0-9A-Za-z])"
)
TITLE_PREFIX_RE = re.compile(r"^\s*(?:[【\[]\s*)?(?:名称|标题|资源标题)(?:\s*[】\]])?\s*[:：]\s*")
TITLE_DESCRIPTION_RE = re.compile(r"\s*[【\[]\s*描述\s*[】\]]\s*[:：].*$")
URL_RE = re.compile(r"https?://\S+")


def load_config() -> dict:
    for p in CONFIG_PATHS:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return {}


def get_config_path() -> Path:
    for p in CONFIG_PATHS:
        if p.exists():
            return p
    return CONFIG_PATHS[0]


def save_config(config: dict) -> Path:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return path


def save_quark_cookie(config: dict, cookie: str) -> Path:
    config.setdefault("quark", {})["cookie"] = cookie
    return save_config(config)


def get_local_download_dir(config: dict) -> str:
    return config.get("local_download_folder") or DEFAULT_LOCAL_DOWNLOAD_DIR


def download_after_save_enabled(config: dict) -> bool:
    return config.get("download_after_save", False) is True


def get_plugin_search_timeout(config: dict) -> int:
    try:
        return int(config.get("plugin_search_timeout", DEFAULT_PLUGIN_SEARCH_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_PLUGIN_SEARCH_TIMEOUT


def get_quark_login_timeout(config: dict) -> int:
    quark_config = config.get("quark", {})
    try:
        return int(quark_config.get("login_timeout", DEFAULT_QUARK_LOGIN_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_QUARK_LOGIN_TIMEOUT


class PluginSearchTimeout(BaseException):
    pass


def _plugin_call_worker(plugin, method_name: str, args: tuple, output):
    try:
        result = getattr(plugin, method_name)(*args)
        output.put({"ok": True, "result": result})
    except BaseException as e:
        output.put({"ok": False, "error": f"{type(e).__name__}: {e}"})


def plugin_call_with_timeout(plugin, method_name: str, args: tuple, timeout: int):
    if timeout <= 0:
        return getattr(plugin, method_name)(*args)

    if "fork" in mp.get_all_start_methods():
        context = mp.get_context("fork")
    else:
        context = mp.get_context()

    output = context.Queue(maxsize=1)
    process = context.Process(
        target=_plugin_call_worker,
        args=(plugin, method_name, args, output),
        daemon=True,
    )
    process.start()
    process.join(timeout)

    if process.is_alive():
        process.terminate()
        process.join(3)
        if process.is_alive():
            process.kill()
            process.join(3)
        raise PluginSearchTimeout(f"{method_name} timed out")

    try:
        payload = output.get(timeout=1)
    except queue.Empty:
        if process.exitcode == 0:
            return [] if method_name == "search" else None
        raise RuntimeError(f"{method_name} exited with code {process.exitcode}")

    if not payload.get("ok"):
        raise RuntimeError(payload.get("error", f"{method_name} failed"))
    return payload.get("result")


def search_plugin_with_timeout(plugin, query: str, timeout: int) -> list[ResourceResult]:
    return plugin_call_with_timeout(plugin, "search", (query,), timeout)


def extract_size_from_title(title: str) -> str:
    match = SIZE_RE.search(title or "")
    if not match:
        return ""

    number, unit = match.groups()
    unit = unit.upper()
    if unit == "G":
        unit = "GB"
    elif unit == "M":
        unit = "MB"
    return f"{number}{unit}"


def display_size(resource: ResourceResult) -> str:
    size = (resource.size or "").strip()
    return size or extract_size_from_title(resource.title) or "-"


def clean_display_title(title: str) -> str:
    cleaned = TITLE_PREFIX_RE.sub("", title or "").strip()
    cleaned = TITLE_DESCRIPTION_RE.sub("", cleaned).strip()
    cleaned = URL_RE.sub("", cleaned).strip()
    cleaned = " ".join(cleaned.split())
    return cleaned or "-"


def truncate_display_text(text: str, max_width: int = MAX_TABLE_TITLE_WIDTH) -> str:
    if len(text) <= max_width:
        return text
    return text[: max_width - 3].rstrip() + "..."


def markdown_cell(value) -> str:
    return str(value).replace("\n", " ").replace("|", "\\|")


def format_search_results_table(results: list[ResourceResult]) -> str:
    if not results:
        return "未找到结果。"

    lines = [
        "| 序号 | 内容 | 大小 | 得分 |",
        "|---:|---|---:|---:|",
    ]
    for index, resource in enumerate(results, start=1):
        title = truncate_display_text(clean_display_title(resource.title))
        score = resource.extra.get("score", 0)
        lines.append(
            f"| {index} | {markdown_cell(title)} | "
            f"{markdown_cell(display_size(resource))} | {markdown_cell(score)} |"
        )
    return "\n".join(lines)


def resource_to_dict(
    resource: ResourceResult,
    index: int = 0,
    truncate_url: bool = False,
    include_extra: bool = True,
) -> dict:
    url = resource.url[:80] if truncate_url else resource.url
    data = {
        "title": resource.title,
        "source": resource.source,
        "site": resource.site,
        "score": resource.extra.get("score", 0),
        "url": url,
    }
    if index:
        data["index"] = index
    if resource.quality:
        data["quality"] = resource.quality
    size = display_size(resource)
    if size != "-":
        data["size"] = size
    if include_extra and resource.extra:
        data["extra"] = resource.extra
    return data


def resource_from_dict(data: dict) -> ResourceResult:
    return ResourceResult(
        title=data.get("title", ""),
        source=data.get("source", ""),
        url=data.get("url", ""),
        quality=data.get("quality", ""),
        size=data.get("size", ""),
        site=data.get("site", ""),
        extra=data.get("extra", {}) if isinstance(data.get("extra", {}), dict) else {},
    )


def save_search_cache(query: str, results: list[ResourceResult]) -> None:
    SEARCH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "query": query,
        "created_at": int(time.time()),
        "results": [
            resource_to_dict(result, index=i)
            for i, result in enumerate(results[:20], start=1)
        ],
    }
    with open(SEARCH_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_search_cache() -> dict:
    if not SEARCH_CACHE_PATH.exists():
        return {}
    with open(SEARCH_CACHE_PATH, encoding="utf-8") as f:
        return json.load(f)


def fallback_queries(query: str) -> list[str]:
    normalized = " ".join(query.lower().split())
    fallbacks = []
    if normalized == "007" or ("007" in normalized and "bond" in normalized):
        fallbacks.extend(["007系列", "詹姆斯邦德"])
    elif normalized == "james bond":
        fallbacks.extend(["詹姆斯邦德", "007系列"])

    seen = {query}
    unique = []
    for item in fallbacks:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return unique


def prefer_fallback_queries(query: str) -> bool:
    normalized = " ".join(query.lower().split())
    return (
        normalized in {"007", "james bond"}
        or ("007" in normalized and "bond" in normalized)
    )


def search_resources(query: str, config: dict) -> tuple[list[ResourceResult], list]:
    plugins = load_plugins(config)
    if not plugins:
        return [], []

    search_timeout = get_plugin_search_timeout(config)
    all_results = []
    for plugin in plugins:
        print(f"🔍 Searching {plugin.display_name}...", file=sys.stderr)
        try:
            results = search_plugin_with_timeout(plugin, query, search_timeout)
            for r in results:
                r.site = plugin.name
                r.extra["score"] = score_resource(r)
            all_results.extend(results)
        except PluginSearchTimeout:
            print(f"⚠️  {plugin.name} timed out after {search_timeout}s", file=sys.stderr)
        except Exception as e:
            print(f"⚠️  {plugin.name} error: {e}", file=sys.stderr)

    all_results.sort(key=lambda r: r.extra.get("score", 0), reverse=True)
    return all_results, plugins


def search_resources_with_fallback(query: str, config: dict) -> tuple[list[ResourceResult], list, str]:
    fallbacks = fallback_queries(query)
    preferred_fallbacks = fallbacks if prefer_fallback_queries(query) else []

    for fallback in preferred_fallbacks:
        print(f"↪️  Trying {fallback!r} for {query!r}...", file=sys.stderr)
        results, plugins = search_resources(fallback, config)
        if results:
            return results, plugins, fallback
        if not plugins:
            return results, plugins, query

    results, plugins = search_resources(query, config)
    if results or not plugins:
        return results, plugins, query

    for fallback in fallbacks:
        if fallback in preferred_fallbacks:
            continue
        print(f"↪️  No results for {query!r}; trying {fallback!r}...", file=sys.stderr)
        results, plugins = search_resources(fallback, config)
        if results:
            return results, plugins, fallback

    return results, plugins, query


def save_succeeded(result: dict) -> bool:
    return result.get("status") == 200 or result.get("code") == 0


def extract_saved_fids(result: dict) -> list[str]:
    candidates = [
        ("task_result", "data", "save_as", "save_as_top_fids"),
        ("task_result", "data", "save_as_top_fid"),
        ("data", "save_as", "save_as_top_fids"),
        ("data", "save_as_top_fids"),
        ("save_as", "save_as_top_fids"),
        ("save_as_top_fids",),
    ]
    fids = []
    for path in candidates:
        value = result
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if not value:
            continue
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            for fid in value:
                if fid and fid not in fids:
                    fids.append(fid)
    return fids


def sync_saved_files(client: QuarkClient, config: dict, result: dict, saved_fids: list[str] = None) -> dict | None:
    if not download_after_save_enabled(config):
        return None
    if not save_succeeded(result):
        return None

    fids = saved_fids or extract_saved_fids(result)
    if not fids:
        print("⚠️  Save succeeded but no saved file IDs were returned; local download skipped.", file=sys.stderr)
        return None

    target_dir = get_local_download_dir(config)
    print(f"💾 Syncing saved files to {target_dir}...", file=sys.stderr)
    return client.download_fids(fids, target_dir=target_dir)


def load_plugins(config: dict) -> list:
    plugins = []
    plugin_configs = config.get("plugins", {})
    plugin_dir = SCRIPT_DIR / "plugins"

    for f in sorted(plugin_dir.glob("*.py")):
        if f.name.startswith("_") or f.name == "base.py":
            continue
        module_name = f.stem
        plugin_conf = plugin_configs.get(module_name, {})
        if not plugin_conf.get("enabled", True):
            continue
        try:
            mod = importlib.import_module(f"plugins.{module_name}")
            if hasattr(mod, "Plugin"):
                plugins.append(mod.Plugin(config=plugin_conf))
        except Exception as e:
            print(f"⚠️  Failed to load plugin {module_name}: {e}", file=sys.stderr)

    return plugins


def get_quark_client(config: dict, force_login: bool = False, timeout: int = 300) -> QuarkClient:
    quark_conf = config.get("quark", {})
    client = QuarkClient(
        cookie=quark_conf.get("cookie", ""),
    )

    if force_login:
        cookie = client.login(force=True, timeout=timeout)
        save_quark_cookie(config, cookie)
    elif not quark_conf.get("cookie") and client.cookie:
        save_quark_cookie(config, client.cookie)

    return client


def quark_auth_required(result: dict) -> bool:
    return isinstance(result, dict) and result.get("auth_required") is True


def print_quark_login_prompt(login: dict) -> None:
    print("🔐 夸克网盘登录已失效，请使用夸克 App 扫描下面二维码重新登录。")
    print(login["media"])
    print("扫码后回复：已扫码")


def start_quark_login_for_hermes(client: QuarkClient, config: dict, pending: dict = None) -> dict:
    return client.start_login_qr(
        timeout=get_quark_login_timeout(config),
        pending=pending or {},
    )


def save_share_once(client: QuarkClient, config: dict, share_url: str, folder: str = "", title: str = "") -> dict:
    target_folder = folder or config.get("save_folder", "")
    print(f"☁️  Saving to Quark: {share_url}", file=sys.stderr)
    result = client.save_share(share_url, folder_name=target_folder, title=title)
    download_result = sync_saved_files(client, config, result)
    return {"result": result, "local_download": download_result}


# ── Quality Scoring ──

QUALITY_SCORES = {"2160p": 100, "4k": 100, "uhd": 100, "1080p": 50, "1080i": 45, "720p": 20, "480p": 5}
SOURCE_SCORES = {"bluray": 90, "remux": 85, "bdrip": 80, "web-dl": 70, "webdl": 70, "webrip": 65, "hdtv": 40, "cam": 5}
HDR_SCORES = {"dolby.vision": 30, "dv": 30, "hdr10+": 25, "hdr10": 20, "hdr": 15}
AUDIO_SCORES = {"atmos": 15, "truehd": 12, "dts-hd": 10, "dts": 8, "eac3": 7, "ddp": 7, "ac3": 3, "aac": 2}
CODEC_SCORES = {"h265": 10, "hevc": 10, "x265": 10, "h264": 5, "x264": 5}
SUB_KW = ["字幕", "subtitle", "chs", "cht", "中英", "中字", "双语"]


def score_resource(res: ResourceResult) -> int:
    t = res.title.lower()
    s = 0
    for table in [QUALITY_SCORES, SOURCE_SCORES, HDR_SCORES, AUDIO_SCORES, CODEC_SCORES]:
        for k, v in table.items():
            if k in t:
                s += v
                break
    if any(kw in t for kw in SUB_KW):
        s += 5
    if res.source == "quark":
        s += 15
    return s


# ── Commands ──

def cmd_login(config: dict, timeout: int = 300):
    client = get_quark_client(config, force_login=True, timeout=timeout)
    path = save_quark_cookie(config, client.cookie)
    print(json.dumps({
        "status": "ok",
        "message": "Quark cookie saved",
        "config": str(path),
        "cookie_length": len(client.cookie),
    }, indent=2, ensure_ascii=False))


def cmd_login_qr(config: dict, timeout: int = DEFAULT_QUARK_LOGIN_TIMEOUT):
    client = get_quark_client(config)
    login = client.start_login_qr(timeout=timeout)
    print_quark_login_prompt(login)
    print(json.dumps({
        "status": "qr_ready",
        "message": "Scan QR with Quark App, then run login --confirm",
        "login": login,
    }, indent=2, ensure_ascii=False))
    return login


def cmd_login_confirm(config: dict, timeout: int = DEFAULT_QUARK_CONFIRM_TIMEOUT, retry_pending: bool = True):
    client = get_quark_client(config)
    pending = client.get_pending_login_action()
    cookie = client.confirm_login(timeout=timeout)
    config_path = save_quark_cookie(config, cookie)

    output = {
        "status": "ok",
        "message": "Quark cookie saved",
        "config": str(config_path),
        "cookie_length": len(cookie),
    }

    if retry_pending and pending.get("action") == "save" and pending.get("share_url"):
        print("☁️  Retrying pending Quark save...", file=sys.stderr)
        retry = save_share_once(
            client,
            config,
            pending["share_url"],
            folder=pending.get("folder", ""),
            title=pending.get("title", ""),
        )
        output["retry"] = retry
        if not quark_auth_required(retry.get("result", {})):
            client.clear_pending_login_action()

    print(json.dumps(output, indent=2, ensure_ascii=False))
    return output


def cmd_download(fids: list[str], config: dict, target_dir: str = ""):
    client = get_quark_client(config)
    result = client.download_fids(fids, target_dir=target_dir or get_local_download_dir(config))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def cmd_search(query: str, config: dict):
    all_results, plugins, matched_query = search_resources_with_fallback(query, config)
    if not plugins:
        print("❌ No plugins enabled. Edit config.json.")
        return []

    save_search_cache(matched_query, all_results)

    if matched_query != query:
        print(f"匹配查询：{matched_query}")
    print(format_search_results_table(all_results[:20]))
    return all_results


def cmd_save(share_url: str, config: dict, folder: str = "", title: str = ""):
    client = get_quark_client(config)
    output = save_share_once(client, config, share_url, folder=folder, title=title)
    result = output["result"]

    if quark_auth_required(result):
        login = start_quark_login_for_hermes(
            client,
            config,
            pending={
                "action": "save",
                "share_url": share_url,
                "folder": folder or config.get("save_folder", ""),
                "title": title,
                "created_at": int(time.time()),
            },
        )
        output["login"] = login
        print_quark_login_prompt(login)

    print(json.dumps(output, indent=2, ensure_ascii=False))
    return output


def select_result_by_index(results: list[ResourceResult], index: int) -> ResourceResult:
    if index < 1 or index > len(results):
        raise ValueError(f"index {index} out of range; available range is 1-{len(results)}")
    return results[index - 1]


def extract_share_url(plugin, resource: ResourceResult, timeout: int = DEFAULT_PLUGIN_SEARCH_TIMEOUT) -> str:
    if resource.url.startswith("https://pan.quark.cn/"):
        return resource.url
    share_url = plugin_call_with_timeout(plugin, "extract_link", (resource,), timeout)
    if not share_url:
        raise RuntimeError("failed to extract share URL")
    return share_url


def cmd_save_index(index: int, config: dict, query: str = "", folder: str = "", dry_run: bool = False):
    plugins_by_name = {plugin.name: plugin for plugin in load_plugins(config)}

    if query:
        results, _, matched_query = search_resources_with_fallback(query, config)
        if not results:
            print("❌ No results found.")
            return None
        save_search_cache(matched_query, results)
        cache_query = matched_query
    else:
        cache = load_search_cache()
        cache_query = cache.get("query", "")
        results = [resource_from_dict(item) for item in cache.get("results", [])]
        if not results:
            print(f"❌ No cached search results. Run: cinema.py search <query>")
            return None

    selected = select_result_by_index(results, index)
    plugin = plugins_by_name.get(selected.site)
    if not plugin and not selected.url.startswith("https://pan.quark.cn/"):
        print(f"❌ Plugin not found for cached result: {selected.site}")
        return None

    print(f"🎯 Selected #{index}: {selected.title}", file=sys.stderr)
    print("🔗 Extracting link...", file=sys.stderr)
    link_timeout = get_plugin_search_timeout(config)
    share_url = extract_share_url(plugin, selected, link_timeout) if plugin else selected.url

    if dry_run:
        output = {
            "query": cache_query,
            "index": index,
            "selected": resource_to_dict(selected, index=index, truncate_url=True, include_extra=False),
            "share_url": share_url,
            "dry_run": True,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return output

    return cmd_save(share_url, config, folder=folder, title=clean_display_title(selected.title))


def cmd_auto(query: str, config: dict):
    all_results, plugins, matched_query = search_resources_with_fallback(query, config)
    if not plugins:
        print("❌ No plugins enabled.")
        return

    if not all_results:
        print("❌ No results found.")
        return

    save_search_cache(matched_query, all_results)
    quark_results = [r for r in all_results if r.source == "quark"]

    if not quark_results:
        print("❌ No Quark resources found.")
        for r in all_results[:5]:
            print(f"  [{r.source}] {r.title}")
        return

    best = quark_results[0]
    print(f"\n🏆 Best: {best.title}", file=sys.stderr)
    print(f"   Score: {best.extra.get('score', 0)}", file=sys.stderr)

    plugin = next((p for p in plugins if p.name == best.site), None)
    if not plugin:
        print("❌ Plugin not found")
        return

    print(f"🔗 Extracting link...", file=sys.stderr)
    share_url = extract_share_url(plugin, best, get_plugin_search_timeout(config))
    if not share_url:
        print("❌ Failed to extract link")
        return

    print(f"   URL: {share_url}", file=sys.stderr)

    # Save
    client = get_quark_client(config)
    folder = config.get("save_folder", "影视资源")
    print(f"☁️  Saving to Quark/{folder}...", file=sys.stderr)
    result = client.save_share(share_url, folder_name=folder, title=clean_display_title(best.title))
    download_result = None
    saved_fids = []

    if quark_auth_required(result):
        login = start_quark_login_for_hermes(
            client,
            config,
            pending={
                "action": "save",
                "share_url": share_url,
                "folder": folder,
                "title": clean_display_title(best.title),
                "created_at": int(time.time()),
            },
        )
        print_quark_login_prompt(login)
        print(json.dumps({
            "movie": best.title,
            "share_url": share_url,
            "result": result,
            "login": login,
            "local_download": None,
        }, indent=2, ensure_ascii=False))
        return

    status = result.get("status", 0)
    if status == 200:
        # Organize into library
        task_data = result.get("task_result", {}).get("data", {})
        save_as = task_data.get("save_as", {})
        saved_fids = save_as.get("save_as_top_fids", [])

        if saved_fids:
            from library import extract_movie_info
            info = extract_movie_info(best.title)
            lib = LibraryManager(client, library_root=folder,
                                 omdb_key=config.get("omdb_api_key", ""),
                                 genre_cache_file=os.path.join(os.path.dirname(__file__), "genre_cache.json"))

            # Build mini4k URL for genre scraping if applicable
            mini4k_url = ""
            if best.site == "mini4k" and best.url.startswith("/"):
                mini4k_url = f"https://www.mini4k.net{best.url}"

            for fid in saved_fids:
                org_result = lib.organize_movie(fid, best.title, info.get("year", ""), mini4k_url)
                if org_result.get("status") == "ok":
                    print(f"📁 Organized: {org_result['path']}", file=sys.stderr)
                else:
                    print(f"⚠️  Organize failed: {org_result.get('error')}", file=sys.stderr)

        print(f"✅ Done!", file=sys.stderr)
        download_result = sync_saved_files(client, config, result, saved_fids)
    else:
        print(f"❌ Failed: {result.get('message', 'unknown')}", file=sys.stderr)

    print(json.dumps({"movie": best.title, "share_url": share_url, "result": result,
                      "local_download": download_result},
                     indent=2, ensure_ascii=False))


def cmd_organize(fid: str, title: str, config: dict, content_type: str = "movie",
                 season: int = 1, episode: int = 0):
    client = get_quark_client(config)
    lib = LibraryManager(client, library_root=config.get("save_folder", "影视资源"),
                         omdb_key=config.get("omdb_api_key", ""),
                         genre_cache_file=os.path.join(os.path.dirname(__file__), "genre_cache.json"))

    if content_type == "tv":
        result = lib.organize_tv_show(fid, title, season=season, episode=episode)
    else:
        result = lib.organize_movie(fid, title)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def cmd_plugins(config: dict):
    plugins = load_plugins(config)
    if not plugins:
        print("No plugins found.")
        print("\nTo add a resource site, create a plugin file:")
        print("  cp scripts/plugins/example.py scripts/plugins/your_site.py")
        print("  # Edit your_site.py, implement search() and extract_link()")
        print('  # Add to config.json: "your_site": {"enabled": true}')
        return

    print("Available plugins:")
    for p in plugins:
        auth = "🔑" if p.requires_auth else "🆓"
        print(f"  {auth} {p.display_name} ({p.name}) - {p.url}")


def parse_save_args(args: list[str]) -> dict:
    parsed = {
        "share_url": "",
        "index": None,
        "query": "",
        "folder": "",
        "dry_run": False,
    }
    query_parts = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--index" and i + 1 < len(args):
            parsed["index"] = int(args[i + 1])
            i += 2
        elif arg == "--index":
            raise ValueError("--index requires a number")
        elif arg == "--query" and i + 1 < len(args):
            query_parts.append(args[i + 1])
            i += 2
        elif arg == "--query":
            raise ValueError("--query requires a value")
        elif arg in ("--folder", "-f") and i + 1 < len(args):
            parsed["folder"] = args[i + 1]
            i += 2
        elif arg in ("--folder", "-f"):
            raise ValueError(f"{arg} requires a folder name")
        elif arg == "--dry-run":
            parsed["dry_run"] = True
            i += 1
        elif arg.startswith("-"):
            raise ValueError(f"unsupported save option: {arg}")
        else:
            if parsed["index"] is None and not parsed["share_url"]:
                parsed["share_url"] = arg
            else:
                query_parts.append(arg)
            i += 1

    parsed["query"] = " ".join(query_parts).strip()
    return parsed


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    config = load_config()
    cmd = sys.argv[1]

    if cmd == "search":
        query = " ".join(sys.argv[2:])
        if not query:
            print("Usage: cinema.py search <query>"); sys.exit(1)
        cmd_search(query, config)

    elif cmd == "login":
        timeout = 300
        mode = "terminal"
        retry_pending = True
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--timeout" and i + 1 < len(sys.argv):
                timeout = int(sys.argv[i + 1]); i += 2
            elif sys.argv[i] == "--qr":
                mode = "qr"; i += 1
            elif sys.argv[i] == "--confirm":
                mode = "confirm"; i += 1
            elif sys.argv[i] == "--no-retry-pending":
                retry_pending = False; i += 1
            else:
                i += 1
        if mode == "qr":
            cmd_login_qr(config, timeout=timeout)
        elif mode == "confirm":
            cmd_login_confirm(config, timeout=timeout, retry_pending=retry_pending)
        else:
            cmd_login(config, timeout=timeout)

    elif cmd == "save":
        if len(sys.argv) < 3:
            print("Usage: cinema.py save <quark_share_url> | cinema.py save --index N [query]"); sys.exit(1)
        try:
            args = parse_save_args(sys.argv[2:])
            if args["index"] is not None:
                cmd_save_index(args["index"], config, query=args["query"],
                               folder=args["folder"], dry_run=args["dry_run"])
            elif args["share_url"]:
                if args["dry_run"]:
                    print(json.dumps({"share_url": args["share_url"], "dry_run": True},
                                     indent=2, ensure_ascii=False))
                else:
                    cmd_save(args["share_url"], config, folder=args["folder"])
            else:
                print("Usage: cinema.py save <quark_share_url> | cinema.py save --index N [query]")
                sys.exit(1)
        except Exception as e:
            print(f"❌ Save failed: {e}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "save-index":
        if len(sys.argv) < 3:
            print("Usage: cinema.py save-index <index> [query] [--dry-run]"); sys.exit(1)
        try:
            args = parse_save_args(["--index", sys.argv[2], *sys.argv[3:]])
            cmd_save_index(args["index"], config, query=args["query"],
                           folder=args["folder"], dry_run=args["dry_run"])
        except Exception as e:
            print(f"❌ Save failed: {e}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "download":
        if len(sys.argv) < 3:
            print("Usage: cinema.py download <file_id> [...] [--dir /root/films]")
            sys.exit(1)
        fids = []
        target_dir = ""
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] in ("--dir", "-d") and i + 1 < len(sys.argv):
                target_dir = sys.argv[i + 1]; i += 2
            else:
                fids.append(sys.argv[i]); i += 1
        cmd_download(fids, config, target_dir)

    elif cmd == "auto":
        query = " ".join(sys.argv[2:])
        if not query:
            print("Usage: cinema.py auto <query>"); sys.exit(1)
        cmd_auto(query, config)

    elif cmd == "organize":
        if len(sys.argv) < 4:
            print("Usage: cinema.py organize <file_id> <title> [--type movie|tv] [--season N] [--episode N]")
            sys.exit(1)
        fid = sys.argv[2]
        title = sys.argv[3]
        content_type = "movie"
        season, episode = 1, 0
        i = 4
        while i < len(sys.argv):
            if sys.argv[i] == "--type" and i + 1 < len(sys.argv):
                content_type = sys.argv[i + 1]; i += 2
            elif sys.argv[i] == "--season" and i + 1 < len(sys.argv):
                season = int(sys.argv[i + 1]); i += 2
            elif sys.argv[i] == "--episode" and i + 1 < len(sys.argv):
                episode = int(sys.argv[i + 1]); i += 2
            else:
                i += 1
        cmd_organize(fid, title, config, content_type, season, episode)

    elif cmd == "plugins":
        cmd_plugins(config)

    else:
        print(f"Unknown command: {cmd}\n{__doc__}")
        sys.exit(1)


if __name__ == "__main__":
    main()
