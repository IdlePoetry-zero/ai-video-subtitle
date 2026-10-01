# 实施与验证记录

第一版按 DESIGN.md 及用户追加约束实现并实际验收：不安装具体模型，默认明确标注 mock 翻译，同时支持 API 与已有本地模型服务。真实 OCR、时间轴、保存、取消恢复、渲染与桌面播放均已验证。详细证据见 `docs/VALIDATION.md`。

## 里程碑

- [x] M1：生成 60 秒 720p 硬字幕样本与 VFR 样本；原生 OCR 实际恢复 13 个事件。最终召回 100%、误增 0、CER 0.2907%、所有起止边界在 200 ms 内。
- [x] M2：Electron/React 工作台连接 Python worker。导入、拖动区域、识别、校对、自动保存与重开真实运行。
- [x] M3：API 与本地 Ollama 协议适配、上下文与术语、返回校验、局部重试、人工译文保护。协议实测通过；依用户要求用 mock 验证工作流，真实模型质量留待已有服务配置后验证。
- [x] M4：实际生成并播放短片、中文 SRT 与整片 MP4。检查中文字体、两行、遮盖、空白区间及样本音视频同步。
- [x] M5：取消恢复、非法修改、视频迁移与指纹、中文路径、桌面操作、类型检查、13 项测试、生产构建及本地应用包真实启动通过。交付 README、截图、样例与验收报告。

## 技术选择与修复

macOS arm64，Node 24.13.0，Python 3.12.14。依赖安装在项目内 `.venv` 和 `node_modules`。当前机器原有系统 Python 3.9.6 不用于 worker。

原生 Apple Vision 使用系统已有 OCR，无独立模型安装。Swift 编译受当前 SDK 重复 SwiftBridging 模块影响，改用 Objective-C JSONL helper 调用同一能力。英语已实际验证，系统支持的其他语言在界面标为待验证。

PyAV 与 OpenCV 内置 FFmpeg 同时加载产生 Objective-C 类冲突，改用 Pillow/NumPy 裁剪与变化分析，PyAV 保留 PTS 解码。FFmpeg 由 imageio-ffmpeg 提供，确认支持 libass；元信息使用 PyAV 的 FFmpeg API，未安装独立 FFprobe。

真实测试修复了低对比背景 OCR 幻觉、FFmpeg 初始 N/A 进度、播放 byte Range 导致的跳转失败、未保存编辑与异步预览切换、失败导入破坏当前项目、默认 asar 不能执行 Python worker 等问题。输出始终保留原视频。

开发与应用包均实际启动。包使用展开资源目录，本机运行约 535 MiB；未签名、公证，也不承诺当前虚拟环境可直接移植到其他电脑。

## 最终证据

- 最终桌面验收：`artifacts/desktop-1790843664528/`。
- OCR 独立评估：`artifacts/ocr-evaluation.json`。
- MP4 像素与音频检查：最终验收目录下 `media-check/result.json` 和 `contact-sheet.jpg`。
- 本地应用包：`release/SubtitleStudio-darwin-arm64/SubtitleStudio.app`。
- 构建、测试、桌面、打包与审计日志均在 `artifacts/`，详见验收报告。

用户真实视频和真实模型质量尚未验证；不将生成样本指标或 mock 译文扩大为实际素材效果承诺。
