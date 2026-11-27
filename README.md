# 每日歌单 · Daily Playlist Player

一个可自己部署的每日歌单播放器框架：每天按星期轮换一种风格，推一首歌；
能播整首，有歌词，能收藏，有完整歌单。曲库走公开资源（哔哩哔哩、YouTube、
iTunes、LRCLIB），不用任何 API 密钥。

> 这是一个**带示例数据的框架**，不是某个人的歌单。内置只有 10 首常见示例歌，
> 用你自己的歌替换它们即可（见「怎么加歌」）。

## 功能

- **每日一歌**：7 种风格按星期轮换（华语流行、欧美流行、日语流行、抒情慢歌、
  励志热血、深夜抒情、周末轻快），同一天打开永远是同一首。
- **透视黑胶唱片机**：播放时唱片旋转，3D 唱臂摆入；播放/暂停、进度条、时间显示。
- **歌词同步**：有时间戳的歌词逐行高亮，点歌词跳转；只有纯文本歌词时，
  客户端按行长分配时长生成估算时间轴，页面会注明是估算。
- **三种音源**：自动 / 哔哩哔哩 / YouTube，可切换。
  - 哔哩哔哩：服务端走公开 API 解析整首 DASH 音频，浏览器用原生 `<audio>` 播放。
  - YouTube：常驻视频框（切歌不重挂），切歌时让视频框自己跳转到新视频地址；
    另有「伴随声音」开关——在某些 App 内嵌网页里视频框不出声时，
    声音改走本页音频通道。
  - 都没有可用版本时，兜底播 30 秒 iTunes 试听，并明确提示。
- **心选歌单**：点 ♡ 收藏，存在 SQLite 里，重启不丢。
- **完整歌单**：可搜索全部歌曲，点任意一首直接播。
- **横屏模式**：横屏自动切换布局，也有手动按钮。

## 快速开始

只需要 Python 3.8+，**零外部依赖**（只用标准库）。

```bash
git clone https://github.com/duanyuntian37-ship-it/daily-playlist-player.git
cd daily-playlist-player
python3 run.py
```

然后打开 http://127.0.0.1:8000

常用选项：

```bash
python3 run.py --port 8080            # 换端口
python3 run.py --db /path/to/data.db  # 换数据库位置
python3 run.py --refresh-today       # 预热今日推荐（解析音频/视频/歌词进缓存）后退出
python3 run.py --reseed              # 把 data/sample_songs.json 重新写入数据库后退出
```

想每天早上自动预热，用 cron（以每天 7 点为例）：

```cron
0 7 * * * python3 /path/to/daily-playlist-player/run.py --refresh-today
```

## 目录结构

```
daily-playlist-player/
├── run.py                  # 启动入口
├── server/
│   ├── app.py              # HTTP 服务 + API 路由 + 音频代理
│   ├── db.py               # SQLite：建表、播种、每日选歌、心选、缓存
│   ├── bilibili.py         # 哔哩哔哩公开 API：搜索 / 取 cid / 取 DASH 音频
│   ├── youtube.py          # YouTube 公开结果页 + oEmbed：找可嵌入视频
│   ├── lyrics.py           # LRCLIB 公开 API：取歌词
│   └── itunes.py           # iTunes 公开搜索 API：30 秒试听 + 封面
├── client/
│   ├── index.html          # 单页播放器结构
│   ├── styles.css          # 黑胶机、唱臂、7 种风格主题、横屏
│   └── app.js              # 播放、歌词同步、音源切换、心选、歌单
├── data/
│   ├── schema.sql          # 8 张表结构
│   └── sample_songs.json   # 10 首示例歌
├── BASELINE.md             # 本框架的基线核查记录（从线上空间核实而来）
├── LICENSE                 # MIT
└── .gitignore
```

首次启动时，程序会在 `data/playlist.db` 建库，并把示例歌单写进去；
数据库文件由 `.gitignore` 排除，不会进仓库。

## 怎么加歌

编辑 `data/sample_songs.json`，按这个格式加一行：

```json
{"id": "s11", "title": "歌名", "artist": "歌手", "lang": "zh",
 "styles": ["cn-pop", "night"], "duration_sec": 240}
```

- `id`：唯一编号，别重复。
- `lang`：`zh` / `en` / `ja` 等，随便写，仅作展示。
- `styles`：从 7 种风格里选 1 个或多个——
  `cn-pop` 华语流行、`en-pop` 欧美流行、`jp-pop` 日语流行、
  `ballad` 抒情慢歌、`anthem` 励志热血、`night` 深夜抒情、`weekend` 周末轻快。
  每天的风格由星期决定，歌只有进了当天风格才会被推。
- `duration_sec`：歌曲大概时长（秒），用来匹配哔哩哔哩视频和估算歌词时间轴，
  不必精确。

加完后执行一次：

```bash
python3 run.py --reseed
```

再启动就能看到新歌。也可以直接删掉 `data/playlist.db` 再启动，
程序会重新建库播种（心选记录会丢，所以推荐用 `--reseed`）。

## 曲库怎么工作（公开资源，没有官方授权曲库）

这个项目没有接任何音乐平台的官方 API，也没有 API 密钥。
所有曲库能力都是运行时查公开端点解析出来的：

| 来源 | 用途 | 怎么查 |
| --- | --- | --- |
| 哔哩哔哩 | 整首音频 | 公开接口：`search/all/v2` 搜视频 → `player/pagelist` 取 cid → `player/playurl`（fnval=16）取 DASH 音频地址；服务端带 Referer 代理给浏览器播 |
| YouTube | 视频画面 | 公开结果页 `results?search_query=` 里找 videoId，再用 oEmbed 校验可嵌入；视频框常驻，切歌只换地址 |
| iTunes Search | 30 秒试听 + 封面 | 公开搜索接口 `itunes.apple.com/search`，无 key |
| LRCLIB | 歌词 | 公开接口 `lrclib.net/api/search`，无 key |

这意味着：

- **能解析不等于有授权**。播的是各平台公开页面上的内容，遵守各平台规则；
  不要把解析到的音频文件下载下来再分发，本项目也不存音频文件（只缓存地址）。
- **随时可能失效**。搜不到、限流、风控、页面改版都会导致某首歌解析失败；
  失败时播放器会按「哔哩哔哩 → YouTube → 30 秒试听」的顺序降级，
  并在页面上如实提示，不会假装播了整首。
- **YouTube 在中国大陆普通网络下通常打不开**，这是网络限制，不是 bug；
  有条件换网络再试，或用哔哩哔哩通道。
- **YouTube 音频提取走不通**：服务端直接抓 YouTube 音频会被机器人验证拦住，
  所以 YouTube 通道只播视频画面，声音靠视频本身或「伴随声音」开关。

## 每日选歌逻辑

- 风格 = 当天星期几（周一华语流行 …… 周日周末轻快）。
- 在该风格的歌里，用 `sha256(日期:风格)` 取一首，所以同一天结果固定，
  不需要定时任务也能每天换歌。
- `run.py --refresh-today` 只是提前把今天那首的音频、视频、歌词解析好
  写进缓存，打开更快；不跑也不影响选歌。

## 数据库

SQLite，8 张表，见 `data/schema.sql`：

- `songs`：歌单目录（id、歌名、歌手、语言、风格、时长）。
- `daily_picks`：每天的推荐记录（日期唯一）。
- `likes`：心选（歌 id + 收藏时间）。
- `audio_cache`：哔哩哔哩解析结果（bvid、cid、音频地址，1 小时过期）。
- `lyrics_cache`：歌词（带时间戳的 JSON + 纯文本，7 天过期）。
- `video_cache` / `youtube_cache`：视频解析结果（7 天过期）。
- `track_cache`：iTunes 试听地址和封面（7 天过期）。

## 已知限制

- 本框架**未在目标部署环境做端到端实测**：在本机做了语法检查、
  本地启动冒烟和 1 首歌的实机解析冒烟（2026-11-27 当天推荐，
  Bilibili 音频、YouTube 视频、LRCLIB 歌词、iTunes 试听均解析成功），
  但其余 9 首没逐首验证，浏览器播放和手机端也没实测。
  公开端点随时可能变，部署后以你那边实际跑通为准，
  报错信息会写进服务端日志和页面状态栏。
- YouTube 常驻视频框 + `location.replace` 切歌的修法，在原线上空间
  是针对手机 App 内嵌网页的专项修复，手机实测当时还没确认；
  在普通桌面浏览器里切歌是正常的。
- 歌词估算时间轴只是按行长分配，仅供参考，页面会注明。
- 服务端是单进程标准库 HTTP 服务，适合个人、小范围使用，
  不是为高并发准备的；要对外服务请前面加反向代理。

## 和原线上版的区别

见 `BASELINE.md`。简单说：原版是托管在 Muse 运行环境里的
TypeScript + React 全栈应用（依赖平台 SDK 和托管定时任务）；
本框架是把它抽出来的便携版——Python 标准库后端 + 原生前端，
去掉平台依赖，换掉个人歌单，只留示例数据和框架逻辑。

## 许可证

MIT，见 `LICENSE`。
