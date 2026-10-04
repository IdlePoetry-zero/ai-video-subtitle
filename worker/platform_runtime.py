"""Small OS boundary shared by all recognition modes."""
from pathlib import Path
import hashlib
import json
import os
import queue
import sys
import threading

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
