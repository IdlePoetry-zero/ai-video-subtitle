import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
const root = process.cwd();
fs.mkdirSync('runtime', { recursive: true });
function run(command, args) { const result = spawnSync(command, args, { stdio: 'inherit' }); if (result.status !== 0) process.exit(result.status || 1); }
const windows = process.platform === 'win32';
const python = process.env.STUDIO_SETUP_PYTHON || (windows ? 'python' : 'python3');
const venvPython = windows ? '.venv/Scripts/python.exe' : '.venv/bin/python';
if (!fs.existsSync(venvPython)) run(python, ['-m', 'venv', '.venv']);
run(venvPython, ['-m', 'pip', 'install', '--cache-dir', 'runtime/pip-cache', '-r', windows ? 'requirements-windows.lock' : 'requirements.lock']);
if (windows) run(venvPython, ['scripts/windows_assets.py']);
else if (process.platform === 'darwin') run('clang', ['-O2', '-fobjc-arc', 'worker/VisionOCR.m', '-framework', 'Foundation', '-framework', 'Vision', '-framework', 'ImageIO', '-framework', 'CoreGraphics', '-o', 'runtime/vision-ocr']);
else throw new Error('目前只支持 macOS 和 Windows。');
console.log('本地处理环境就绪。运行 npm run dev。');
