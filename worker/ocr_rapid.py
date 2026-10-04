"""Offline RapidOCR adapter; all model files are shipped inside the wheel."""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image


def model_files():
    import rapidocr_onnxruntime
    folder = Path(rapidocr_onnxruntime.__file__).parent / 'models'
    return sorted(folder.glob('*.onnx'))


def validate_models():
    from worker.platform_runtime import ROOT
    expected = json.loads((ROOT / 'runtime/ocr-models.manifest.json').read_text('utf-8'))
    actual = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in model_files()}
    if len(actual) < 3 or actual != expected['models']:
        raise RuntimeError('OCR 模型缺失或校验失败，请重新安装处理组件。')


def main():
    # Stdout is exclusively JSON RPC. Libraries log to stderr.
    from rapidocr_onnxruntime import RapidOCR
    validate_models()
    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1,
                      det_use_cuda=False, cls_use_cuda=False, rec_use_cuda=False)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get('operation') == 'languages':
                response = {'languages': ['en-US'], 'engine': 'RapidOCR · ONNX CPU',
                            'source_language_scope': 'Windows 初版仅验证英语'}
            else:
                if request.get('language', 'en-US') != 'en-US':
                    raise ValueError('Windows 初版仅支持英语源字幕，请使用 macOS 版本处理其他语言。')
                image = Image.open(io.BytesIO(base64.b64decode(request['image']))).convert('RGB')
                # RapidOCR ndarray input follows OpenCV's BGR convention.
                result, _ = engine(np.array(image)[:, :, ::-1], text_score=.2)
                items, weak = [], []
                for polygon, text, confidence in result or []:
                    points = np.asarray(polygon, dtype=float)
                    x0,y0 = np.maximum(points.min(axis=0), [0,0])
                    x1,y1 = np.minimum(points.max(axis=0), [image.width,image.height])
                    box = [float(x0/image.width),float(y0/image.height),float((x1-x0)/image.width),float((y1-y0)/image.height)]
                    if x1 <= x0 or y1 <= y0: continue
                    if not text.strip() or confidence < .45:
                        weak.append(box)
                    else:
                        items.append({'text':text, 'confidence':float(confidence), 'box':box})
                response = {'items':items, 'unreadable_boxes':weak}
        except Exception as error:
            response = {'error':str(error)}
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
