"""Compare independent pixel fixture annotations with native OCR and rendered MP4."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from worker.core import frames,crop,probe,VisionOCR
from worker.dynamic import intersection,visible_intervals,eligible
import av
import numpy as np


def evaluate(reference,cues):
 used=set();rows=[]
 for expected in reference['events']:
  available=[c for c in cues if c['id'] not in used and c['source'].replace('\n',' ')==expected['text'].replace('\n',' ') and intersection(c['box'],expected['bubble_box'])>0 and c['start']<expected['end'] and c['end']>expected['start']]
  if not available:rows.append({'id':expected['id'],'missing':True});continue
  c=max(available,key=lambda c:intersection(c['box'],expected['bubble_box']));used.add(c['id'])
  rows.append({'id':expected['id'],'cue_id':c['id'],'source_exact':True,'start_error':abs(c['first_seen']-expected['start']),'end_error':abs(c['disappeared_at']-expected['end']),'eligible':eligible(c),'visibility':visible_intervals(c)})
 return {'reference_events':len(reference['events']),'found_events':len(used),'extra_events':[c['id'] for c in cues if c['id'] not in used],'events':rows,'maximum_start_error':max((r.get('start_error',0) for r in rows),default=0),'maximum_end_error':max((r.get('end_error',0) for r in rows),default=0)}


def verify(project,output,root):
 root=Path(root);reference=json.loads(Path('artifacts/dynamic-fixtures/reference.json').read_text());evaluation=evaluate(reference,project.data['cues']);(root/'fixture-evaluation.json').write_text(json.dumps(evaluation,indent=2))
 assert evaluation['found_events']==9 and not evaluation['extra_events'] and evaluation['maximum_start_error']<=.15 and evaluation['maximum_end_error']<=.15
 meta=probe(output);source=project.data['meta'];ocr=VisionOCR();pixels=[];background=[]
 try:
  for target in (3.75,8.,11.,13.6,15.2,18.):
   at,image=next(frames(output,target,None,.03,meta));active=[c for c in project.data['cues'] if c['start']<=at<c['end'] and eligible(c)]
   for cue in active:
    roi=cue['box'];padded=[max(0,roi[0]-.01),max(0,roi[1]-.015),min(1-roi[0]+.01,roi[2]+.02),min(1-roi[1]+.015,roi[3]+.03)]
    read=ocr.recognize(crop(image,padded),'zh-Hans');chinese=any('\u3400'<=c<='\u9fff' for c in read['text'])
    pixels.append({'time':at,'id':cue['id'],'expected':cue['translation'],'read':read['text'],'chinese_present':chinese})
  # Full blank frames must retain their original pixels, not an obsolete mask.
  for target in (.5,6.5,9.7,12.5,16.25,19.5):
   at,image=next(frames(output,target,None,.03,meta));_,original=next(frames(source['path'],at,None,.03,source));delta=float(np.mean(np.abs(image.astype(float)-original.astype(float))))
   background.append({'time':at,'mean_pixel_error':delta});assert delta<4
 finally:ocr.close()
 with av.open(str(output)) as c:video_frames=sum(1 for _ in c.decode(video=0))
 with av.open(str(output)) as c:audio_frames=sum(1 for _ in c.decode(audio=0))
 report={'output':str(Path(output).resolve()),'meta':meta,'video_frames':video_frames,'audio_frames':audio_frames,'chinese_pixel_checks':pixels,'no_caption_frame_checks':background,'evaluation':evaluation}
 (root/'fixture-media-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 assert video_frames==600 and audio_frames>0 and meta['width']==1280 and meta['height']==720 and abs(meta['duration']-20)<.05
 assert len(pixels)>=9 and all(p['chinese_present'] for p in pixels)
 return report

if __name__=='__main__':
 from worker.core import Project
 root=Path('artifacts/dynamic-20261003');p=Project(root/'fixture-project')
 try:
  print(json.dumps(evaluate(json.loads(Path('artifacts/dynamic-fixtures/reference.json').read_text()),p.data['cues']),indent=2))
 finally:p.close()
