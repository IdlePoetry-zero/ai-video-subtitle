"""One-shot batch pipeline: probe → scan → clean → translate → export → QA.

Individual steps are separate scripts; this driver just chains them with the
settings that worked well on real footage.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(script: str, *arguments, capture: bool = False):
    command = [sys.executable, str(HERE / script), *map(str, arguments)]
    print(f'\n$ {" ".join(Path(part).name if part.startswith(str(HERE)) else part for part in command[1:])}',
          flush=True)
    result = subprocess.run(command, text=True, encoding='utf-8',
                            capture_output=capture)
    if result.returncode != 0:
        if capture and result.stderr:
            print(result.stderr[-1500:])
        raise SystemExit(f'{script} 失败（退出码 {result.returncode}）')
    if capture:
        print(result.stdout.strip())
    return result.stdout if capture else ''


def suggest_shards(duration: float) -> int:
    minutes = duration / 60
    if minutes <= 15:
        return 2
    if minutes <= 40:
        return 3
    return 4


def main():
    parser = argparse.ArgumentParser(description='一条命令完成探测 → 识别 → 清洗 → 翻译 → 导出 → 质检')
    parser.add_argument('video')
    parser.add_argument('--name', help='项目名（默认取视频文件名）')
    parser.add_argument('--mode', choices=('auto', 'standard', 'dynamic'), default='auto')
    parser.add_argument('--roi', help='标准模式区域；auto 时由 probe 给出')
    parser.add_argument('--shards', default='auto', help='动态模式分片数，auto 或 1-8')
    parser.add_argument('--interval', type=float, default=.4, help='动态模式扫描间隔（默认 0.4s）')
    parser.add_argument('--workdir', default=None, help='项目目录（默认 runtime/projects）')
    parser.add_argument('--output-dir', default=None, help='成品目录（默认与视频同目录）')
    parser.add_argument('--no-watermark-filter', action='store_true')
    parser.add_argument('--skip-qa', action='store_true')
    parser.add_argument('--start', type=float, default=None)
    parser.add_argument('--end', type=float, default=None)
    args = parser.parse_args()

    video = Path(args.video).resolve()
    if not video.is_file():
        raise SystemExit(f'找不到视频：{video}')
    name = args.name or video.stem.replace(' ', '-')[:60]
    workdir_args = ['--workdir', args.workdir] if args.workdir else []

    probe_output = run('probe.py', video, '--json', capture=True)
    info = json.loads(probe_output)[0]
    duration = info['duration_min'] * 60
    mode = args.mode if args.mode != 'auto' else info['mode']
    roi = args.roi or (','.join(str(part) for part in info['roi']) if info['roi'] else None)
    if mode == 'standard' and not roi:
        raise SystemExit('该视频需要显式 --roi（probe 未能给出稳定区域）')
    shards = suggest_shards(duration) if args.shards == 'auto' else int(args.shards)
    print(f'\n[{name}] {duration/60:.1f} min  模式={mode}  '
          f"{'ROI=' + roi if mode == 'standard' else f'分片={shards} 间隔={args.interval}s'}")

    scan_args = [video, '--name', name, '--mode', mode, '--overwrite', *workdir_args]
    if mode == 'standard':
        scan_args += ['--roi', roi]
    else:
        scan_args += ['--shards', shards, '--interval', args.interval]
    if args.start is not None:
        scan_args += ['--start', args.start]
    if args.end is not None:
        scan_args += ['--end', args.end]
    run('scan.py', *scan_args)

    clean_args = [name, '--expand-boxes', *workdir_args]
    if not args.no_watermark_filter:
        clean_args.append('--ignore-watermarks')
    run('clean.py', *clean_args)

    run('translate.py', name, *workdir_args)

    output_dir = Path(args.output_dir) if args.output_dir else video.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f'{video.stem}_中文版.mp4'
    run('export.py', name, '--output', output, *workdir_args)

    if not args.skip_qa:
        run('qa.py', name, '--export', output, *workdir_args)

    print(f'\n完成：{output}')


if __name__ == '__main__':
    main()
