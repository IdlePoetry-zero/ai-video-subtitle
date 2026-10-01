"""Verify actual extension outputs under both whole-sentence display policies."""
import json
from pathlib import Path
import sys
import time
import numpy as np
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from worker.core import ROOT, Project, VisionOCR, frames, export_video, probe, translate
run=Path(sys.argv[1]) if len(sys.argv)>1 else sorted(p for p in (ROOT/'artifacts').glob('progressive-desktop-*') if (p/'result.json').exists())[-1]
result=json.loads((run/'result.json').read_text());project=Project(result['directory'])
folder=run/'media-check';folder.mkdir(exist_ok=True)
actual=next(Path(p) for p in result['outputs'] if 'ui-export' in p and p.endswith('.mp4'))
# Separate read/write project copy for first-seen preview; never change UI acceptance project.
comparison=Project.create(project.data['meta']['path'], folder/f'first-policy-project-{time.time_ns()}')
comparison.update({'recognition_mode':'progressive'})
comparison.data['cues']=json.loads(json.dumps(project.data['cues']))
for cue in comparison.data['cues']:cue['manual_time']=False;cue['manual']=False
comparison.save();comparison.update({'progressive':{'display':'first'}})
first_output=comparison.directory/'first-policy-preview.mp4'
export_video(comparison,first_output,start=0,end=6)
comparison.close()
ocr=VisionOCR();rows=[];images=[]
try:
 for file,target,label in [(actual,.5,'blank before'),(actual,2,'growing, wait for complete'),(first_output,2,'growing, show full Chinese from first'),(actual,4,'full sentence'),(actual,6.5,'blank gap'),(actual,23,'two lines'),(actual,30.2,'next caption already covered'),(actual,52,'same-prefix next caption')]:
  t,pixels=next(frames(file,target,None,0));image=Image.fromarray(pixels);image.save(folder/f'{len(rows)}-{target}.jpg')
  strip=pixels[545:710]
  zh=ocr.recognize(strip,'zh-Hans')['text'];en=ocr.recognize(strip,'en-US')['text']
  rows.append({'label':label,'pts':t,'chinese_ocr':zh,'english_ocr':en});images.append(image.resize((640,360)))
 assert not rows[0]['chinese_ocr'] and not rows[1]['chinese_ocr']
 assert '欢迎' in rows[2]['chinese_ocr'] and '欢迎' in rows[3]['chinese_ocr']
 assert not rows[4]['chinese_ocr']
 assert len(rows[5]['chinese_ocr'].splitlines())>=2
 assert not rows[6]['chinese_ocr']
 assert 'Hello' not in rows[1]['english_ocr'] and 'Welcome' not in rows[1]['english_ocr']
 assert '导出之后' in rows[7]['chinese_ocr']
 # Inspect original text pixels at exact first and last reference frames.
 reference=json.loads((ROOT/'artifacts/progressive-fixtures/reference.json').read_text())
 edges=[]
 for truth in reference:
  for target in (truth['start'],truth['end']-.04):
   t,pixels=next(frames(actual,target,None,0))
   # End frames may still contain Chinese, so use English OCR and exact pixel
   # background at each known original-text row rather than rejecting all text.
   source_pixels=next(frames(ROOT/'artifacts/progressive-fixtures/逐步出现字幕 测试.mp4',target,None,0))[1]
   for y1,y2 in [(640,690),(580,640)]:
    original=source_pixels[y1:y2,70:1200]
    rendered=pixels[y1:y2,70:1200]
    bright=(original.min(axis=2)>200)
    if not bright.any():continue
    # Original white text pixels must have been changed by the opaque mask;
    # unrelated Chinese glyph coincidences are limited to a small fraction.
    unchanged=np.all(np.abs(rendered.astype(int)-original.astype(int))<12,axis=2)&bright
    fraction=float(unchanged.sum()/bright.sum())
    assert fraction<.15,(target,y1,fraction)
    edges.append({'pts':t,'row':y1,'original_text_pixels_unchanged':fraction})
finally:ocr.close();project.close()
sheet=Image.new('RGB',(1280,1560),(16,24,32));draw=ImageDraw.Draw(sheet)
for i,image in enumerate(images):
 x=(i%2)*640;y=(i//2)*390;sheet.paste(image,(x,y+25));draw.text((x+10,y+5),f'{rows[i]["pts"]:.2f}s {rows[i]["label"]}',fill='white')
sheet.save(folder/'contact-sheet.jpg')
meta=probe(actual);source=probe(ROOT/'artifacts/progressive-fixtures/逐步出现字幕 测试.mp4')
assert meta['width']==1280 and meta['height']==720 and meta['audio']
assert abs(meta['duration']-source['duration'])<.05
(folder/'result.json').write_text(json.dumps({'passed':True,'metadata':meta,'first_policy_preview':str(first_output),'frames':rows,'edge_mask_checks':edges},ensure_ascii=False,indent=2))
print('Actual pixels verified: blank gaps, complete-policy waiting coverage, first-policy full Chinese, two lines and direct replacement')
