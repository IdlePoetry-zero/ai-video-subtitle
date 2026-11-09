"""Create a project for one video and run the recognition scan.

Standard mode is for subtitles that stay inside one band; dynamic mode finds
captions anywhere on screen.  Dynamic mode accepts a shard count n (parallel
child workers) and a scan interval m in seconds.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DEFAULT_WORKDIR, Worker, format_seconds  # noqa: E402

STANDARD_STYLE = {'mode': 'cover', 'coverArea': 'region', 'fontSize': 46, 'background': '#000000',
                  'color': '#ffffff', 'padding': 2, 'maxCps': 12, 'maxChars': 44, 'maxLines': 2}
DYNAMIC_STYLE = {'mode': 'cover', 'coverArea': 'text', 'fontSize': 38, 'background': '#000000',
                 'color': '#ffffff', 'padding': 3, 'maxCps': 12, 'maxChars': 44, 'maxLines': 2}


def main():
    parser = argparse.ArgumentParser(description='创建项目并识别字幕')
    parser.add_argument('video')
    parser.add_argument('--name', required=True, help='项目名（作为工作目录下的子目录）')
    parser.add_argument('--mode', choices=('standard', 'dynamic'), default='standard')
    parser.add_argument('--roi', help='标准模式区域 x,y,w,h（归一化，如 0.05,0.88,0.90,0.11）')
    parser.add_argument('--shards', type=int, default=2, help='动态模式并行分片数（1-8，默认 2）')
    parser.add_argument('--interval', type=float, default=.4, help='动态模式扫描间隔秒（0.15-2，默认 0.4）')
    parser.add_argument('--profile', choices=('legacy', 'enhanced'), default='legacy')
    parser.add_argument('--language', default='en-US')
    parser.add_argument('--workdir', default=str(DEFAULT_WORKDIR))
    parser.add_argument('--translation', choices=('api', 'ollama', 'mock'), default='api')
    parser.add_argument('--api-base', default='https://api.deepseek.com')
    parser.add_argument('--api-model', default='deepseek-flash')
    parser.add_argument('--start', type=float, default=0.0)
    parser.add_argument('--end', type=float, default=None)
    parser.add_argument('--overwrite', action='store_true', help='已存在同名项目时删除重建')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    video = Path(args.video)
    if not video.is_file():
        raise SystemExit(f'找不到视频：{video}')
    folder = Path(args.workdir) / args.name
    if folder.exists():
        if not args.overwrite:
            raise SystemExit(f'项目已存在：{folder}（加 --overwrite 覆盖）')
        shutil.rmtree(folder)

    changes = {
        'language': args.language,
        'translation': {'provider': args.translation, 'baseUrl': args.api_base,
                        'model': args.api_model, 'glossary': ''},
    }
    if args.mode == 'standard':
        if not args.roi:
            raise SystemExit('标准模式需要 --roi（可用 probe.py 得到建议值）')
        changes['roi'] = [float(part) for part in args.roi.split(',')]
        changes['style'] = STANDARD_STYLE
    else:
        changes['recognition_mode'] = 'dynamic'
        changes['dynamic'] = {'exclusions': [], 'profile': args.profile, 'review_regions': [],
                              'shards': max(1, min(8, args.shards)),
                              'interval': max(.15, min(2.0, args.interval))}
        changes['style'] = DYNAMIC_STYLE

    worker = Worker()
    started = time.time()
    try:
        project = worker.call('create', {'video': str(video.resolve()), 'directory': str(folder)})
        project = worker.call('update', {'changes': changes})
        meta = project['meta']
        print(f"项目 {args.name}：{meta['width']}x{meta['height']}  "
              f"{format_seconds(meta['duration'])}  模式={project['recognition_mode']}")
        if args.mode == 'dynamic':
            print(f"  分片 n={changes['dynamic']['shards']}  间隔 m={changes['dynamic']['interval']}s  "
                  f"profile={args.profile}")
        else:
            print(f"  ROI={changes['roi']}")

        worker.call('scan', {'start': args.start, 'end': args.end, 'force': True})
        status, result, error = worker.wait_job(quiet=not args.verbose)
        if status != 'complete':
            raise SystemExit(f'识别失败（{status}）：{error}')
        cues = result['cues']
        elapsed = time.time() - started
        print(f"识别完成：{len(cues)} 条事件，用时 {elapsed/60:.1f} 分钟"
              f"（{meta['duration']/elapsed:.2f}x 实时）")
        for cue in cues[:5]:
            print(f"  {format_seconds(cue['start'])}  {cue['source'][:50]!r}")
    finally:
        worker.close()


if __name__ == '__main__':
    main()