# BASELINE.md — 基线核查记录

本文件记录这个框架包是从哪里来的、核实了什么、改了什么、没核实什么。
按「先验基线再移植」的要求写：不凭摘要假设结构，先查线上空间的真实结构。

## 核查方式

- 工具：`artifact.inspect`（repair_authorized=false，只诊断，不修复、不改线上空间）
- 对象：线上空间 `mei-ri-ge-dan-tui-jian-2`（每日歌单推荐）
- inspection_id：`8ce7826a-99a4-4f10-a00d-b9ae6913a254`
- 时间：2026-11-27
- 结论：诊断已提交（diagnosis_submitted），当前构建 `bce8f9fc` 可正常渲染。

## 线上空间实际包含什么（核实到的基线）

- 类型：全栈 TypeScript 应用（Bun + Drizzle SQLite），托管在 Muse 运行环境。
- 服务端：`server/src/actions.ts`（1550+ 行）、`server/src/schema.ts`、
  `server/src/catalog.ts`（59,427 字节 / 3126+ 行）。
- 前端：`client/src/App.tsx`（88 KB）、`client/src/api.ts`、7 张风格背景图。
- 数据库（隔离副本实测）：songs 400 行、feedback 5 行、daily_picks 2 行、
  lyrics_cache 28、track_cache 21、video_cache 20、audio_cache 15、youtube_cache 16。
- 数据模型：8 张表（songs、feedback、track_cache、lyrics_cache、video_cache、
  audio_cache、youtube_cache、daily_picks），migration 0001–0006。
- 对外接口（10 个 action）：getToday、nextSong、playSong、getFullAudio、
  getYoutube、getLyrics、getLibrary、setFeedback、seedCatalog、refreshDailyPick。
- 曲库来源（DATA-PLAN.md 有 2026-11-26 的测试记录）：Bilibili
  search/playurl、YouTube 结果页抓取 + oEmbed、iTunes Search、LRCLIB——
  都是运行时查公开端点解析，不是官方授权曲库 API；YouTube 音频提取
  已确认走不通（机器人验证墙），YouTube 在中国大陆普通网络下打不开。
- 关键行为（多轮手机实测修出来的）：Bilibili 整首音频服务端取、
  先播 30 秒试听再无缝换整首；YouTube 常驻视频框、切歌用
  `contentWindow.location.replace` 而不是改 src 属性；伴随声音通道；
  纯文本歌词用客户端估算时间轴并注明是估算；无歌词显示「暂无歌词」；
  无可用版本兜底 30 秒试听。

## 冲突与解决

**冲突**：任务要求「可移植，不依赖 Muse 的托管运行环境」，但核查发现
线上代码耦合了 Hatch 运行时——`package.json` 把 `@hatch/space-sdk`
pin 在 `file:/opt/hatch/skills/spaces/ts-runtime/dist/space-sdk.tgz`
（本地路径，别人 clone 下来装不上），服务端用 `ctx.db / ctx.blobs /
ctx.inference`，`space.json` 里还有托管 cron（`mei-ri-ge-dan-daily-pick`）。
直接推原树既跑不起来，也会泄露个人数据。

**解决**：不推原树，做剥离版导出，并抽一个便携适配器——

- 后端改写为 Python 3.8+ 标准库（http.server + sqlite3 + urllib），零外部依赖；
- 前端改写为原生 HTML/CSS/JS 单页（无构建步骤），保留原版的全部功能点；
- 托管 cron 改为「按日期确定性选歌」（不需要定时任务）+ `--refresh-today`
  预热命令（可用系统 cron 调度）；
- 线上空间本身**没有动**，它的 Bilibili / YouTube 逻辑、数据库和缓存都原样保留。

## 偏差清单（框架与原版的不同之处）

| 项目 | 原版 | 本框架 |
| --- | --- | --- |
| 后端语言 | TypeScript（Bun） | Python 3.8+ 标准库 |
| 前端 | React（App.tsx 88 KB） | 原生 HTML/CSS/JS |
| 数据库访问 | Drizzle + ctx.db | sqlite3 直连，同一套 8 张表 |
| 喜欢记录表 | `feedback` | 改名 `likes`（作用相同） |
| 音频存储 | 服务端下载成 blob 存 blobs/ | 不存音频文件；只缓存解析出的地址，播时经 `/api/audio-stream` 代理 |
| 封面 | 存 blob | 用 iTunes artwork URL |
| 每日选歌 | 托管 cron 预热 + action | 按日期确定性选歌 + `--refresh-today` 预热 |
| 歌单数据 | 400 首个人歌单 | 10 首示例歌（见下） |

## 排除清单（明确没放进包里的东西）

- 400 首个人歌单数据：`catalog.ts`（388 首酷狗歌单 001 + 12 首站外推荐）
  和 songs 表 400 行，**一律没放**。示例歌是新挑的 10 首常见歌，
  逐一核对过用户歌单文件：这 10 首的歌名在用户歌单里**一次都没出现**，
  不存在把个人歌单内容换个形式带进来的情况。
- 喜欢记录：feedback 5 行没放；`likes` 表是空的。
- 全部缓存行：lyrics/track/video/audio/youtube 各缓存表没放。
- 运行时文件：`app.db`、`app.db-shm`、`app.db-wal`、`blobs/`（已下载的
  封面/音频）、`audits/`、`node_modules/`、`dist/`、`.space-build*`。
- 任何能定位到具体个人的信息（姓名、学校、地区、联系方式、账号）
  一律不含。包里也没有 API 密钥——只用公开接口。
- 部分歌名在原版里有录屏截断 / OCR 损坏（如标题带未闭合括号和 `...`），
  示例歌全部用完整无损坏的歌名。

## 目标仓库

`daily-playlist-player`：用户 2026-11-27 已手动新建的公开空仓库
（main 分支）。README 随代码一起推；仓库简介需用户自己在 GitHub
仓库页 About 里填（Muse 这边没有改仓库简介的接口）。

## 未核实的部分（老实标注）

1. **未在目标部署环境做端到端实测**。本机（Ubuntu 24.04，Python 3.12、
   Node 24）做了：全部 `.py` 文件 `py_compile`、`app.js` 的 `node --check`、
   JSON 校验、本地启动冒烟（首页 200、`/api/today`、`/api/library` 正常返回），
   以及 `--refresh-today` 实机解析冒烟（2026-11-27 当天推荐 Viva La Vida）：
   Bilibili 解析出 DASH 音频地址、YouTube 解析出官方视频且 oEmbed 校验可嵌入、
   LRCLIB 返回带时间戳歌词、iTunes 返回试听和封面地址，四个公开端点均 HTTP 200。
   但这只是 1 首歌的解析冒烟：其余 9 首没逐首验证，浏览器里播代理音频流、
   手机 App 内嵌网页里的 YouTube 框都没实测。部署后以实际跑通为准。
2. **YouTube 第 13 轮修复（常驻框 + location.replace 切歌）在手机 App
   内嵌网页里的实测当时还没确认**；本框架按同一做法实现，
   桌面浏览器里切歌正常，手机端需实测。
3. **没有对原版做全文件密钥扫描**。检查只覆盖了导出包本身
   （见下「交付前检查」）；原版 `actions.ts`、`App.tsx` 的全文件扫描
   不在本次核查范围内。但导出包是重写的，不含原版文件，
   且包内已做全文密钥/个人信息 grep。
4. **示例歌的解析成功率未逐首验证**。10 首都是哔哩哔哩和 YouTube 上
   极常见的歌，但没逐首跑过解析；某首解析失败时播放器会按
   哔哩哔哩 → YouTube → 30 秒试听降级并提示。

## 交付前检查

- 全包 grep 查个人信息与密钥模式——零命中（检查命令与结果见打包记录）。
- 全包 grep 用户歌单内容：示例歌名与用户歌单文件无重叠（逐首核对过）。
- 语法检查：`python3 -m py_compile` 全部 `.py` 通过；
  `node --check client/app.js` 通过；两个 JSON 文件校验通过。
- 本地冒烟：`python3 run.py` 能启动，首页 200，`/api/today` 返回
  当天推荐（2026-11-27 周五，风格「励志热血」，Viva La Vida），
  `/api/library` 返回 10 首；`--reseed` 写入 10 首；`--refresh-today`
  实机解析：Bilibili 音频、YouTube 官方视频、LRCLIB 同步歌词、iTunes
  试听/封面全部 ok，四张缓存表均有 1 行。video_cache 由 YouTube
  解析时同步写入。
