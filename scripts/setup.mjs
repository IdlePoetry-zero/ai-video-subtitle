import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
const root = process.cwd();
fs.mkdirSync('runtime', { recursive: true });
function run(command, args) { const result = spawnSync(command, args, { stdio: 'inherit' }); if (result.status !== 0) process.exit(result.status || 1); }
const bundled = '/Users/max/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3';
const python = process.env.STUDIO_SETUP_PYTHON || (fs.existsSync(bundled) ? bundled : 'python3');
if (!fs.existsSync('.venv/bin/python')) run(python, ['-m', 'venv', '.venv']);
run('.venv/bin/python', ['-m', 'pip', 'install', '--cache-dir', 'runtime/pip-cache', '-r', 'requirements.lock']);
run('clang', ['-O2', '-fobjc-arc', 'worker/VisionOCR.m', '-framework', 'Foundation', '-framework', 'Vision', '-framework', 'ImageIO', '-framework', 'CoreGraphics', '-o', 'runtime/vision-ocr']);
console.log('本地处理环境就绪；未安装独立模型。运行 npm run dev。');
