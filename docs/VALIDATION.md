# 第一版验收记录

验收日期：2026-10-01。范围按 DESIGN.md 顶部的用户追加约束：不安装独立模型，真实 OCR 与视频处理保持有效，翻译使用明确标注的 mock；API 和本地服务适配器真实实现，但不声称验证真实模型质量。用户尚未提供业务视频，以下指标来自生成样本。

## 样本与独立识别指标

输入 `artifacts/fixtures/硬字幕 测试视频.mp4`：60 秒，1280×720，25 fps，13 个英文硬字幕事件。含两行字幕、0.5 秒短字幕、隔空白重复文本、无字幕区间、变化背景、区域外干扰标题及测试音频；仅视频与音频轨道。生成脚本为 `tests/generate_fixture.py`。参考 JSON 只供评估器和隔离单元测试读取，桌面应用及 OCR worker 不读取它。

最终真实桌面识别目录：`artifacts/desktop-1790843664528/`。`recognized.json` 在编辑前保存，避免人工校正改善 OCR 指标。评估结果保存在 `artifacts/ocr-evaluation.json`。

| 指标 | 实测 | 要求 |
| --- | --- | --- |
| 事件召回 | 13/13，100% | 100% |
| 错误新增事件 | 0 | 0 |
| CER | 0.2907% | ≤2% |
| 起止时间均在 200 ms 内 | 13/13，100% | ≥95% |
| 隔空白重复句 | 两个独立事件 | 不误合并 |
| OCR 调用 | 259 次 | 记录实际值 |
| 扫描耗时 | 16.37 秒 | 无实时承诺 |
| 代表截图缓存 | 约 204 KiB | 不逐帧存储 |

CER 只进行 NFKC 与空白规范化，保留标点、数字与否定词。另有 `variable-timestamps.mp4`，真实帧间隔为 0.08/0.12 秒，测试确认使用 PTS，而非帧序号除以平均帧率。

## 真实桌面工作流

`tests/desktop.mjs` 使用 Playwright 启动真实 Electron。测试模式只替代文件选择器的返回路径，OCR、worker、数据库、FFmpeg 和视频播放均为真实实现。

| 验收项 | 证据 |
| --- | --- |
| 中文与空格路径导入、真实框选移动 | `01-import.png` |
| 原生像素 OCR、13 条时间轴 | `recognized.json` |
| 2.28 秒处取消、打开项目后恢复 | `artifacts/desktop-final.log` 与项目检查点 |
| API、Ollama、mock 设置保存 | 桌面断言与 `result.json` |
| 原文、译文与起止时间自动保存，重开保留 | `02-editor.png`、桌面断言 |
| 人工译文保护、合并、拆分、撤销 | 桌面断言 |
| 与导出相同链路的短片预览，实际播放 | `03-preview.png` |
| SRT、整片 MP4 导出并跳转到 32 秒播放 | `04-export-playing.png`、`result.json` |
| 原视频缺失与重新定位、导入失败不丢当前项目 | `tests/test_core.py` 回归测试 |
| 视频内容变化拒绝复用时间轴 | 文件指纹回归测试 |

截图与 `result.json` 均在上述最终识别目录。项目目录为 `artifacts/desktop-1790843664528/项目 with spaces/`。

## 输出与画面核对

实际整片：`项目 with spaces/ui-export-1790843686943.mp4`；SRT：`项目 with spaces/ui-export-1790843686893.srt`；真实短片：`项目 with spaces/preview-1790843685559.mp4`，均在最终验收目录下。

`tests/verify_media.py` 从实际 MP4 解码画面并以原生中文 OCR 辅助检查。`media-check/contact-sheet.jpg` 已人工查看：1.00 秒无字幕；2.04 秒覆盖外文且尚未显示手动推迟的中文；3.00 秒显示人工译文；5.32 秒字幕消失；21.44 秒短字幕；26.00 秒空白；32.00 秒两行中文；58.00 秒末尾字幕。原外文在其存在时间内被不透明背景条覆盖，中文字体正常。

输出为 H.264、1280×720、25 fps、60.01 秒，音频实际存在。源与输出音频起点均为 0，终点分别为 60.00/60.01 秒，解码首秒测试音相关系数 0.999777。该证据用于本样本音画时长及音频保留检查，不代表任意对话素材、HDR 或复杂音轨已经验证。明文结果见 `media-check/result.json`。

字幕区域推荐也从真实视频抽帧 OCR：找到候选区域，归一化坐标约为 `[0.03, 0.81125, 0.94, 0.16597]`；以用户确认区域为准。

## 测试、构建与应用包

- `npm test`：13 项通过，约 3 秒。包括数字与否定词保护、字幕 ID 完整性、人工修改保存及撤销、非法修改拒绝、遮盖区间与中文区间独立、SRT 防覆盖、API/Ollama HTTP 契约、取消请求、VFR 时间戳、导出取消清理、视频变化缓存失效和缺失文件恢复。
- `npm run build`：TypeScript 类型检查和 Vite 生产构建通过。
- `npm run test:desktop`：真实桌面流程通过，无 renderer error。
- `npm audit`：0 vulnerabilities（本次锁文件审计）。
- `npm run package`：生成 `release/SubtitleStudio-darwin-arm64/SubtitleStudio.app`，约 535 MiB。Python 环境约 167 MiB、开发 npm 依赖约 407 MiB；未下载独立 OCR 或翻译模型。
- `node tests/package-smoke.mjs`：实际启动最终应用包，打开保存的项目，检查内置 FFmpeg/原生 OCR，并实际跳转播放。证据为 `artifacts/package-smoke.json`、`artifacts/packaged-app.png`。

本地应用包使用展开目录，保证 Python worker 与原生 helper 可执行；排除测试视频、项目、缓存、服务设置和日志。首版未签名、公证，Python 环境依赖当前机器已有运行时，不承诺跨电脑即开即用。

日志：`artifacts/tests-final.log`、`build-final.log`、`desktop-final.log`、`package-final.log`、`package-smoke.log`、`media-check.log`、`npm-audit.log`。

## 复现命令

```sh
npm ci
npm run setup
.venv/bin/python tests/generate_fixture.py
npm test
npm run build
npm run test:desktop
# 将下面目录替换为桌面测试打印的目录
.venv/bin/python tests/evaluate_ocr.py artifacts/desktop-1790843664528/recognized.json
.venv/bin/python tests/verify_media.py artifacts/desktop-1790843664528
npm run package
node tests/package-smoke.mjs
npm start
```

## 明确未验证项

真实翻译模型服务连通性、翻译语义质量及用户真实视频效果尚未验证。API 与 Ollama 使用本地 HTTP 响应服务验证协议和取消行为，模型默认使用 mock，绝不作为真实翻译质量证据。其他输入语言、复杂移动字幕、低清遮挡、HDR 与复杂多音轨需以后逐项验证。这些限制按本次用户授权的首版范围记录，未安装独立模型。
