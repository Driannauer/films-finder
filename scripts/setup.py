#!/usr/bin/env python3
"""Interactive setup wizard for films-finder."""

import json
import os
import sys
import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(SCRIPT_DIR, "..")
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
EXAMPLE_PATH = os.path.join(SKILL_DIR, "config.example.json")
PLUGINS_DIR = os.path.join(SCRIPT_DIR, "plugins")


def discover_plugins() -> list[dict]:
    """Auto-discover available plugins from the plugins directory."""
    plugins = []
    for path in sorted(glob.glob(os.path.join(PLUGINS_DIR, "*.py"))):
        name = os.path.basename(path).replace(".py", "")
        if name.startswith("_") or name == "__init__":
            continue
        try:
            spec = {}
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("name ="):
                        spec["name"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("display_name ="):
                        spec["display_name"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("requires_auth ="):
                        spec["requires_auth"] = "True" in line
                    elif line.startswith("url ="):
                        spec["url"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if len(spec) >= 3:
                        break
            spec.setdefault("name", name)
            spec.setdefault("display_name", name)
            spec.setdefault("requires_auth", False)
            spec.setdefault("url", "")
            plugins.append(spec)
        except Exception:
            plugins.append({"name": name, "display_name": name, "requires_auth": False, "url": ""})
    return plugins


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    if os.path.exists(EXAMPLE_PATH):
        with open(EXAMPLE_PATH) as f:
            return json.load(f)
    return {
        "quark": {"cookie": ""},
        "plugins": {},
        "save_folder": "夸克影视",
        "download_after_save": False,
        "local_download_folder": "/root/films",
        "omdb_api_key": "",
    }


def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 配置已保存到 {CONFIG_PATH}")


def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    val = input(f"{prompt}{hint}: ").strip()
    return val if val else default


def main():
    print("=" * 50)
    print("🎬 films-finder 设置向导")
    print("=" * 50)

    config = load_config()
    available_plugins = discover_plugins()

    # ── Step 1: Quark Auth ──
    print("\n📁 第一步：夸克网盘登录\n")
    print("  推荐：先退出本向导，运行 python3 scripts/cinema.py login 扫码登录并自动保存 Cookie")
    print("  手动：浏览器打开 pan.quark.cn → F12 → Network → 复制任意请求的 Cookie 头")
    print()

    cookie = ask("Cookie（已扫码登录可直接回车）", config["quark"].get("cookie", ""))
    config["quark"]["cookie"] = cookie

    # ── Step 2: Content Sources ──
    print(f"\n🔍 第二步：内容源配置（发现 {len(available_plugins)} 个插件）\n")

    if not available_plugins:
        print("  未发现插件，请将插件 .py 文件放入 scripts/plugins/ 目录")
    else:
        for i, plugin in enumerate(available_plugins, 1):
            auth_tag = "（需登录）" if plugin["requires_auth"] else "（免费）"
            url_tag = f" {plugin['url']}" if plugin["url"] else ""
            print(f"  {i}. {plugin['display_name']}{auth_tag}{url_tag}")
        print()

        for plugin in available_plugins:
            current = config.get("plugins", {}).get(plugin["name"], {}).get("enabled", False)
            default = "y" if current else "n"
            choice = ask(f"启用 {plugin['display_name']}？(y/n)", default)

            if plugin["name"] not in config["plugins"]:
                config["plugins"][plugin["name"]] = {}

            if choice.lower() == "y":
                config["plugins"][plugin["name"]]["enabled"] = True
                if plugin["requires_auth"]:
                    config["plugins"][plugin["name"]]["username"] = ask(f"  {plugin['display_name']} 账号")
                    config["plugins"][plugin["name"]]["password"] = ask(f"  {plugin['display_name']} 密码")
            else:
                config["plugins"][plugin["name"]]["enabled"] = False

    # ── Step 3: Genre Classification ──
    print("\n🎭 第三步：自动类型分类\n")
    print("  影片会自动归入 动作/剧情/科幻 等文件夹")
    print()
    print("  方式一：OMDB API（免费，1000次/天，准确率高）")
    print("  方式二：从兼容内容源页面抓取（免费，准确率取决于内容源）")
    print("  方式三：不配置外部类型来源（无法识别时归入“其他”）")
    print()

    genre_choice = ask("选择 (1=OMDB, 2=内容源抓取, 3=归入其他)", "1")

    if genre_choice == "1":
        print("\n  获取OMDB Key：")
        print("  1. 打开 http://www.omdbapi.com/apikey.aspx")
        print("  2. 选择 FREE，填写邮箱")
        print("  3. 收到邮件，复制 API Key")
        print()
        omdb_key = ask("OMDB API Key", config.get("omdb_api_key", ""))
        config["omdb_api_key"] = omdb_key
    elif genre_choice == "2":
        config["omdb_api_key"] = ""
        print("  → 将从兼容内容源页面抓取类型信息")
    else:
        config["omdb_api_key"] = ""
        print("  → 无法识别类型时归入“其他”")

    # ── Step 4: Save Folder ──
    print("\n📂 第四步：保存目录\n")
    folder = ask("夸克网盘中的保存目录名", config.get("save_folder", "夸克影视"))
    config["save_folder"] = folder

    # ── Step 5: Local Download ──
    print("\n💾 第五步：本地同步下载\n")
    download_default = "y" if config.get("download_after_save", False) else "n"
    download_choice = ask("转存成功后同步下载到本地？(y/n)", download_default)
    config["download_after_save"] = download_choice.lower() == "y"
    if config["download_after_save"]:
        local_folder = ask("本地下载目录", config.get("local_download_folder", "/root/films"))
        config["local_download_folder"] = local_folder

    # ── Save ──
    save_config(config)

    # ── Summary ──
    print("\n" + "=" * 50)
    print("📋 配置摘要")
    print("=" * 50)
    if config["quark"].get("cookie"):
        print(f"  夸克登录：Cookie（{len(config['quark']['cookie'])}字符）")
    else:
        print("  ⚠️  夸克未配置！")

    enabled = [k for k, v in config.get("plugins", {}).items() if v.get("enabled")]
    print(f"  内容源：{', '.join(enabled) if enabled else '无'}")
    print(f"  保存目录：{config['save_folder']}")
    if config.get("download_after_save", False):
        print(f"  本地同步：{config.get('local_download_folder', '/root/films')}")
    else:
        print("  本地同步：关闭")

    if config.get("omdb_api_key"):
        print(f"  类型分类：OMDB API ✅")
    elif genre_choice == "2":
        print(f"  类型分类：内容源抓取")
    else:
        print(f"  类型分类：无法识别时归入“其他”")

    print("\n🎬 完成！对你的 Hermes Agent 说「我要看电影」试试吧！\n")


if __name__ == "__main__":
    main()
