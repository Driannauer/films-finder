# films-finder

`films-finder` 是一个面向个人媒体库的影视资源查找与整理工具，也可以作为 [Hermes Agent](https://github.com/nousresearch/hermes-agent) skill 使用。它通过插件搜索影视资源，按资源质量自动评分，并支持将夸克网盘资源转存到指定目录，再整理成适合 Infuse、Plex、Jellyfin 等媒体播放器识别的目录结构。

本项目适合用于个人影视库管理、资源检索和自动化整理。请在使用时遵守所在地法律法规以及相关平台的服务条款。

## 主要功能

- 多来源搜索：通过 `scripts/plugins/` 下的插件接入不同资源站。
- 质量评分：按分辨率、片源、HDR、音频、编码、字幕、网盘类型等维度自动排序。
- 夸克网盘转存：支持直接转存夸克分享链接，也支持从搜索结果中选择指定条目转存。
- 扫码登录：支持终端登录，也支持生成可由 Hermes 发送的二维码图片。
- 媒体库整理：可将已保存的文件整理为电影或剧集目录结构。
- 类型分类：支持通过 OMDB API 或资源页信息识别影片类型，并缓存识别结果。
- 本地同步：可在转存成功后把夸克文件同步下载到本地目录。

## 项目结构

```text
films-finder/
├── scripts/
│   ├── cinema.py          # 命令行入口
│   ├── setup.py           # 交互式配置向导
│   ├── quark.py           # 夸克网盘相关操作
│   ├── library.py         # 媒体库整理逻辑
│   └── plugins/           # 内容源插件
├── config.example.json    # 配置示例
├── requirements.txt       # Python 依赖
├── SKILL.md               # Hermes skill 描述
└── README.md
```

## 环境要求

- Python 3.10 或更高版本。
- 可访问目标内容源和夸克网盘。
- 如需作为 Hermes skill 使用，请先安装并配置 Hermes Agent。
- 如需使用 OMDB 类型分类，请准备一个 OMDB API Key。

## 快速开始

作为普通 Python 工具使用：

```bash
git clone https://github.com/<your-github-username>/films-finder.git
cd films-finder
pip install -r requirements.txt
python scripts/setup.py
```

作为 Hermes skill 使用：

```bash
git clone https://github.com/<your-github-username>/films-finder.git ~/.hermes/skills/films-finder
pip install -r ~/.hermes/skills/films-finder/requirements.txt
python ~/.hermes/skills/films-finder/scripts/setup.py
```

配置向导会引导你完成：

1. 夸克网盘登录或 Cookie 配置。
2. 内容源插件启用或禁用。
3. OMDB API 或资源页抓取的类型分类设置。
4. 夸克网盘保存目录设置。
5. 转存后是否同步下载到本地。

## 常用命令

```bash
python scripts/cinema.py plugins
python scripts/cinema.py search "流浪地球"
python scripts/cinema.py auto "星际穿越"
python scripts/cinema.py save https://pan.quark.cn/s/xxxx
python scripts/cinema.py save --index 1
python scripts/cinema.py save --index 1 "流浪地球"
python scripts/cinema.py save --index 1 "流浪地球" --dry-run
python scripts/cinema.py login
python scripts/cinema.py login --qr
python scripts/cinema.py login --confirm
python scripts/cinema.py download <fid> --dir /root/films
python scripts/cinema.py organize <fid> "电影名称" --type movie
python scripts/cinema.py organize <fid> "剧集名称" --type tv --season 1 --episode 1
python scripts/setup.py
```

命令说明：

- `plugins`：查看当前可用插件。
- `search <query>`：搜索影视资源，并以 Markdown 表格输出前 20 条结果。
- `auto <query>`：搜索并自动选择评分最高的夸克资源进行转存和整理。
- `save <url>`：直接转存夸克分享链接。
- `save --index N`：转存最近一次搜索结果中的第 N 条。
- `save --index N <query>`：重新搜索后转存第 N 条结果。
- `save --dry-run`：只解析并展示将要保存的资源，不执行转存。
- `download <fid>`：把指定夸克文件或文件夹 ID 下载到本地。
- `organize`：将已保存的文件整理为电影或剧集目录。
- `login`、`login --qr`、`login --confirm`：完成夸克登录和 Cookie 保存。

## 配置说明

首次运行 `python scripts/setup.py` 后会生成 `config.json`。也可以参考 `config.example.json` 手动配置：

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
    }
  },
  "save_folder": "夸克影视",
  "download_after_save": false,
  "local_download_folder": "/root/films",
  "skip_ad_images": true,
  "plugin_search_timeout": 20,
  "omdb_api_key": ""
}
```

字段说明：

- `quark.cookie`：夸克网盘登录 Cookie。可通过扫码登录自动写入。
- `quark.login_timeout`：扫码登录等待时间，单位为秒。
- `plugins`：内容源插件配置。每个插件可单独启用、禁用或配置超时时间。
- `save_folder`：资源转存到夸克网盘后的目标目录。
- `download_after_save`：转存成功后是否自动同步下载到本地。
- `local_download_folder`：本地下载目录。
- `plugin_search_timeout`：单个插件搜索超时时间，单位为秒。
- `omdb_api_key`：OMDB API Key。留空时会尝试使用资源页信息或跳过精准分类。

不要把包含真实 Cookie、账号、密码或私有 API Key 的 `config.json` 提交到公开仓库。

## 夸克登录

终端登录：

```bash
python scripts/cinema.py login
```

Hermes 聊天场景可使用二维码登录：

```bash
python scripts/cinema.py login --qr
```

命令会生成二维码图片并输出 `MEDIA:/...png` 路径。用夸克 App 扫码后执行：

```bash
python scripts/cinema.py login --confirm
```

如果转存时检测到 Cookie 缺失或失效，程序会提示重新扫码，并在确认登录后重试之前挂起的转存任务。

也可以手动获取 Cookie：登录 [pan.quark.cn](https://pan.quark.cn)，打开浏览器开发者工具，进入 Network 面板，复制请求头中的 `Cookie` 值并填入 `config.json` 的 `quark.cookie`。

## 搜索与转存流程

推荐流程：

```bash
python scripts/cinema.py search "影片名称"
python scripts/cinema.py save --index 1
```

`search` 会缓存最近一次搜索结果，`save --index N` 会从缓存中选择第 N 条资源并提取真实夸克分享链接。如果想避免误转存，可以先执行：

```bash
python scripts/cinema.py save --index 1 --dry-run
```

确认无误后再去掉 `--dry-run`。

## 媒体库整理

电影目录示例：

```text
夸克影视/
├── 动作/
│   └── 疾速追杀 (2014)/
│       └── John.Wick.2014.1080p.BluRay.x265.mkv
├── 剧情/
│   └── 奥本海默 (2023)/
│       └── Oppenheimer.2023.2160p.WEB-DL.mkv
└── 其他/
    └── 未识别影片 (2024)/
```

命名规则尽量兼容常见媒体播放器：

- 电影：`Movie Name (Year).ext`
- 剧集：`Show Name/Season 01/Show Name - S01E01.ext`

当源文件已经是常见发布组命名格式时，程序会尽量保留原文件名，只整理外层目录。

## 质量评分

搜索结果会根据标题和资源信息自动打分，分数越高越靠前。

| 因素 | 高分示例 | 低分示例 |
| --- | --- | --- |
| 分辨率 | 2160p、4K、UHD | 480p |
| 片源 | BluRay、REMUX、WEB-DL | CAM |
| HDR | Dolby Vision、HDR10+、HDR | 无 HDR |
| 音频 | Atmos、TrueHD、DTS-HD | AAC |
| 编码 | H.265、HEVC、x265 | H.264 |
| 字幕 | 包含中文字幕或双语字幕 | 无字幕信息 |
| 平台 | 夸克网盘 | 其他网盘 |

评分只用于排序参考，最终保存前建议结合文件大小、片源和标题自行确认。

## 添加内容源插件

在 `scripts/plugins/` 下新增一个 Python 文件，例如：

```bash
cp scripts/plugins/example.py scripts/plugins/your_site.py
```

插件需要继承 `ResourcePlugin`，并实现 `search` 和 `extract_link`：

```python
from plugins import ResourcePlugin, ResourceResult


class Plugin(ResourcePlugin):
    name = "your_site"
    display_name = "Your Site Name"
    requires_auth = False
    url = "https://your-site.example"

    def search(self, query: str, page: int = 1) -> list[ResourceResult]:
        ...

    def extract_link(self, resource: ResourceResult) -> str | None:
        ...
```

然后在 `config.json` 中启用：

```json
{
  "plugins": {
    "your_site": {
      "enabled": true
    }
  }
}
```

也可以重新运行 `python scripts/setup.py`，让配置向导重新发现插件。

## 常见问题

### 没有搜索结果

先运行 `python scripts/cinema.py plugins`，确认至少有一个插件已启用。再检查网络访问、插件配置和关键词是否正确。

### 转存失败或提示需要登录

夸克 Cookie 可能为空或已失效。运行 `python scripts/cinema.py login` 或二维码登录流程重新保存 Cookie。

### `save --index` 找不到缓存

需要先执行一次 `search`，或者直接使用：

```bash
python scripts/cinema.py save --index 1 "影片名称"
```

### 不想自动下载到本地

将 `config.json` 中的 `download_after_save` 设置为 `false`。

## 许可证

MIT

## 原仓库

本项目基于原仓库 [DavidBB-L/cinema-manager](https://github.com/DavidBB-L/cinema-manager) 改写与整理。
