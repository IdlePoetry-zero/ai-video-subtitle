"""Inspect actual exported pixels, subtitle intervals, streams and decoded audio."""
import json
import sys
from pathlib import Path
import numpy as np
import av
from PIL import Image, ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from worker.core import frames, probe, VisionOCR, ROOT, Project, recommend
run = Path(sys.argv[1]) if len(sys.argv)>1 else sorted(path for path in (ROOT/'artifacts').glob('desktop-*') if (path/'result.json').exists())[-1]
result=json.loads((run/'result.json').read_text())
output=next(Path(p) for p in result['outputs'] if 'ui-export' in p and p.endswith('.mp4'))
source=ROOT/'artifacts/fixtures/硬字幕 测试视频.mp4'
folder=run/'media-check';folder.mkdir(exist_ok=True)
ocr=VisionOCR();rows=[];images=[]
try:
    for target in [1,2.02,3,5.3,21.44,26,32,58]:
        timestamp,pixels=next(frames(output,target,None,0))
        image=Image.fromarray(pixels);image.save(folder/f'{target}.jpg')
        # Only the caption strip; exclude the unrelated title at the top.
        crop=pixels[545:710]
        chinese=ocr.recognize(crop,'zh-Hans')['text']
        english=ocr.recognize(crop,'en-US')['text']
        rows.append({'requested':target,'pts':timestamp,'chinese_ocr':chinese,'english_ocr':english})
        preview=image.resize((640,360));images.append(preview)
    assert not rows[0]['chinese_ocr'] and not rows[5]['chinese_ocr']
    assert '欢迎' in rows[2]['chinese_ocr']
    assert len(rows[6]['chinese_ocr'].splitlines()) >= 2
    assert 'Read both lines' not in rows[6]['english_ocr']
finally: ocr.close()
def audio_data(file):
    with av.open(str(file)) as c:
        stream=c.streams.audio[0]
        decoded=list(c.decode(stream))
        start=float(decoded[0].pts*decoded[0].time_base)
        end=float(decoded[-1].pts*decoded[-1].time_base)+decoded[-1].samples/decoded[-1].sample_rate
        data=np.concatenate([frame.to_ndarray().reshape(-1) for frame in decoded])
        return start,end,data
sa,ea,a=audio_data(source);sb,eb,b=audio_data(output)
size=min(len(a),len(b),48000)
correlation=float(np.corrcoef(a[:size],b[:size])[0,1])
assert correlation>.95
assert abs(sa-sb)<.05 and abs(ea-eb)<.05
meta=probe(output);assert meta['width']==1280 and meta['height']==720 and meta['audio']
assert abs(meta['duration']-probe(source)['duration'])<.05
sheet=Image.new('RGB',(1280,4*390),(16,24,32));draw=ImageDraw.Draw(sheet)
for i,img in enumerate(images):
    x=(i%2)*640;y=(i//2)*390;sheet.paste(img,(x,y+25));draw.text((x+10,y+5),f"{rows[i]['pts']:.2f}s",fill='white')
sheet.save(folder/'contact-sheet.jpg')
p=Project(result['directory'])
try: region=recommend(p)
finally:p.close()
assert region['found'] and region['roi'][1]>.55
report={'passed':True,'video':str(output),'metadata':meta,'frames':rows,'audio':{'source_start':sa,'export_start':sb,'source_end':ea,'export_end':eb,'correlation_first_second':correlation},'recommended_region':region,'limitations':'Test tone and stream timestamps verify sample synchrony, not arbitrary dialogue or HDR.'}
(folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'passed':True,'audio_correlation':correlation,'source_audio_end':ea,'export_audio_end':eb,'recommended_region':region},ensure_ascii=False))
