# Windows 移植验证

目标见 `GOAL_WINDOWS.md`，Windows 构建分支为 `codex/windows-port`。本报告区分本地验证、真正 Windows EXE 验证以及尚未进行的人工验收。

## 本地已完成

- macOS 原有及新增跨平台测试：58 项通过。前端 TypeScript / Vite 构建通过。
- Windows 配置下的 57 项回归通过，独立评估环境没有修改原 `.venv`。
- 四个已有 macOS 应用目录全部文件哈希与移植前一致：标准 4107、逐步 4115、高质量 4123、动态 4127 个文件。
- 使用生成的 12 秒、1280×720、20 fps、带音轨视频，分别通过服务端 RPC 执行真实 RapidOCR、翻译子进程、本地 HTTP 接口、MP4 / SRT 导出。
- 标准模式恢复 3 个完整底部句子，并保留逐字出现时的中间片段；逐步和高质量模式各合并成 3 个完整底部句子；动态模式恢复底部和顶部同时出现的 4 个事件，并完成取消 / 续跑。
- 四种输出均保留 1280×720、12 秒、240 帧和音轨。导出后重新 OCR 确认画面存在真实中文“你好，世界。”，不是只检查 SRT 或数据库。
- 数字与否定句 `We need 12 samples, not 20.` 被完整识别；原视频、既有应用、用户项目和密钥没有上传。
- 模型固定为 RapidOCR 1.4.4 的 PP-OCRv4 ONNX 模型，模型哈希和适配参数见 `config/windows-ocr-manifest.json`。运行时校验模型，识别时不下载资源。

本地证据：`artifacts/windows/local-acceptance-final/acceptance.json`、四模式项目/MP4/SRT/导出截图；应用隔离证据：`artifacts/windows/mac-isolation.json`。这些目录未提交到源码仓库。

## Windows 验证

最终构建：[`37187976562`](https://github.com/IdlePoetry-zero/ai-video-subtitle/actions/runs/37187976562)，2026-10-04 全部成功；发行构建源码提交 `e611b6bb412e84ff4b744efbaf54582ba8e66159`。后续仓库更新仅补充验证报告和开发测试启动脚本，不改变应用运行代码。

运行环境为 GitHub Windows Server 2025 / Windows 10.0.26100 x64。目标发行系统仍为 Windows 11 x64，尚未在日常 Windows 11 电脑上人工逐项操作 GUI。

| 实际 Windows 验收 | 结果 |
| --- | --- |
| 源码回归 | 58 项通过 |
| 包内冻结后端 | 四种模式全部通过 |
| 文字逐步生成、数字与否定、同时多个块 | 完整句子与时间检查通过 |
| 取消 / 续跑及缓存 | 动态模式通过 |
| 中文路径、中文 MP4 / SRT | 四种模式通过 |
| 输出分辨率 / 时长 / 帧数 / 音轨 | 均为 1280×720、12 秒、240 帧、保留音轨 |
| 导出画面重新 OCR | 四种输出均读到“你好，世界。” |
| 便携 EXE | 原生 Windows 界面启动、连接 OCR、截图成功 |
| NSIS 安装器 | 安装到含中文与空格的指定目录成功 |
| 安装版 EXE | 原生 Windows 界面启动、连接 OCR、截图成功 |
| 卸载 | 成功，测试用户数据目录保留 |

冻结后端为 Python 3.12.10；FFmpeg 为随包提供的 7.1；OCR 为 RapidOCR 1.4.4 / ONNX Runtime CPU。包内使用模型校验和 Noto Sans CJK SC 字体。便携版界面截图和动态中文字幕画面已下载并视觉复核。

下载：[安装器、便携 ZIP 与 SHA256SUMS](https://github.com/IdlePoetry-zero/ai-video-subtitle/actions/runs/37187976562/artifacts/11297592527)，[Windows 验证证据](https://github.com/IdlePoetry-zero/ai-video-subtitle/actions/runs/37187976562/artifacts/11297437830)。仓库为私有，需使用具有仓库访问权限的 GitHub 账号。Actions 工件保留 14 天；源码及构建脚本长期保留，可再次构建。

下载工件约 561 MiB，包含 `SubtitleStudioWindows-0.1.0-windows-x64-setup.exe`、`SubtitleStudioWindows-0.1.0-windows-x64.zip` 和 `SHA256SUMS.txt`。外层 GitHub 工件 ZIP 的 SHA-256：

```text
d0e714a3e1b5d88ac5d911db61d6f4b4fc54695d947ce6d97603ca93c0aacca8
```

每个安装器 / 便携 ZIP 的独立 SHA-256 见包内 `SHA256SUMS.txt`。源码仓库未提交视频、安装包、用户项目、设置或密钥。

已修正首次 Windows 冻结测试发现的编码器停滞：FFmpeg 使用独立标准输入、清理继承的冻结 DLL 搜索环境，并在 Windows 临时文件被短暂占用时重试清理。修正后本地四模式导出再次通过；Windows 冻结 EXE 的四模式导出也已通过。

## 验证边界

翻译测试使用本地确定性 HTTP 服务验证兼容接口、冻结子进程和中文输出，不代表真实模型翻译质量。Windows 首版仅支持英语源字幕。

自动启动探针验证渲染器与 OCR 连接，并保存界面截图；它不等同于人工逐项操作 GUI。日常 Windows 11 电脑上的人工体验验收尚未进行。

Windows 首版未签名。复杂移动字幕、特效、微小文字仍需人工校对。固定区域的自动正文判断使用区域下半部，应围绕实际字幕选择合适区域；纯正文可选择“全部文字”布局。Windows 专门保留唯一高置信完整短句，但不会放宽人工排除区域。
