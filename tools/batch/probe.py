"""Inspect a video (or a folder of videos) and suggest how to scan it.

Full-frame OCR at a handful of timestamps tells us whether subtitles sit in one
fixed band (standard mode is much faster) or move around (dynamic mode).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, repo_cwd  # noqa: E402

sys.path.insert(0, str(ROOT))
from worker.core import probe as probe_media  # noqa: E402


def inspect(path: Path, count: int, language: str, verbose: bool):
    from worker.core import frames, VisionOCR

    meta = probe_media(str(path))
    with repo_cwd():
        ocr = VisionOCR()
    frames_items = []
    boxes = []
    empty = 0
    try:
        for index in range(count):
            moment = meta['duration'] * (index + 0.5) / count
            try:
                _, image = next(frames(str(path), moment, None, .1, meta))
            except StopIteration:
                continue
            result = ocr.recognize(image, language)
            items = [item for item in result['items'] if item['confidence'] > .6]
            frames_items.append(items)
            if not items:
                empty += 1
    finally:
        ocr.close()

    # Text that sits in the same spot with the same words at most timestamps is a
    # title/watermark, not dialogue: drop it before deciding where subtitles live.
    seen = {}
    for items in frames_items:
        for text in {item['text'].strip() for item in items}:
            seen[text] = seen.get(text, 0) + 1
    static = {text for text, hits in seen.items() if hits >= max(3, count * .7)}
    notes = []
    for items in frames_items:
        items = [item for item in items if item['text'].strip() not in static]
        if not items:
            continue
        # Subtitles are normally the largest text on screen; drop small UI labels.
        tallest = max(item['box'][3] for item in items)
        items = [item for item in items if item['box'][3] >= tallest * .75]
        top = min(item['box'][1] for item in items)
        bottom = max(item['box'][1] + item['box'][3] for item in items)
        left = min(item['box'][0] for item in items)
        right = max(item['box'][0] + item['box'][2] for item in items)
        moment = meta['duration'] * (len(boxes) + 0.5) / max(1, len(frames_items))
        boxes.append({'time': moment, 'top': top, 'bottom': bottom, 'left': left, 'right': right,
                      'text': ' '.join(item['text'] for item in items)[:48]})
        if verbose:
            print(f"  {moment:7.1f}s  y {top:.2f}-{bottom:.2f}  x {left:.2f}-{right:.2f}  {boxes[-1]['text']!r}")
    if static:
        notes.append(f'忽略 {len(static)} 条固定叠加文字')

    suggestion = {'mode': 'dynamic', 'roi': None, 'reason': '字幕位置不固定'}
    if boxes:
        tops = [row['top'] for row in boxes]
        top_side = sum(1 for value in tops if value <= .30)
        bottom_side = sum(1 for value in tops if value >= .60)
        spread = max(tops) - min(tops)
        left = min(row['left'] for row in boxes)
        right = max(row['right'] for row in boxes)
        top = min(tops) - .02
        bottom = max(row['bottom'] for row in boxes) + .02
        roi = [round(max(0.0, left - .05), 3), round(max(0.0, top), 3),
               round(min(1.0, right - left + .10), 3), round(min(1.0, bottom - top), 3)]
        if bottom_side >= len(boxes) * .7 and spread <= .18:
            suggestion = {'mode': 'standard', 'roi': roi, 'reason': '字幕固定在画面下方'}
        elif top_side >= len(boxes) * .7 and spread <= .18:
            suggestion = {'mode': 'standard', 'roi': roi, 'reason': '字幕固定在画面上方'}
        else:
            suggestion = {'mode': 'dynamic', 'roi': None,
                          'reason': f'字幕纵坐标跨度 {spread:.2f}，位置不固定'}
    suggestion['notes'] = notes
    return {'meta': meta, 'samples': boxes, 'empty': empty, 'suggestion': suggestion}


def main():
    parser = argparse.ArgumentParser(description='探测视频并建议识别模式与区域')
    parser.add_argument('input', help='视频文件或包含 mp4 的目录')
    parser.add_argument('--samples', type=int, default=8, help='抽样时间点数量（默认 8）')
    parser.add_argument('--language', default='en-US')
    parser.add_argument('--verbose', action='store_true', help='打印每个时间点')
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    args = parser.parse_args()

    target = Path(args.input)
    files = sorted(target.glob('*.mp4')) if target.is_dir() else [target]
    report = []
    for file in files:
        if not file.is_file():
            print(f'跳过（不存在）：{file}')
            continue
        result = inspect(file, args.samples, args.language, args.verbose)
        meta = result['meta']
        suggestion = result['suggestion']
        entry = {
            'file': str(file),
            'duration_min': round(meta['duration'] / 60, 2),
            'size': f"{meta['width']}x{meta['height']}",
            'fps': round(meta['fps'], 2),
            'audio': meta['audio'],
            **suggestion,
        }
        report.append(entry)
        if not args.json:
            print(f"\n=== {file.name}")
            print(f"    {meta['width']}x{meta['height']}  {meta['duration']/60:.1f} min  "
                  f"{meta['fps']:.2f} fps  音轨={meta['audio']}")
            print(f"    有效抽样 {len(result['samples'])}/{args.samples}（空白 {result['empty']}）")
            print(f"    建议：{suggestion['mode']}   ROI={suggestion['roi']}   （{suggestion['reason']}）")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
