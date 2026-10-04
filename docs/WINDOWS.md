# Windows 版本

目标系统：Windows 11 x64。首版为未签名的测试发行版。

## 安装

使用 `SubtitleStudioWindows-0.1.0-windows-x64-setup.exe` 安装，或解压便携 ZIP 后运行 `SubtitleStudioWindows.exe`。便携版仍将项目和设置写入 `%APPDATA%\SubtitleStudioWindows`，不要求安装目录可写。卸载保留该目录，避免删除用户项目。

应用随包提供本地 OCR、Python 处理组件、FFmpeg、Noto 中文字体，无需另行安装。模型校验失败会提示重新安装，不会在识别期间下载模型。

Windows 首版支持英语源字幕。可使用标准、逐步生成、高质量固定区域和全画面多区域四种模式。Windows OCR 与 Apple Vision 使用不同模型，质量需要分别验证；原 macOS 成品继续可用。

## 翻译

在设置中填写兼容 OpenAI 的 API 地址、模型名称、密钥，或连接已运行的本地 Ollama/兼容接口。本应用不会下载翻译大模型。OCR 和视频处理在本机执行，翻译接口收到字幕文字及上下文；视觉复核另有单独授权界面。

密钥由 Electron safeStorage 使用 Windows 系统加密。系统安全存储不可用时只在当前运行保留。密钥不写入项目和安装包。macOS 的加密设置不能直接复制到 Windows，需要重新配置。

## 使用与限制

先导入视频，选择识别模式并试处理短片段。固定区域模式确认区域；全画面模式检查多个字幕块、排除水印、确认弱证据后翻译。校对结果后导出新文件，程序不会覆盖原视频或既有输出。

全画面模式针对“位置任意、单段出现后静止、多个块同时存在、文字逐步生成”。持续移动、旋转、复杂文字特效仍可能需要人工校对。遮盖使用背景色；没有实现无痕修复。SRT 不携带空间位置。

## 开发与构建

在 Windows x64 安装 Node.js 22 和 Python 3.12 后运行 `npm ci`、`npm run setup`、`npm run package:windows`。最终用户不需要这些开发工具。产物在独立的 `release-windows`，不覆盖 macOS 发布目录。

GitHub Actions 工作流 `Windows build and acceptance` 在 Windows 构建源代码、冻结后端并验证实际 EXE，生成安装器和便携包。自动验收使用生成的无敏感视频和本地 HTTP 翻译测试接口；这验证接口与导出流程，不代表真实模型翻译质量或人工 GUI 验收。具体执行结果见 Windows 验证报告。

初版没有购买或使用代码签名证书，Windows 可能显示发行者未知。正式发行签名需要另外配置证书。第三方许可、模型哈希、FFmpeg 构建信息随包提供；再分发时保留它们。
