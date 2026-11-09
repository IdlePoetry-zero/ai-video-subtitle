# 批量字幕工具（tools/batch）

不用打开桌面窗口，直接用命令行把一批视频跑成中文字幕成片。

工具通过和桌面应用完全相同的 JSONL worker 协议驱动 `worker/server.py`，
所以识别、翻译、渲染行为与界面里一致，只是把"框选 → 点按钮"换成了参数。

```
probe.py     抽样 OCR，判断字幕是固定区域还是任意位置，给出建议模式与 ROI
scan.py      建项目并识别（standard 固定区域 / dynamic 全画面，支持分片并行）
clean.py     去噪、合并重复、闭合间隙、过滤水印、扩框（对应界面里的校对前置工作）
translate.py 调翻译服务（DeepSeek / 任意 OpenAI 兼容接口 / Ollama）
export.py    导出 MP4（可选同时导出 SRT）
qa.py        抽检成片：字幕是否真的换成中文、随机时间点是否残留英文
pipeline.py  把上面六步串起来，一条命令跑完
```

## 准备

```powershell
npm ci
npm run setup          # 建 .venv、装 OCR 依赖、下载中文字体
```

翻译密钥按优先级取：`--api-key` → `SUBTITLE_API_KEY` / `OPENAI_API_KEY` → `runtime/.apikey`。

## 一条命令跑完

```powershell
.venv\Scripts\python.exe tools\batch\pipeline.py "D:\videos\my-video.mp4"
```

默认行为：

1. 抽样 8 个时间点判断模式（字幕固定在下方/上方 → `standard`，位置乱跑 → `dynamic`）；
2. `standard` 用建议 ROI，`dynamic` 按片长自动分片（≤15 分钟 2 片，≤40 分钟 3 片，更长 4 片）；
3. 识别 → 清洗（含水印过滤和扩框）→ 翻译 → 导出到**视频同目录**，文件名 `原名_中文版.mp4`；
4. 跑质检并打印中文覆盖率。

常用参数：

| 参数 | 说明 |
|---|---|
| `--mode standard\|dynamic` | 覆盖自动判断 |
| `--roi 0.05,0.88,0.90,0.11` | 标准模式区域（归一化 x,y,w,h） |
| `--shards 4` | 动态模式并行分片数（1–8） |
| `--interval 0.4` | 动态模式扫描间隔（秒，0.15–2） |
| `--output-dir D:\out` | 成品目录 |
| `--start / --end` | 只处理某个时间段 |
| `--skip-qa` | 跳过质检 |

## 分步使用

```powershell
# 1. 探测：字幕在哪、用什么模式
.venv\Scripts\python.exe tools\batch\probe.py "D:\videos\a.mp4" --samples 10

# 2. 识别
.venv\Scripts\python.exe tools\batch\scan.py "D:\videos\a.mp4" --name a --mode dynamic --shards 3 --interval 0.4

# 3. 清洗（--dry-run 先看效果）
.venv\Scripts\python.exe tools\batch\clean.py a --ignore-watermarks --expand-boxes

# 4. 翻译
.venv\Scripts\python.exe tools\batch\translate.py a

# 5. 导出
.venv\Scripts\python.exe tools\batch\export.py a --output "D:\out\a_中文版.mp4" --srt "D:\out\a_中文版.srt"

# 6. 质检
.venv\Scripts\python.exe tools\batch\qa.py a --export "D:\out\a_中文版.mp4"
```

项目默认建在 `runtime/projects/<name>`，用 `--workdir` 改到别处。

## 两个关键参数怎么选

**模式**：字幕位置固定（黑边里的对白、游戏对话框）用 `standard`，它只 OCR 一条带，
速度通常是实时的 1–2 倍；字幕会在画面任意位置出现（弹幕、竖排、卡片）用 `dynamic`，
它跟踪每个文字对象的生命周期，慢 2–4 倍但不会漏。

**分片 `n` 与间隔 `m`**（动态模式）：

- `n` 把时间轴切成 n 段并行跑，近似线性加速；每片占一个 CPU 核，建议 2–4；
- `m` 是整帧扫描周期，也节流"对已发现对象的重复读取"。默认 0.4 秒；片源字幕停留
  3 秒以上时放宽到 0.8 能再快一倍；
- 实测：10 分钟 1080p30 素材，`n=1, m=0.4` 27 分钟 → `n=2, m=0.4` 7.1 分钟（3.8×）。

## 已知限制

- 只支持英语源字幕（OCR 模型随包提供的是英文/中文识别）；
- 白字压浅色背景、时长不足 0.3 秒的闪句可能漏识别；
- `dynamic` 模式会把画面里的水印、UI 标签也当成文字对象，用 `clean.py --ignore-watermarks` 过滤；
- 翻译默认 `deepseek-flash`，如需换服务改 `scan.py --api-base/--api-model` 或项目的 `translation` 配置。
