"""Render the subtitled video (and optionally an SRT) from a project."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DEFAULT_WORKDIR, Worker, project_path  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='导出带中文字幕的视频 / SRT')
    parser.add_argument('project')
    parser.add_argument('--output', required=True, help='输出 mp4 路径')
    parser.add_argument('--srt', default=None, help='同时导出 SRT 到该路径')
    parser.add_argument('--bilingual', action='store_true', help='SRT 同时保留原文')
    parser.add_argument('--start', type=float, default=None, help='只导出该时间之后（秒）')
    parser.add_argument('--end', type=float, default=None)
    parser.add_argument('--workdir', default=str(DEFAULT_WORKDIR))
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    folder = project_path(args.project, Path(args.workdir))
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    worker = Worker()
    started = time.time()
    try:
        worker.call('open', {'directory': str(folder)})
        worker.call('export', {'output': str(output), 'start': args.start, 'end': args.end})
        status, project, error = worker.wait_job(quiet=not args.verbose)
        if status != 'complete':
            raise SystemExit(f'导出失败（{status}）：{error}')
        size = output.stat().st_size / 1048576
        print(f'视频完成：{output}  {size:.0f} MB  用时 {(time.time()-started)/60:.1f} 分钟')
        if args.srt:
            srt = Path(args.srt).resolve()
            srt.parent.mkdir(parents=True, exist_ok=True)
            if srt.exists():
                srt.unlink()
            worker.call('srt', {'output': str(srt), 'bilingual': args.bilingual})
            print(f'字幕完成：{srt}')
    finally:
        worker.close()


if __name__ == '__main__':
    main()
