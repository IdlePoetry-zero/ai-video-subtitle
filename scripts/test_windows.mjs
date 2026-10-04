import { spawnSync } from 'node:child_process';
const python = process.env.STUDIO_PYTHON || (process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv-windows-eval/bin/python');
const result = spawnSync(python, ['tests/windows_acceptance.py', ...process.argv.slice(2)], {
  stdio: 'inherit', env: { ...process.env, PYTHONUTF8: '1' },
});
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
