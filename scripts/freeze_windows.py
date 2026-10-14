"""Build on Windows itself; PyInstaller cannot cross-compile from macOS."""
from pathlib import Path
import subprocess
import sys

if sys.platform != 'win32':
    raise SystemExit('Windows 后端必须在 Windows x64 环境构建。')
args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
        '--name', 'subtitle-worker', '--distpath', 'build-windows/dist',
        '--workpath', 'build-windows/work', '--specpath', 'build-windows']
for package in ['rapidocr_onnxruntime', 'onnxruntime', 'av', 'imageio_ffmpeg']:
    args += ['--collect-all', package]
for module in ['server', 'core', 'appearance', 'platform_runtime', 'ocr_rapid', 'translation_client',
               'dynamic', 'coverage', 'export_lock', 'progressive', 'quality', 'visual_review', 'visual_client']:
    args += ['--hidden-import', 'worker.' + module]
args += ['worker/entry.py']
subprocess.run(args, check=True)
