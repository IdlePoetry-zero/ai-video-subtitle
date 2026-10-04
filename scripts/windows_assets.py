"""Download only the pinned redistributable font; OCR models are in pinned wheel."""
from pathlib import Path
import hashlib
import importlib.metadata as metadata
import json
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
FONT_COMMIT = '523d033d6cb47f4a80c58a35753646f5c3608a78'
FONT_HASH = '2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b'


def download(relative, remote, expected=None):
    target = ROOT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        data = urllib.request.urlopen(remote, timeout=90).read()
        if expected and hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError('公开资源校验失败：' + relative)
        target.write_bytes(data)
    if expected and hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        raise RuntimeError('已有资源校验失败：' + relative)


def main():
    prefix = f'https://raw.githubusercontent.com/notofonts/noto-cjk/{FONT_COMMIT}/'
    download('runtime/fonts/NotoSansCJKsc-Regular.otf', prefix + 'Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf', FONT_HASH)
    download('runtime/fonts/OFL.txt', prefix + 'LICENSE')
    manifest = ROOT / 'config/windows-ocr-manifest.json'
    shutil.copyfile(manifest, ROOT / 'runtime/ocr-models.manifest.json')
    from worker.ocr_rapid import validate_models
    validate_models()
    folder = ROOT / 'runtime/licenses'
    folder.mkdir(exist_ok=True)
    sbom = []
    for dist in sorted(metadata.distributions(), key=lambda d:d.metadata['Name'].lower()):
        name = dist.metadata['Name']
        sbom.append({'name':name,'version':dist.version,'license':dist.metadata.get('License-Expression') or dist.metadata.get('License'),
                     'urls':dist.metadata.get_all('Project-URL', [])})
        for file in dist.files or []:
            if '.dist-info/' in str(file) and any(token in Path(file).name.lower() for token in ['license','copying','notice']):
                source = dist.locate_file(file)
                if source.is_file():
                    shutil.copyfile(source, folder / (name + '-' + str(file).replace('/', '_').replace('\\', '_')))
    (folder/'python-dependencies.json').write_text(json.dumps(sbom,ensure_ascii=False,indent=2),encoding='utf-8')
    # Wheel model conversion preserves PaddleOCR's Apache-2.0 attribution.
    download('runtime/licenses/RapidOCR-APACHE-2.0.txt', 'https://raw.githubusercontent.com/RapidAI/RapidOCR/v1.4.4/LICENSE')
    download('runtime/licenses/PaddleOCR-APACHE-2.0.txt', 'https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/v2.7.3/LICENSE')
    python_tag = '.'.join(map(str,sys.version_info[:3]))
    download('runtime/licenses/Python-PSF.txt', f'https://raw.githubusercontent.com/python/cpython/v{python_tag}/LICENSE')
    for name in ['GPLv2','GPLv3','LGPLv2.1']:
        download('runtime/licenses/' + name + '.txt', 'https://raw.githubusercontent.com/FFmpeg/FFmpeg/n7.1/COPYING.' + name)
    import av
    (folder/'pyav-build.json').write_text(json.dumps({'version':av.__version__,'libraries':av.library_versions},indent=2),encoding='utf-8')
    import imageio_ffmpeg
    ffmpeg = subprocess.check_output([imageio_ffmpeg.get_ffmpeg_exe(),'-version'],text=True,encoding='utf-8')
    (folder/'ffmpeg-build.txt').write_text(ffmpeg,encoding='utf-8')
    (ROOT/'runtime/THIRD_PARTY_NOTICES.txt').write_text('''Windows evaluation build includes:
RapidOCR 1.4.4 (Apache-2.0), PP-OCRv4 models from PaddleOCR (Apache-2.0).
ONNX Runtime CPU (MIT), Python and dependencies (see licenses/python-dependencies.json).
Noto Sans CJK SC font (SIL OFL 1.1, see fonts/OFL.txt).
Electron/Chromium licenses are in the application root.
imageio-ffmpeg supplies FFmpeg including libx264. The FFmpeg binary is GPL-licensed;
see licenses/ffmpeg-build.txt for its exact version, configuration and build details.
Source and build references: https://github.com/imageio/imageio-ffmpeg/tree/v0.6.0/binaries
https://github.com/BtbN/FFmpeg-Builds and https://ffmpeg.org/download.html
https://code.videolan.org/videolan/x264
Retain these notices and upstream licenses when redistributing the evaluation package.
''',encoding='utf-8')
    print('Pinned offline OCR models, font and notices prepared.')


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT))
    main()
