# 字幕工作室

macOS 桌面应用：从视频画面识别外文硬字幕，恢复时间轴，翻译、校对，导出中文 SRT 或带中文字幕的 MP4。

视频、OCR、编辑、保存和导出均使用真实实现。按照当前用户要求，不下载或安装独立模型，默认使用明确标注的模拟翻译。OCR 使用 macOS 自带 Apple Vision。真实翻译可连接云端 OpenAI 兼容 API、LM Studio 等本地兼容 API，或已有 Ollama 服务。

## 逐步出现字幕扩展版

当前扩展分支 `codex/progressive-subtitles` 增加可选的“扩展模式 · 逐步出现字幕”。`main` 与原标准应用包保留。新建和旧项目默认标准模式，原标准识别算法保持不变。

在“字幕识别模式”切换到扩展模式，适用于固定区域内逐字、逐词增加的清晰字幕。应用合并文字增长过程、恢复整句并翻译一次；提供首次出现、完整候选与消失时间，以及逐步 OCR 证据。两种模式的结果、检查点和人工校对独立保存，可来回切换。

“中文显示时机”可选从首次出现显示整句，或等待完整原文后显示整句；原文遮盖按原文出现时间计算。手工修改的时间不会被设置切换覆盖。本次不实现中文逐字动画、任意位置多气泡或特效文字识别；不安装独立模型，翻译默认明确的 mock。

```sh
.venv/bin/python tests/generate_progressive_fixture.py
npm run test:progressive
.venv/bin/python tests/verify_progressive_media.py
```

Goal 提示词见 [GOAL_PROGRESSIVE.md](GOAL_PROGRESSIVE.md)，实现与验收见 [扩展验收报告](docs/PROGRESSIVE_VALIDATION.md)。

## 运行

当前项目依赖已经准备好：

```sh
npm start
```

开发时：

```sh
npm run dev
```

重新准备环境和构建：

```sh
npm ci
npm run setup
npm run build
npm start
```

需要 macOS 12 或更高版本、Node 22.12 或更高版本、Python 3.12 及 Xcode Command Line Tools 的 clang。当前实测设备为 macOS arm64，Node 24.13.0、Python 3.12.14。setup 会建立项目内 `.venv`、安装 `requirements.lock` 中的 Python 库并编译原生 OCR helper，不安装独立模型。没有单独安装 FFmpeg 时使用 imageio-ffmpeg 中的 arm64 二进制；视频元信息与时间戳通过 PyAV 的 FFmpeg API 读取。

可通过 `STUDIO_SETUP_PYTHON` 指定创建虚拟环境的 Python，通过 `STUDIO_PYTHON` 指定运行 worker 的解释器，通过 `FFMPEG_BINARY` 指定 FFmpeg。当前 setup 优先使用本机已有的 Codex Python 运行时；迁移到其他电脑应先提供 Python 3.12，再重新 setup。

## 使用

1. 导入或拖入完整视频。项目默认保存在项目目录的 `projects/` 下，原视频不会被覆盖。
2. 使用“自动推荐区域”或“框选字幕区域”。框内拖动移动，右下角拖动缩放，也可输入百分比。点击“保存区域”确认。
3. 选择输入语言。英语已经经过测试；其他语言仅表示系统支持，效果尚未验证。
4. 设置开始与结束时间，点击“识别片段”试处理；或点击“识别全片 / 继续”。字幕位置变化时可添加不重叠的分段区域。
5. 点击“翻译字幕”。默认模式是模拟；设置中可以连接真实服务。
6. 点击字幕跳到对应片段，可循环播放并核对原始截图。编辑原文、中文或时间会延迟自动保存，也可立即点“保存修改”；“撤销编辑”恢复前一版本。
7. “字幕检查阈值”可调整阅读速度、字数和行数；“重译这一条”保留人工译文；修改原文会将译文标为待更新。可合并、拆分字幕，或统一替换译文术语。
8. “生成效果预览”会真实渲染短片，与整片导出使用相同字体、遮盖和排版。普通播放上的叠层用于即时编辑，最终效果以渲染预览为准。
9. 导出中文 SRT 或 MP4。独立 SRT 不会遮盖视频已有的硬字幕；MP4 默认用不透明背景条覆盖外文。也可选择保留外文、把中文放在上方。

任务可取消，有效进度保存在 SQLite 中。重新打开项目后继续识别，不重复插入字幕。带人工修改的区域不会被重新 OCR 自动覆盖；如需完全重做，可重新导入原视频创建新项目。

不可由内置播放器直接播放的格式，会自动生成兼容预览副本；OCR 始终读取原视频。字幕缓存包含源文件完整指纹、语言、区域及引擎版本，避免错误复用。

## 翻译配置

### 云端或 OpenAI 兼容 API

在“翻译设置”选择 API，填写包含版本路径的基地址、已可用模型名和密钥，例如基地址 `https://api.openai.com/v1`。应用调用 `/chat/completions`，要求支持 JSON 对象输出。LM Studio 等本地兼容服务可用 `http://localhost:1234/v1`，无鉴权的本地接口可留空密钥。

DeepSeek V4.1 Flash 使用 `https://api.deepseek.com` 和模型名 `deepseek-flash`，见 [DeepSeek 官方文档](https://api-docs.deepseek.com/zh-cn/)。官方接口的字幕翻译请求关闭默认思考模式，继续使用 JSON 返回和字幕 ID 校验；其他兼容接口不添加此参数。2026-10-02 已完成真实服务调用、真实英文字幕批量翻译及中文预览验证。

也可在启动进程环境中配置 `SUBTITLE_API_KEY`（兼容读取 `OPENAI_API_KEY`）。应用不展示或打印环境中的密钥值。界面输入的密钥使用 Electron safeStorage 加密保存在本机；系统安全存储不可用时，只在本次进程中保留。密钥不写进项目 SQLite、截图或日志。

### 已有 Ollama 服务

选择“本地 Ollama 服务”，地址通常为 `http://localhost:11434`，填写本机已经可用的模型名。应用请求 `/api/chat`，使用非流式 JSON 输出，不会调用模型安装或下载接口。本地请求直接连接，不经过系统 HTTP 代理。

### 模拟模式

用于不安装模型时验证工作流。已知测试句返回固定中文示例，其他内容返回带“模拟译文”标记的占位内容。界面横幅、字幕状态和检查列表均标注模拟，不能作为真实翻译质量证明。

术语表每行一个约定，例如 `Subtitle Studio = 字幕工作室`。真实适配器带上下文与术语表分批请求，检查字幕 ID、数量、空译文和重复返回；失败可以局部重试。人工译文受到保护。

## 验证与样本

```sh
.venv/bin/python tests/generate_fixture.py
npm test
npm run build
npm run test:desktop
.venv/bin/python tests/verify_media.py
```

桌面测试真实启动 Electron、真实识别像素、取消恢复、编辑保存重开、生成短片和全片、实际播放，再保存界面截图。测试模式只为文件选择对话框提供本地路径，未模拟 OCR、worker、渲染或媒体播放。API 与 Ollama 自动化测试使用本地响应服务验证协议，不声称运行了真实模型。

测试视频在 `artifacts/fixtures/`，参考时间轴只供独立评估使用，应用不读取该参考文件。测试包括 60 秒 720p 视频中的 13 条字幕、两行字幕、0.5 秒短字幕、重复句子、空白区间、变化背景、区域外文字及不规则帧时间戳。

评估某次桌面识别的原始结果：

```sh
.venv/bin/python tests/evaluate_ocr.py artifacts/desktop-<时间戳>/recognized.json
```

报告、截图和实际导出路径保存在对应桌面验收目录，汇总见 `docs/VALIDATION.md`。

## 本地打包

```sh
npm run package
```

当前扩展分支输出 `release-progressive/SubtitleStudioProgressive-darwin-arm64/SubtitleStudioProgressive.app`，不覆盖原 `release/SubtitleStudio-darwin-arm64/SubtitleStudio.app`，应用用户配置目录也分别保存。第一版为本机开发与本地打包成果，不包含签名、公证或可跨电脑直接运行的独立 Python 分发。迁移电脑时请重新准备依赖；不要把当前机器的虚拟环境当成通用安装包。

## 已知边界

- 优先处理固定区域、一至两行、清晰横排英文字幕。其他语言、移动字幕、动画字幕、严重模糊或遮挡需要逐项验证与校对。
- OCR 可能误识别，低对比背景经过像素过滤；不能保证发现所有漏字幕。检测到文字但无法读出的区间会保留待检查条目。
- 原字幕自然擦除与背景修复尚不属于首版；背景条会遮住部分画面。
- 视频烧录需要重新编码。当前默认输出 H.264/AAC，保持显示尺寸，可能改变码率和文件大小；HDR 色彩保真未验证。
- 2026-10-02 的两段真实视频测试暴露了说话人名称、选项文字、光标和画面变化造成的额外分段及误读。固定区域外的文字也会遗漏；当前尚不能对这类素材承诺自动处理准确。合成样本指标不能外推到真实全片。
- 按用户要求未安装独立模型；DeepSeek 云端连接和抽样译文已经实测，其他服务及全片逐句翻译质量仍需专项验证。
- 本地未签名应用在文稿文件夹保存项目时可能等待 macOS 访问许可；真实测试中曾因此写入超时。独立临时目录中的桌面翻译、渲染和播放成功；需区分系统文件权限与模型服务错误。

产品范围与验收标准见 `DESIGN.md`，执行记录见 `IMPLEMENTATION_PLAN.md`。

## 渐进字幕高质量模式

新增第三种可选识别模式：**扩展模式 · 渐进字幕高质量**。默认自动正文布局分离说话人和侧边选项，通过更长的换句确认、多帧候选与紧裁剪放大复读恢复整句。严格下半部/完整区域预设和手动排除框可处理对话框或已知水印。各模式结果独立保存，标准模式仍为默认。

识别置信度不是正确率。中文省略号、水印和短促被打断的句子仍需校对；完整出现时间是有多帧支持的 OCR 候选时间，不保证文字语义已经完结。真实片段对比、退化案例和验证边界见 [高质量验收报告](docs/QUALITY_VALIDATION.md)。

图像复核默认不发送截图。点击“上传字幕截图并复核这一条”才向当前支持图像的 API 发送最多三张字幕区域图；模型建议不会自动改写原文或人工译文。当前仅完成契约测试，真实图像外传实测等待具体授权；上述质量指标来自本地 OCR。[DeepSeek 图像接口说明](https://api-docs.deepseek.com/guides/vision/)。

`npm run package:quality` 生成独立 `release-quality/SubtitleStudioQuality-darwin-arm64/SubtitleStudioQuality.app`；不会覆盖已有 `release/` 和 `release-progressive/`。Goal 提示词见 [GOAL_QUALITY.md](GOAL_QUALITY.md)，实施记录见 [QUALITY_PLAN.md](QUALITY_PLAN.md)。

高质量独立应用将新项目与加密设置保存到 `~/Library/Application Support/SubtitleStudioQuality/`，重新打包可保留这些数据。
