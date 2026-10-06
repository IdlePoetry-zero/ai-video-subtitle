"""Subtitle cover geometry and optional local, per-frame background interpolation."""
from __future__ import annotations

import math


def union_boxes(boxes):
    x = min(b[0] for b in boxes)
    y = min(b[1] for b in boxes)
    return [x, y, max(b[0] + b[2] for b in boxes) - x,
            max(b[1] + b[3] for b in boxes) - y]


def remember_text_box(event, result):
    """Keep the union across growth stages, in full-frame normalized coordinates."""
    boxes = [item['box'] for item in result.get('items', []) if item.get('text', '').strip()]
    if not boxes:
        return
    x, y, w, h = union_boxes(boxes)
    rx, ry, rw, rh = event['roi']
    current = [rx + x * rw, ry + y * rh, w * rw, h * rh]
    event['source_box'] = union_boxes([event['source_box'], current]) if event.get('source_box') else current


def source_box(cue, fallback):
    # Dynamic boxes can be manually corrected, merged or split. They take priority
    # over stale OCR evidence; quality body_box is relative to its original ROI.
    region = cue.get('box', fallback)
    if cue.get('recognition_mode') == 'dynamic':
        return region
    if cue.get('source_box'):
        return cue['source_box']
    if cue.get('body_box'):
        x, y, w, h = cue['body_box']
        rx, ry, rw, rh = region
        return [rx + x * rw, ry + y * rh, w * rw, h * rh]
    return region


def pixel_box(cue, meta, style, fallback, tight=None):
    tight = (style['mode'] != 'above' and (style.get('coverArea', 'region') == 'text' or style['mode'] == 'delogo')) if tight is None else tight
    x, y, w, h = source_box(cue, fallback) if tight else cue.get('box', fallback)
    width, height = meta['width'], meta['height']
    padding = max(0, min(50, int(style['padding'])))
    lower = (lambda n: math.floor(n + 1e-7)) if tight else round
    upper = (lambda n: math.ceil(n - 1e-7)) if tight else round
    return [max(0, min(width - 1, lower(x * width) - padding)),
            max(0, min(height - 1, lower(y * height) - padding)),
            max(1, min(width, upper((x + w) * width) + padding)),
            max(1, min(height, upper((y + h) * height) + padding))]


def cover_intervals(cue):
    if cue.get('recognition_mode') == 'dynamic':
        from worker.dynamic import visible_intervals
        return visible_intervals(cue)
    return cue.get('cover_intervals', [[cue.get('original_start', cue['start']),
                                       cue.get('original_end', cue['end'])]])


def local_repair_filters(data, start=None, end=None):
    """Delogo interpolates from each frame's border; it cannot recover hidden detail.

    Group identical rectangles and use half-open intervals. Filter scripts avoid
    Windows command length limits and exclude invisible/unconfirmed objects.
    """
    if data['style']['mode'] != 'delogo':
        return []
    meta = data['meta']
    width, height = meta['width'], meta['height']
    if width < 4 or height < 4:
        raise ValueError('视频尺寸不足以进行局部去字。')
    groups = {}
    lo, hi = max(0, start or 0), min(meta['duration'], end if end is not None else meta['duration'])
    for cue in data['cues']:
        if data.get('recognition_mode') == 'dynamic':
            from worker.dynamic import eligible
            if not eligible(cue):
                continue
        left, top, right, bottom = pixel_box(cue, meta, data['style'], data['roi'], True)
        # Delogo needs at least one intact border pixel inside the image.
        left, top = max(1, left), max(1, top)
        right, bottom = min(width - 1, right), min(height - 1, bottom)
        if right - left < 2 or bottom - top < 2:
            raise ValueError('字幕区域太小或紧贴画面边缘，无法局部去字；请使用背景覆盖。')
        intervals = []
        for a, b in cover_intervals(cue):
            a, b = max(lo, a), min(hi, b)
            if a < b:
                intervals.append((a, b))
        if intervals:
            groups.setdefault((left, top, right - left, bottom - top), []).extend(intervals)
    if len(groups) > 2048:
        raise ValueError('局部去字区域过多，请分段导出或使用背景覆盖。')
    filters = []
    for (x, y, w, h), intervals in groups.items():
        merged = []
        for a, b in sorted(intervals):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        enable = '+'.join(f'gte(t,{a:.6f})*lt(t,{b:.6f})' for a, b in merged)
        filters.append(f"delogo=x={x}:y={y}:w={w}:h={h}:enable='{enable}'")
    return filters
