"""Clean a finished scan: merge duplicate reads, drop OCR noise, stop watermark captures.

Standard projects get gap closure and explicit cover windows; dynamic projects get
the overlap merge and the confirm/ignore decision that export depends on.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DEFAULT_WORKDIR, clamp_box, load_project, normalize, project_path,
                    save_project, similar, union)  # noqa: E402

URL = re.compile(r'^(?:https?://)?(?:www\.)?[a-z0-9][a-z0-9.\-]*\.'
                 r'(?:com|net|org|tv|co|io|me|gg|xyz|link|cc)(?:/\S*)?$', re.I)
HANDLE = re.compile(r'^@[A-Za-z0-9_.]{2,}$')
LABEL = re.compile(r'^[A-Z0-9+&/\-]{3,}$')


def is_watermark(text: str) -> bool:
    lines = [re.sub(r'\s+', '', line) for line in (text or '').splitlines() if line.strip()]
    return bool(lines) and all(URL.match(line) or HANDLE.match(line) or LABEL.match(line)
                               for line in lines)


def merge_duplicates(cues):
    """Collapse competing reads of one caption that overlap in time and place."""
    ordered = sorted(cues, key=lambda cue: (cue.get('first_seen', cue['start']), cue['box'][1], cue['box'][0]))
    merged, collapsed = [], 0
    for cue in ordered:
        start = cue.get('first_seen', cue['start'])
        end = cue.get('disappeared_at', cue['end'])
        target, best = None, 0.0
        for kept in merged:
            if kept['end'] < start - 1.0 or kept['start'] > end + 1.0:
                continue
            overlap = min(end, kept['end']) - max(start, kept['start'])
            if overlap <= 0.2 * min(end - start, kept['end'] - kept['start']):
                continue
            ratio = similar(kept['source'], cue['source'])
            if ratio > best and ratio >= .55:
                target, best = kept, ratio
        if target is None:
            merged.append(cue)
            continue
        collapsed += 1
        if len(normalize(cue['source'])) > len(normalize(target['source'])):
            target['source'] = cue['source']
        target['box'] = union(target['box'], cue['box'])
        first, last = min(target['start'], start), max(target['end'], end)
        target.update(start=first, end=last, first_seen=first, disappeared_at=last,
                      visible_intervals=[[first, last]],
                      confidence=max(target.get('confidence') or 0, cue.get('confidence') or 0))
    return merged, collapsed


def noise(cue, min_duration: float, min_confidence: float) -> bool:
    text = (cue.get('source') or '').strip()
    duration = cue['end'] - cue['start']
    confidence = cue.get('confidence') or 0
    words = len(re.findall(r"[A-Za-z][A-Za-z'’\-]*", text))
    cjk = len(re.findall(r'[\u4e00-\u9fff\u3040-\u30ff]', text))
    if not text or text.startswith('[无法识别'):
        return True
    if duration < min_duration:
        return True
    if confidence < min_confidence and duration < 1.2:
        return True
    if words == 0 and cjk < 3:
        return True
    if words < 2 and len(normalize(text)) < 12 and confidence < .95:
        return True
    return False


def clean_standard(cues, args):
    kept, dropped = [], 0
    for cue in cues:
        if noise(cue, args.min_duration, args.min_confidence):
            dropped += 1
            continue
        kept.append(cue)
    merged = closed = 0
    out = []
    for cue in sorted(kept, key=lambda item: item['start']):
        if out:
            previous = out[-1]
            gap = cue['start'] - previous['end']
            if -0.001 <= gap < args.gap:
                if normalize(previous['source']) == normalize(cue['source']):
                    previous['end'] = max(previous['end'], cue['end'])
                    merged += 1
                    continue
                cue['start'] = previous['end']
                closed += 1
        out.append(cue)
    for cue in out:
        cue['cover_intervals'] = [[cue['start'], cue['end']]]
    return out, dropped, merged, closed


def clean_dynamic(cues, args):
    merged, collapsed = merge_duplicates(cues)
    kept, dropped = [], []
    for cue in merged:
        if noise(cue, args.min_duration, args.min_confidence):
            dropped.append(cue)
            continue
        if args.ignore_watermarks and is_watermark(cue['source']):
            dropped.append(cue)
            continue
        kept.append(cue)
    for cue in kept:
        cue['dynamic_verified'] = True
        cue['ignored'] = False
        cue['visible_intervals'] = [[cue['start'], cue['end']]]
        if args.expand_boxes:
            cue['box'] = clamp_box(cue['box'], args.pad, args.pad, args.min_width, args.min_height)
    for cue in dropped:
        cue['dynamic_verified'] = False
        cue['ignored'] = True
    kept.sort(key=lambda item: item['start'])
    return kept + dropped, len(dropped), collapsed, 0


def main():
    parser = argparse.ArgumentParser(description='清洗识别结果（去噪、合并、对齐遮盖）')
    parser.add_argument('project', help='项目名或目录')
    parser.add_argument('--workdir', default=str(DEFAULT_WORKDIR))
    parser.add_argument('--min-duration', type=float, default=None, help='最短事件时长（秒）')
    parser.add_argument('--min-confidence', type=float, default=None, help='最低置信度')
    parser.add_argument('--gap', type=float, default=.8, help='小于该间隔的相邻字幕视为连续（秒）')
    parser.add_argument('--ignore-watermarks', action='store_true', help='忽略纯网址/账号/UI 标签')
    parser.add_argument('--expand-boxes', action='store_true', help='动态模式扩大字幕框以容纳译文')
    parser.add_argument('--pad', type=float, default=.006)
    parser.add_argument('--min-width', type=float, default=.12)
    parser.add_argument('--min-height', type=float, default=.052)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    folder = project_path(args.project, Path(args.workdir))
    data = load_project(folder)
    mode = data.get('recognition_mode', 'standard')
    cues = data['cues']
    if args.min_duration is None:
        args.min_duration = .35 if mode == 'standard' else .8
    if args.min_confidence is None:
        args.min_confidence = .55 if mode == 'standard' else .80
    if mode != 'dynamic':
        args.expand_boxes = False

    if mode == 'dynamic':
        result, dropped, collapsed, closed = clean_dynamic(cues, args)
        verified = sum(1 for cue in result if cue.get('dynamic_verified') and not cue.get('ignored'))
        print(f'{folder.name}: 动态模式  {len(cues)} → {len(result)} 条（合并 {collapsed}，丢弃 {dropped}，确认 {verified}）')
    else:
        result, dropped, collapsed, closed = clean_standard(cues, args)
        print(f'{folder.name}: 标准模式  {len(cues)} → {len(result)} 条（合并 {collapsed}，丢弃 {dropped}，闭合间隙 {closed}）')

    for cue in result[:5]:
        print(f"  {cue['start']:7.1f}-{cue['end']:7.1f}  {cue['source'][:52]!r}")

    if args.dry_run:
        print('（--dry-run，未写入）')
        return
    data['cues'] = result
    save_project(folder, data)
    print('已写入 project.sqlite')


if __name__ == '__main__':
    main()