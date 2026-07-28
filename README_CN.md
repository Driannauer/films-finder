# films-finder

[English](README.md)

`films-finder` 是一个 [Hermes Agent](https://github.com/nousresearch/hermes-agent) 技能和 Python 命令行工具：搜索影视内容源、按质量排序、把选中的资源转存到夸克网盘，并整理成适合 Infuse、Plex 或 Jellyfin 使用的个人媒体库。

## 功能

- 同时搜索所有已启用的内容源插件并合并结果。
- 按分辨率、片源、HDR、音频、编码、字幕和网盘类型自动评分。
- 先展示带序号的结果表，再按用户选择转存，不会默认盲选。
- 支持终端扫码，以及适合 Hermes 聊天发送的图片二维码登录。
- Cookie 失效时记录当前转存任务，重新登录后自动重试原任务。
- 转存时过滤推广图片，并尽量复用已有目录和同名文件。
- 支持转存成功后自动下载到本地，也可按文件 ID 手动下载。
- 将电影和剧集整理成媒体服务器容易识别的目录结构。

## 环境要求

- Python 3.10 或更高版本
- 夸克网盘账号和夸克 App
- 如需对话式使用，需要 Hermes Agent
- 可选的 [OMDb API Key](https://www.omdbapi.com/apikey.aspx)，用于影片类型分类

## 安装

```bash
git clone https://github.com/Driannauer/films-finder.git ~/.hermes/skills/films-finder
cd ~/.hermes/skills/films-finder

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.json config.json
.venv/bin/python scripts/setup.py
```

`config.json` 会保存本地凭据，已被 Git 忽略。

## 快速开始

先在交互式终端扫码登录：

```bash
.venv/bin/python scripts/cinema.py login
```

然后搜索、查看排序结果并转存指定条目：

```bash
.venv/bin/python scripts/cinema.py search '流浪地球2'
.venv/bin/python scripts/cinema.py save --index 1
```

最近一次搜索结果会缓存在 `~/.films-finder/last_search.json`。如果缓存可能已经过时，可以在转存时重新搜索：

```bash
.venv/bin/python scripts/cinema.py save --index 1 '流浪地球2'
```

也可以直接转存夸克分享链接：

```bash
.venv/bin/python scripts/cinema.py save 'https://pan.quark.cn/s/your-share-id'
```

## 在 Hermes 中使用

把仓库安装到 `~/.hermes/skills/films-finder` 后，可以直接对助手说：

- “搜索星际穿越。”
- “保存第 2 个。”
- “自动帮我选流浪地球 2 的最佳版本。”
- “把这个夸克文件整理成第一季第三集。”

聊天场景使用两步扫码流程：

```bash
# 生成可由 Hermes 作为媒体附件发送的 PNG 二维码
.venv/bin/python scripts/cinema.py login --qr

# 用户用夸克 App 扫码后执行
.venv/bin/python scripts/cinema.py login --confirm --timeout 60
```

如果转存时发现 Cookie 已失效，`films-finder` 会生成新二维码并记录原转存任务。`login --confirm` 保存新 Cookie 后，会自动重试这一个任务。

## 命令速查

| 命令 | 用途 |
|---|---|
| `cinema.py search <关键词>` | 搜索已启用插件、排序并缓存最新结果 |
| `cinema.py save --index N [关键词]` | 转存缓存中的第 `N` 条；传入关键词时会重新搜索 |
| `cinema.py save <分享链接>` | 直接转存夸克分享链接 |
| `cinema.py auto <关键词>` | 自动选择得分最高的夸克结果，转存并按电影整理 |
| `cinema.py login` | 在终端显示二维码并保存登录 Cookie |
| `cinema.py login --qr` | 生成供 Hermes 发送的二维码图片 |
| `cinema.py login --confirm` | 确认最近一次扫码，并重试待处理转存 |
| `cinema.py download <fid> [...]` | 按夸克文件或文件夹 ID 下载到本地 |
| `cinema.py organize <fid> <标题>` | 将已有夸克文件整理成电影或剧集 |
| `cinema.py plugins` | 查看已启用的内容源插件 |

常用选项：

```bash
# 只预览解析到的结果和分享链接，不执行转存
.venv/bin/python scripts/cinema.py save --index 1 --dry-run

# 本次转存使用其他目标目录
.venv/bin/python scripts/cinema.py save --index 1 --folder '我的媒体库'

# 递归下载一个文件或文件夹
.venv/bin/python scripts/cinema.py download <fid> --dir /srv/media

# 按剧集整理
.venv/bin/python scripts/cinema.py organize <fid> '剧名' \
  --type tv --season 1 --episode 3
```

## 配置

可以重新运行 `scripts/setup.py`，也可以直接编辑 `config.json`：

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

| 配置项 | 说明 |
|---|---|
| `quark.cookie` | 夸克会话 Cookie；扫码登录后自动写入 |
| `quark.login_timeout` | 登录二维码有效时长，单位为秒 |
| `plugins.<name>.enabled` | 启用或停用指定内容源 |
| `plugins.wp365.request_timeout` | 365 内容源单次请求超时 |
| `plugins.wp365.retries` | 365 内容源请求最大尝试次数 |
| `save_folder` | 夸克网盘中的目标目录 |
| `download_after_save` | 转存成功后是否自动下载到本地 |
| `local_download_folder` | 自动或手动下载的本地目标目录 |
| `plugin_search_timeout` | 插件搜索或链接解析的进程级超时 |
| `omdb_api_key` | 可选，用于查询影片类型 |

扫码状态保存在 `~/.hermes/cache/films-finder/quark-login/`。运行时 Cookie、二维码状态、虚拟环境和 `config.json` 都不会进入版本控制。

## 媒体库结构

电影按类型和片名整理：

```text
夸克影视/
└── 科幻/
    └── 流浪地球2 (2023)/
        └── The.Wandering.Earth.II.2023.2160p.WEB-DL.mkv
```

剧集使用季度目录：

```text
夸克影视/
└── 剧情/
    └── 剧名/
        └── Season 01/
            └── 剧名 - S01E03.mkv
```

符合 Scene 规范的文件名会被保留，杂乱文件名会被标准化。类型信息优先来自 OMDb，其次使用兼容插件提供的页面信息；无法识别时归入 `其他`。

## 质量评分

评分只用于排序，不保证内容源中的链接始终可用。

| 信号 | 示例 |
|---|---|
| 分辨率 | 2160p/4K 高于 1080p、720p 和 480p |
| 片源 | BluRay/REMUX 高于 WEB-DL、WEBRip、HDTV 和 CAM |
| HDR | Dolby Vision、HDR10+、HDR10、HDR |
| 音频 | Atmos、TrueHD、DTS-HD、DTS、EAC3/DDP、AAC |
| 编码 | H.265/HEVC/x265 高于 H.264/x264 |
| 加分项 | 含字幕和夸克来源会额外加分 |

## 添加内容源插件

复制模板，然后实现 `search()` 和 `extract_link()`：

```bash
cp scripts/plugins/example.py scripts/plugins/my_source.py
```

```python
from plugins import ResourcePlugin, ResourceResult


class Plugin(ResourcePlugin):
    name = "my_source"
    display_name = "我的内容源"
    requires_auth = False
    url = "https://example.com"

    def search(self, query: str, page: int = 1) -> list[ResourceResult]:
        ...

    def extract_link(self, resource: ResourceResult) -> str | None:
        ...
```

在 `config.json` 中启用：

```json
{
  "plugins": {
    "my_source": {
      "enabled": true
    }
  }
}
```

兼容插件最终必须能返回夸克分享链接。`.m3u8` 等纯在线播放地址不能转存到夸克网盘。

## 常见问题

- **出现 `auth_required`**：扫描新生成的二维码，然后运行 `login --confirm`。扫码成功只代表 Cookie 已保存，仍需检查待处理转存的重试结果。
- **出现 `Invalid share URL`**：内容源没能把搜索结果解析成有效夸克链接，可以稍后重搜或选择其他结果。
- **同名冲突 / 错误码 `23008`**：目标位置已有同名内容，或同名转存任务仍在进行。
- **插件超时**：调大 `plugin_search_timeout`，或调整对应插件的请求超时与重试次数。

请只保存你有权访问和存储的内容。
