import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
if (process.platform !== 'win32') throw new Error('Windows 后端必须在 Windows 构建；请使用 GitHub Windows 构建流程。');
const python = process.env.STUDIO_PYTHON || '.venv/Scripts/python.exe';
function run(command, args) { const r = spawnSync(command, args, { stdio: 'inherit', env: { ...process.env, PYTHONUTF8: '1', ELECTRON_BUILDER_COMPRESSION_LEVEL: process.env.ELECTRON_BUILDER_COMPRESSION_LEVEL || '5' } }); if (r.status !== 0) process.exit(r.status ?? 1); }
run(python, ['scripts/windows_assets.py']);
run(python, ['scripts/freeze_windows.py']);
run(process.execPath, ['node_modules/typescript/bin/tsc', '--noEmit']);
run(process.execPath, ['node_modules/vite/bin/vite.js', 'build']);
run(process.execPath, ['node_modules/electron-builder/cli.js', '--config', 'config/electron-builder.windows.cjs', '--win', '--x64', '--publish', 'never']);
