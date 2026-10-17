"""Shard-parallel dynamic scan.

The parent splits [start, end] into N windows, runs the ordinary dynamic scan for
each window in a child process (its own copy of the project database), then merges
the resulting events back into the parent project.  Neighbouring windows overlap a
little so a caption crossing a boundary is still recognised; the merge step then
collapses the duplicated reads.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from worker.core import Project, Cancelled
from worker.platform_runtime import ROOT, subprocess_options

OVERLAP = 2.5
POLL = 1.0


def _norm(text):
    return ' '.join(unicodedata.normalize('NFKC', text).split()).casefold()


def _similar(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.92
    return SequenceMatcher(None, a, b).ratio()


def _union(a, b):
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return [x0, y0, x1 - x0, y1 - y0]


def _ranges(start, end, count):
    span = (end - start) / count
    windows = []
    for index in range(count):
        left = start + index * span
        right = end if index == count - 1 else start + (index + 1) * span
        windows.append([max(start, left - (OVERLAP if index else 0.0)), right])
    return windows


def _reset_copy(source, folder, interval):
    """Give the child its own project copy restricted to the shard window."""
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, folder / 'project.sqlite')
    child = Project(str(folder))
    child.data['cues'] = []
    child.data['scan'] = {}
    child.data['dynamic'] = {**child.data.get('dynamic', {}), 'shards': 1, 'interval': interval}
    child.data['task'] = {'stage': 'scan', 'status': 'running'}
    child.data['outputs'] = []
    child.save()
    child.close()


def _cursor(folder):
    path = folder / 'project.sqlite'
    try:
        db = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=1)
        row = db.execute('SELECT payload FROM project WHERE id=1').fetchone()
        db.close()
        if row:
            return float(json.loads(row[0]).get('scan', {}).get('cursor') or 0)
    except Exception:
        pass
    return 0.0


def _merge_cues(cues):
    """Collapse duplicate reads of one caption that came from overlapping windows."""
    cues.sort(key=lambda cue: (cue.get('first_seen', cue['start']), cue['box'][1], cue['box'][0]))
    merged = []
    for cue in cues:
        start, end = cue.get('first_seen', cue['start']), cue.get('disappeared_at', cue['end'])
        target, best = None, 0.0
        for kept in merged[-12:]:
            kstart, kend = kept['start'], kept['end']
            if kend < start - 1.5 or kstart > end + 1.5:
                continue
            overlap = min(end, kend) - max(start, kstart)
            if overlap <= 0.2 * min(end - start, kend - kstart):
                continue
            ratio = _similar(kept['source'], cue['source'])
            if ratio > best and ratio >= .55:
                target, best = kept, ratio
        if target is None:
            merged.append(cue)
            continue
        if len(_norm(cue['source'])) > len(_norm(target['source'])):
            target['source'] = cue['source']
        target['box'] = _union(target['box'], cue['box'])
        first = min(target['start'], start)
        last = max(target['end'], end)
        target.update(start=first, end=last, first_seen=first, disappeared_at=last,
                      visible_intervals=[[first, last]],
                      confidence=max(target.get('confidence') or 0, cue.get('confidence') or 0))
    merged.sort(key=lambda cue: (cue['start'], cue['box'][1], cue['box'][0]))
    return merged


def _move_evidence(cues, target_directory):
    evidence = target_directory / 'evidence'
    evidence.mkdir(exist_ok=True)
    for cue in cues:
        shot = cue.get('screenshot')
        if shot and Path(shot).is_file():
            destination = evidence / (cue['id'] + '.jpg')
            shutil.copyfile(shot, destination)
            cue['screenshot'] = str(destination)
        for item in (cue.get('evidence') or {}).values():
            old = item.get('path')
            if old and Path(old).is_file():
                destination = evidence / (cue['id'] + '-' + Path(old).name)
                shutil.copyfile(old, destination)
                item['path'] = str(destination)


def scan_sharded(project, emit=lambda value: None, cancel=None, start=0., end=None, config=None):
    from worker.core import Cancelled as _Cancelled
    from worker.dynamic import MODE, VERSION
    cancel = cancel or threading.Event()
    data = project.data
    config = config or {}
    count = max(1, min(8, int(config.get('shards') or 1)))
    duration = data['meta']['duration']
    end = min(duration, end if end is not None else duration)
    if not 0 <= start < end:
        raise ValueError('试处理区间无效。')
    interval = config.get('interval')

    overlaps = lambda cue: cue.get('first_seen', cue['start']) < end and cue.get('disappeared_at', cue['end']) > start
    if any(cue.get('manual') and overlaps(cue) for cue in data['cues']):
        raise ValueError('该时间段含人工校对事件，请缩小范围或创建新项目。')

    base = project.directory / 'shards'
    shutil.rmtree(base, ignore_errors=True)
    data['scan'] = {'status': 'running', 'cursor': start, 'calls': 0, 'shards': count,
                    'mode': MODE, 'version': VERSION, 'started': time.time()}
    data['task'] = {'stage': 'scan', 'status': 'running'}
    project.save(history=True)

    windows = _ranges(start, end, count)
    folders, processes = [], []
    try:
        for index, (left, right) in enumerate(windows):
            folder = base / str(index)
            _reset_copy(project.directory / 'project.sqlite', folder, interval)
            folders.append(folder)
            environment = {**os.environ, 'STUDIO_SHARD_CHILD': '1'}
            command = [sys.executable, '-m', 'worker.shard', str(folder), str(left), str(right)]
            processes.append(subprocess.Popen(command, cwd=str(ROOT), env=environment,
                                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL, **subprocess_options()))

        while any(process.poll() is None for process in processes):
            if cancel.wait(POLL):
                raise Cancelled()
            cursors = [_cursor(folder) for folder in folders]
            done = sum(1 for process in processes if process.poll() is not None)
            emit({'stage': 'scan', 'status': 'running', 'time': min(sum(cursors), end), 'total': end,
                  'count': len(data['cues']),
                  'message': f'分片扫描：{done}/{count} 片完成，最长进度 {max(cursors or [start]):.0f}s'})
        failed = [index for index, process in enumerate(processes) if process.returncode != 0]
        if failed:
            raise RuntimeError(f'分片扫描失败（第 {", ".join(str(i + 1) for i in failed)} 片），请重试或减少分片数。')

        cues = []
        for folder in folders:
            child = Project(str(folder))
            cues.extend(child.data['cues'])
            child.close()
        merged = _merge_cues(cues)
        _move_evidence(merged, project.directory)
        data['cues'] = [cue for cue in data['cues'] if not overlaps(cue)] + merged
        data['cues'].sort(key=lambda cue: (cue['start'], cue['box'][1], cue['box'][0]))
        data['scan'].update(status='complete', cursor=end, shards=count,
                            calls=sum(_calls(folder) for folder in folders))
        from worker.dynamic import check_dynamic_cues
        check_dynamic_cues(data['cues'], data['style'])
        project.save()
        return project.snapshot()
    except Cancelled:
        data['scan']['status'] = 'cancelled'
        project.save()
        raise _Cancelled()
    except Exception:
        data['scan']['status'] = 'failed'
        project.save()
        raise
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def _calls(folder):
    try:
        db = sqlite3.connect(f'file:{folder / "project.sqlite"}?mode=ro', uri=True, timeout=1)
        row = db.execute('SELECT payload FROM project WHERE id=1').fetchone()
        db.close()
        return int(json.loads(row[0]).get('scan', {}).get('calls') or 0) if row else 0
    except Exception:
        return 0


def _child_main(argv):
    folder, left, right = argv[0], float(argv[1]), float(argv[2])
    project = Project(folder)
    try:
        from worker.core import scan
        scan(project, lambda value: None, None, left, right, True)
    finally:
        project.close()


if __name__ == '__main__':
    _child_main(sys.argv[1:])
