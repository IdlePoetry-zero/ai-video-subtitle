"""Check a rendered video against its project: are the cues actually translated on screen?"""
from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DEFAULT_WORKDIR, ROOT, load_project, project_path, repo_cwd  # noqa: E402

sys.path.insert(0, str(ROOT))
from worker.core import VisionOCR, crop, frames, probe  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='抽检成片：字幕是否真的换成了中文')
    parser.add_argument('project')
    parser.add_argument('--export', required=True, help='成片 mp4 路径')
    parser.add_argument('--samples', type=int, default=30, help='字幕取样条数')
    parser.add_argument('--leftover', type=int, default=20, help='随机时间点检查残留英文（0 关闭）')
    parser.add_argument('--workdir', default=str(DEFAULT_WORKDIR))
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args()

    folder = project_path(args.project, Path(args.workdir))
    data = load_project(folder)
    export = Path(args.export)
    if not export.is_file():
        raise SystemExit(f'找不到成片：{export}')
    meta = probe(str(export))
    random.seed(args.seed)

    candidates = [cue for cue in data['cues']
                  if cue.get('translation')
                  and (data.get('recognition_mode') != 'dynamic'
                       or (cue.get('dynamic_verified') and not cue.get('ignored')))]
    if not candidates:
        raise SystemExit('项目里没有可抽检的字幕')

    with repo_cwd():
        ocr = VisionOCR()
    ok = latin = empty = 0
    problems = []
    try:
        for cue in random.sample(candidates, min(args.samples, len(candidates))):
            moment = (cue['start'] + cue['end']) / 2
            _, image = next(frames(str(export), moment, None, .1, meta))
            box = cue.get('box') or data['roi'] if data.get('recognition_mode') == 'dynamic' else data['roi']
            pad = .02
            roi = [max(0., box[0] - pad), max(0., box[1] - pad),
                   min(1. - box[0] + pad, box[2] + 2 * pad), min(1. - box[1] + pad, box[3] + 2 * pad)]
            text = ocr.recognize(crop(image, roi), 'en-US')['text']
            if re.search(r'[\u4e00-\u9fff]', text):
                ok += 1
            elif re.search(r'[A-Za-z]{3,}', text):
                latin += 1
                problems.append(('残留英文', round(moment, 1), text[:40]))
            else:
                empty += 1
                problems.append(('空白', round(moment, 1), cue.get('translation', '')[:24]))

        print(f'字幕抽检 {min(args.samples, len(candidates))} 条：中文 {ok}，残留英文 {latin}，空白 {empty}')

        if args.leftover and data.get('recognition_mode') != 'dynamic':
            source = data['meta']['path']
            if not Path(source).is_file():
                print('原视频不在原位，跳过残留检查')
            else:
                source_meta = probe(source)
                roi = data['roi']
                left = missed = replaced = 0
                for _ in range(args.leftover):
                    moment = random.uniform(5, meta['duration'] - 5)
                    try:
                        _, before = next(frames(source, moment, None, .1, source_meta))
                        _, after = next(frames(str(export), moment, None, .1, meta))
                    except StopIteration:
                        continue
                    original = ocr.recognize(crop(before, roi), 'en-US')['text']
                    rendered = ocr.recognize(crop(after, roi), 'en-US')['text']
                    if not re.search(r'[A-Za-z]{3,}', original):
                        continue
                    if re.search(r'[\u4e00-\u9fff]', rendered):
                        replaced += 1
                    elif re.search(r'[A-Za-z]{3,}', rendered):
                        left += 1
                    else:
                        missed += 1
                total = replaced + left + missed
                if total:
                    print(f'随机时间点 {total} 处原片有英文：已替换 {replaced}，'
                          f'残留 {left}，空白 {missed}')
    finally:
        ocr.close()

    for row in problems[:8]:
        print('  ', row)


if __name__ == '__main__':
    main()
