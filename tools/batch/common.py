"""Shared helpers for the batch tools: worker RPC, project access, text utilities.

The batch tools drive the same JSONL worker protocol the desktop app uses, so no
desktop window is needed.  Everything is path-relative: the repository root is
derived from this file, and every path can be overridden from the command line.
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKDIR = ROOT / 'runtime' / 'projects'


@contextlib.contextmanager
def repo_cwd():
    """Run a block from the repository root (the OCR helper is imported as a module)."""
    previous = os.getcwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(previous)


class WorkerError(RuntimeError):
    pass


class Worker:
    """One worker process; requests are serialised by the protocol itself."""

    def __init__(self, root: Path = ROOT):
        environment = {**os.environ, 'PYTHONUTF8': '1'}
        self.process = subprocess.Popen(
            [sys.executable, 'worker/server.py'], cwd=str(root), env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', bufsize=1)
        self.counter = 0
        self._progress = threading.Event()

    def call(self, method: str, params: dict | None = None):
        self.counter += 1
        payload = {'id': self.counter, 'method': method, 'params': params or {}}
        self.process.stdin.write(json.dumps(payload) + '\n')
        self.process.stdin.flush()
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise WorkerError('worker 已退出')
            value = json.loads(line)
            if value.get('event'):
                if not self._progress.is_set():
                    self._progress.set()
                continue
            if value.get('id') != self.counter:
                continue
            if 'error' in value:
                raise WorkerError(value['error'])
            return value.get('result')

    def wait_job(self, quiet: bool = True):
        """Block until a job event arrives; returns (status, project, error)."""
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise WorkerError('worker 已退出')
            value = json.loads(line)
            if not value.get('event'):
                continue
            if value['event'] == 'progress':
                if not quiet:
                    stamp = value.get('time') or value.get('count') or 0
                    print(f"    [{stamp:8.1f}] {value.get('message', '')}", flush=True)
                continue
            if value['event'] == 'job':
                return value.get('status'), value.get('project'), value.get('error')

    def close(self):
        try:
            self.process.stdin.close()
        except Exception:
            pass
        self.process.wait(timeout=10)


def project_path(name_or_path: str, workdir: Path = DEFAULT_WORKDIR) -> Path:
    candidate = Path(name_or_path)
    if candidate.is_dir():
        return candidate
    for folder in (workdir / name_or_path, ROOT / 'runtime' / 'projects' / name_or_path):
        if folder.is_dir():
            return folder
    raise SystemExit(f'找不到项目目录：{name_or_path}（默认工作目录 {workdir}）')


def load_project(folder: Path) -> dict:
    database = sqlite3.connect(f'file:{folder / "project.sqlite"}?mode=ro', uri=True, timeout=10)
    try:
        row = database.execute('SELECT payload FROM project WHERE id=1').fetchone()
    finally:
        database.close()
    if not row:
        raise SystemExit(f'{folder} 不是有效项目目录')
    return json.loads(row[0])


def save_project(folder: Path, data: dict) -> None:
    database = sqlite3.connect(folder / 'project.sqlite')
    try:
        database.execute('INSERT OR REPLACE INTO project VALUES(1,?)',
                         (json.dumps(data, ensure_ascii=False),))
        database.commit()
    finally:
        database.close()


def normalize(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', text or '').split()).casefold()


def similar(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.92
    return SequenceMatcher(None, a, b).ratio()


def union(a, b):
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return [x0, y0, x1 - x0, y1 - y0]


def clamp_box(box, pad_x: float = 0.0, pad_y: float = 0.0,
              min_w: float = 0.0, min_h: float = 0.0):
    x, y, w, h = box
    width = max(w + pad_x * 2, min_w)
    height = max(h + pad_y * 2, min_h)
    center_x, center_y = x + w / 2, y + h / 2
    left = min(max(0.0, center_x - width / 2), 1.0 - width)
    top = min(max(0.0, center_y - height / 2), 1.0 - height)
    return [round(left, 5), round(top, 5), round(width, 5), round(height, 5)]


def api_key(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    environment = os.environ.get('SUBTITLE_API_KEY') or os.environ.get('OPENAI_API_KEY')
    if environment:
        return environment
    for candidate in (ROOT / 'runtime' / '.apikey', ROOT / '.apikey'):
        if candidate.is_file():
            return candidate.read_text(encoding='utf-8').strip()
    raise SystemExit('缺少翻译密钥：请用 --api-key、环境变量 SUBTITLE_API_KEY 或 runtime/.apikey 提供。')


def format_seconds(value: float) -> str:
    return f'{int(value // 60):02d}:{value % 60:05.2f}'
