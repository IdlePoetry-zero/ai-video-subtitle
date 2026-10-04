"""Small OS boundary shared by all recognition modes."""
from pathlib import Path
import hashlib
import json
import os
import queue
import sys
import threading
import subprocess
import time

ROOT = Path(os.environ.get('STUDIO_RESOURCE_ROOT', Path(__file__).resolve().parent.parent))


def rapid_ocr():
    return sys.platform == 'win32' or os.environ.get('STUDIO_OCR_ENGINE') == 'rapidocr'


def ocr_identity():
    if not rapid_ocr():
        return 'vision-accurate-v3'
    manifest = ROOT / 'runtime/ocr-models.manifest.json'
    if not manifest.is_file():
        raise RuntimeError('缺少 OCR 模型清单，请重新安装 Windows 处理组件。')
    return 'rapidocr-onnx-1.4.4-' + hashlib.sha256(manifest.read_bytes()).hexdigest()


def chinese_font():
    if rapid_ocr():
        font = ROOT / 'runtime/fonts/NotoSansCJKsc-Regular.otf'
        family = 'Noto Sans CJK SC'
    else:
        font = Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
        family = 'Arial Unicode MS'
    if not font.is_file():
        raise ValueError('缺少随应用提供的中文字体，请重新安装或运行环境配置。')
    return font, family


def subprocess_options():
    return {'creationflags': 0x08000000} if sys.platform == 'win32' else {}


_external_launch_lock = threading.Lock()


def external_process(command, **kwargs):
    """FFmpeg must not inherit the frozen Python DLL search path or RPC stdin."""
    kwargs.setdefault('stdin',subprocess.DEVNULL)
    kwargs.update(subprocess_options())
    if sys.platform != 'win32' or not getattr(sys,'frozen',False):
        return subprocess.Popen(command,**kwargs)
    import ctypes
    with _external_launch_lock:
        ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            environment=os.environ.copy()
            bundled=str(Path(sys._MEIPASS).resolve()).casefold()
            environment['PATH']=os.pathsep.join(p for p in environment.get('PATH','').split(os.pathsep)
                                               if not str(Path(p).resolve()).casefold().startswith(bundled))
            return subprocess.Popen(command,env=environment,**kwargs)
        finally:
            ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))


def remove_temporary(path):
    # Windows scanners/codec processes may retain a just-closed file briefly.
    for attempt in range(10):
        try:
            path.unlink(missing_ok=True)
            return True
        except PermissionError:
            if sys.platform != 'win32': raise
            time.sleep(.1)
    return False


class LineReader:
    """One persistent reader avoids select() on Windows pipes and buffers lines."""
    def __init__(self, stream):
        self.queue = queue.Queue()
        def read():
            try:
                for line in stream:
                    self.queue.put(line)
            finally:
                self.queue.put(None)
        self.thread = threading.Thread(target=read, daemon=True)
        self.thread.start()

    def get(self, timeout):
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return ''
