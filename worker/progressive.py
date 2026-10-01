"""Optional fixed-region growing-caption aggregation; standard OCR remains isolated."""
from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import uuid

import numpy as np
from PIL import Image

from worker.core import (VisionOCR, Cancelled, probe, file_fingerprint, frames, crop,
                         signature, validate_roi, normalize, compatible, check_cues)

VERSION = 'progressive-v2'
BLANK_GRACE = .16
RESET_CONFIRM = .12
COVER_GRACE = .2


def relation(previous, text):
    """Only append growth or very close OCR corrections; rewrites start new events."""
    a, b = normalize(previous).casefold(), normalize(text).casefold()
    if not a:
        return 'grow'
    if a == b:
        return 'same'
    if a.rstrip('.!?。！？') == b.rstrip('.!?。！？'):
        return 'correction'
    compact_a, compact_b = re.sub(r'\s+', '', a), re.sub(r'\s+', '', b)
    if compact_b.startswith(compact_a) and len(compact_b) > len(compact_a):
        return 'grow'
    if b.startswith(a) and len(b) > len(a):
        return 'grow'
    if a.startswith(b) and len(b) < len(a):
        return 'shrink'
    # Corrections must retain actual numeric and negation evidence.
    if len(b) > len(a) and len(a) >= 8:
        prefix = b[:len(a)]
        if compatible(a, prefix):
            return 'grow'
    if compatible(a, b):
        return 'correction'
    return 'change'


def best_variant(event):
    values = event['variants']
    if not values:
        return None
    reliable = [text for text, stats in values.items()
                if stats['count'] >= 2 and stats['last']-stats['first'] >= .119 and stats['confidence'] >= .4]
    candidates = reliable or list(values)
    return max(candidates, key=lambda text: (len(normalize(text)), values[text]['count'], values[text]['confidence']))


def new_event(timestamp, roi):
    return {'id': str(uuid.uuid4()), 'start': max(0., timestamp-.04), 'last_seen': timestamp,
            'current': '', 'roi': list(roi), 'variants': {}, 'transient_changes': 0,
            'screenshot': '', 'screenshot_text': ''}


def record(event, timestamp, result):
    text = result['text'].strip()
    event['last_seen'] = timestamp
    if not text:
        return
    values = event['variants']
    stats = values.setdefault(text, {'count': 0, 'confidence': 0., 'first': timestamp, 'last': timestamp})
    stats['count'] += 1
    stats['last'] = timestamp
    stats['confidence'] = max(stats['confidence'], float(result.get('confidence', 0)))
    kind = relation(event['current'], text)
    if kind in ('grow', 'same', 'correction'):
        event['current'] = text


def event_to_cue(event, end, display='first'):
    best = best_variant(event)
    stats = event['variants'].get(best, {})
    stable = bool(best and stats['count'] >= 2 and stats['last']-stats['first'] >= .119 and stats['confidence'] >= .4)
    # Retrospective confirmation can use an earlier full-word observation that
    # omitted only trailing punctuation; retain exactly what that frame read.
    equivalent = [text for text in event['variants'] if best and
                  normalize(text).rstrip('.!?。！？') == normalize(best).rstrip('.!?。！？')]
    evidence_text = min(equivalent, key=lambda text: event['variants'][text]['first']) if equivalent else best
    complete_time = round(event['variants'][evidence_text]['first'], 3) if stable else None
    source = best or '[无法识别的字幕]'
    issue = ''
    if not stable:
        issue = '完整文本缺少多帧证据，请核对'
    elif len(event['variants']) > 1 and not re.search(r'[.!?。！？]$', source.strip()):
        issue = '文字曾逐步增长，末尾未见结束标点，请确认是否完整'
    start = complete_time if display == 'complete' and complete_time is not None else event['start']
    return {'id': event['id'], 'start': round(start, 3), 'end': round(max(start+.01, end), 3),
            'original_start': round(event['start'], 3), 'original_end': round(end, 3),
            # Mask sampling uncertainty without changing measured cue times or
            # the user's Chinese display policy; standard rendering is unchanged.
            'cover_intervals': [[round(max(0., event['start']-COVER_GRACE), 3), round(end+COVER_GRACE, 3)]],
            'first_seen': round(event['start'], 3), 'complete_time': complete_time,
            'complete_evidence_text': evidence_text if stable else None,
            'disappeared_at': round(end, 3), 'source': source,
            'raw_ocr': list(event['variants']), 'growth': [dict(text=text, **values) for text, values in event['variants'].items()],
            'recognition_mode': 'progressive', 'complete_supported': stable,
            'confidence': stats.get('confidence', 0), 'translation': '', 'translation_status': 'missing',
            'box': event['roi'], 'screenshot': event['screenshot'], 'manual': False,
            'manual_translation': False, 'manual_time': False, 'revision': 0, 'recognition_issue': issue,
            'transient_changes': event['transient_changes'], 'issues': []}


class Tracker:
    """JSON-serializable active and pending events, including debounce checkpoints."""
    def __init__(self, state=None, display='first'):
        self.state = state or {'active': None, 'pending': None, 'blank_since': None}
        self.display = display

    def finish(self, end):
        active = self.state['active']
        self.state.update(active=None, pending=None, blank_since=None)
        return [event_to_cue(active, end, self.display)] if active else []

    def observe(self, timestamp, result, roi):
        state = self.state
        text = result['text'].strip()
        active = state['active']
        if not text and not result.get('unreadable'):
            if active:
                if state['blank_since'] is None:
                    state['blank_since'] = timestamp
                if timestamp-state['blank_since'] >= BLANK_GRACE-1e-6:
                    return self.finish(max(active['start']+.01, state['blank_since']-.04))
            return []
        state['blank_since'] = None
        if active and list(roi) != active['roi']:
            closed = self.finish(timestamp-.04)
            state['active'] = new_event(timestamp, roi)
            record(state['active'], timestamp, result)
            return closed
        if active is None:
            state['active'] = new_event(timestamp, roi)
            record(state['active'], timestamp, result)
            return []
        if not text:
            active['last_seen'] = timestamp
            return []
        kind = relation(active['current'], text)
        if kind == 'shrink' and text == best_variant(active) and active['variants'].get(active['current'], {}).get('count', 0) < 2:
            # Discard an uncorroborated one-frame extension instead of creating
            # a duplicate caption when the confirmed text returns.
            active['current'] = text
            active['transient_changes'] += 1
            kind = 'same'
        if kind in ('grow', 'same', 'correction'):
            if state['pending']:
                active['transient_changes'] += 1
            state['pending'] = None
            record(active, timestamp, result)
            return []
        # A contraction may be OCR dropout or a new caption restarting at its prefix.
        # Keep both hypotheses until the new text persists or itself grows.
        pending = state['pending']
        if pending is None or relation(pending['current'], text) not in ('same', 'grow', 'correction'):
            pending = new_event(timestamp, roi)
            state['pending'] = pending
        record(pending, timestamp, result)
        pending_count = sum(value['count'] for value in pending['variants'].values())
        if timestamp-(pending['start']+.04) >= RESET_CONFIRM-1e-6 and pending_count >= 2:
            closed = event_to_cue(active, pending['start'], self.display)
            state.update(active=pending, pending=None)
            return [closed]
        return []


def scan_progressive(project, emit=lambda value: None, cancel=None, start=0., end=None, force=False):
    cancel = cancel or threading.Event()
    data = project.data
    meta = probe(data['meta']['path'])
    fingerprint = file_fingerprint(meta['path'])
    if data.get('fingerprint_version') == 1 and fingerprint != data['fingerprint']:
        raise ValueError('原视频内容已经变化，请为新视频创建项目。')
    if not data.get('fingerprint_version'):
        data.update(fingerprint=fingerprint, fingerprint_version=1)
    end = min(end if end is not None else meta['duration'], meta['duration'])
    if not 0 <= start < end:
        raise ValueError('试处理区间无效。')
    validate_roi(data['roi'])
    config = data.get('progressive', {'display': 'first'})
    # Display timing is a presentation setting; it does not invalidate pixel OCR.
    key = hashlib.sha256(json.dumps([fingerprint, data['roi'], data['regions'], data['language'], VERSION, start, end]).encode()).hexdigest()
    checkpoint = data.get('scan', {})
    resume = checkpoint.get('key') == key and checkpoint.get('status') in ('running', 'cancelled', 'failed') and not force
    if checkpoint.get('key') == key and checkpoint.get('status') == 'complete' and not force:
        emit({'stage': 'scan', 'status': 'cached', 'time': end, 'total': end, 'message': '逐步模式结果已保存，无需重复运行。'})
        return project.snapshot()
    if not resume:
        def overlaps(cue):
            return cue.get('first_seen', cue['start']) < end and cue.get('disappeared_at', cue['end']) > start
        if any(cue.get('manual') and overlaps(cue) for cue in data['cues']):
            raise ValueError('选定范围含人工修改字幕，请缩小范围或创建新项目。')
        data['cues'] = [cue for cue in data['cues'] if not overlaps(cue)]
        checkpoint = {'key': key, 'cursor': start-.0001, 'status': 'running', 'calls': 0, 'tracker': None, 'mode': 'progressive', 'version': VERSION}
        data['scan'] = checkpoint
        project.save(history=True)
    tracker = Tracker(checkpoint.get('tracker'), config.get('display', 'first'))
    checkpoint['tracker'] = tracker.state
    previous_signature, last_ocr = None, -999.
    started, saved = time.monotonic(), time.monotonic()
    ocr = VisionOCR()
    try:
        if data['language'] not in ocr.request({'operation': 'languages'})['languages']:
            raise ValueError('当前系统 OCR 不支持所选语言。')
        for timestamp, image in frames(meta['path'], checkpoint['cursor']+.0001, end, .08, meta):
            if cancel.is_set():
                raise Cancelled()
            roi = next((region['roi'] for region in data['regions'] if region['start'] <= timestamp < region['end']), data['roi'])
            pixels = crop(image, roi)
            sig = signature(pixels)
            delta = float(np.mean(sig != previous_signature)) if previous_signature is not None else 1.
            if delta > .002 or timestamp-last_ocr >= .159:
                result = ocr.recognize(pixels, data['language'])
                last_ocr = timestamp
                data['cues'].extend(tracker.observe(timestamp, result, roi))
                for event in (tracker.state['active'], tracker.state['pending']):
                    if event:
                        best = best_variant(event)
                        if best == result['text'].strip() and best != event['screenshot_text']:
                            path = project.directory/'evidence'/f"{event['id']}.jpg"
                            Image.fromarray(pixels).save(path)
                            event.update(screenshot=str(path), screenshot_text=best)
            previous_signature = sig
            checkpoint.update(cursor=timestamp, status='running')
            if time.monotonic()-saved >= .8:
                checkpoint['calls'] += ocr.calls
                ocr.calls = 0
                data['cues'].sort(key=lambda cue: cue['start'])
                project.save()
                emit({'stage': 'scan', 'status': 'running', 'time': timestamp, 'total': end,
                      'count': len(data['cues']), 'message': '正在恢复逐步出现字幕的完整句'})
                saved = time.monotonic()
        final_end = tracker.state['blank_since']-.04 if tracker.state['blank_since'] is not None else end
        data['cues'].extend(tracker.finish(final_end))
        checkpoint.update(status='complete', cursor=end)
        data['cues'].sort(key=lambda cue: cue['start'])
        check_cues(data['cues'], data['style'], data['translation'].get('glossary', ''))
        return project.snapshot()
    except Cancelled:
        checkpoint['status'] = 'cancelled'
        raise
    except Exception:
        checkpoint['status'] = 'failed'
        raise
    finally:
        checkpoint['calls'] += ocr.calls
        checkpoint['elapsed'] = checkpoint.get('elapsed', 0)+time.monotonic()-started
        project.save()
        ocr.close()
