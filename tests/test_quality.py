import copy
import json
import threading
from pathlib import Path
import pytest
from worker.core import Project,ROOT,scan,Cancelled
from worker.quality import QualityTracker,select_body,quality_record,best_supported
from worker.progressive import new_event

ROI=[.04,.76,.92,.21]
def obs(tracker,t,text,confidence=.99,alternatives=None):
 return tracker.observe(t,{'text':text,'confidence':confidence,'alternatives':alternatives or []},ROI)
def run(rows):
 tracker=QualityTracker();out=[]
 for t,text in rows:out.extend(obs(tracker,t,text))
 out.extend(tracker.finish(rows[-1][0]+.1));return out


def test_layout_removes_name_and_side_options_not_short_body():
 result={'items':[{'text':'Name','box':[.45,.15,.1,.12],'confidence':1},{'text':'Choice','box':[.8,.02,.19,.12],'confidence':1},{'text':'No.','box':[.45,.62,.1,.15],'confidence':.9}]}
 body=select_body(result,ROI)
 assert body['text']=='No.' and len(body['excluded_items'])==2
 assert not select_body({'items':result['items'][:2]},ROI)['text']
 assert select_body(result,ROI,{'layout':'all'})['text']=='Choice\nName\nNo.'
 excluded=[.04+.92*.4,.76+.21*.5,.92*.2,.21*.4]
 assert not select_body(result,ROI,{'exclusions':[excluded]})['text']


def test_cursor_and_fade_do_not_create_extra_events():
 rows=[(1,'Hopefully'),(1.1,'Hopefully it'),(1.2,"Hopefully it won't take long."),(1.3,"Hopefully it won't take long."),(1.4,"Hopefully it won't take long."),(1.5,"Hopefully it won't take long. )"),(1.6,"Hopefully it won't take long."),(1.7,"Hopefully it won't take long. )"),(1.8,"Hopefully it won't take long."),(1.9,"Honefully it won't take lona."),(2.,"Honefully it won't take lona."),(2.1,"Hopefully it won't take long."),(2.2,''),(2.5,'')]
 cues=run(rows)
 assert len(cues)==1 and cues[0]['source']=="Hopefully it won't take long."
 assert cues[0]['quality_support']>=3


def test_reliable_parent_beats_long_garbage_and_preserves_real_punctuation():
 cues=run([(1,'Hello'),(1.1,'Hello world.'),(1.2,'Hello world.'),(1.3,'Hello world.'),(1.4,'Hello world.'),(1.5,'Hello world. random garbage'),(1.6,'Hello world. random garbage'),(1.7,'Hello world.'),(1.8,''),(2.1,'')])
 assert len(cues)==1 and cues[0]['source']=='Hello world.'
 cues=run([(1,'Use (12)'),(1.1,'Use (12)'),(1.2,'Use (12)'),(1.3,''),(1.6,'')])
 assert cues[0]['source']=='Use (12)'


def test_same_prefix_restart_repeated_event_and_protected_rewrites():
 rows=[]
 phrases=['Save before exporting.','Save after exporting.','We need 12, not 20.','We need 20, not 20.','Do not overwrite.','Do overwrite.']
 for i,text in enumerate(phrases):
  start=1+i
  rows.extend([(start,text.split()[0]),(start+.1,text),(start+.2,text),(start+.35,text),(start+.5,text),(start+.7,text)])
 rows.extend([(7,''),(7.3,''),(8,'Do overwrite.'),(8.1,'Do overwrite.'),(8.2,'Do overwrite.'),(8.4,''),(8.7,'')])
 assert [c['source'] for c in run(rows)]==phrases+['Do overwrite.']


def test_alternate_scale_is_not_an_independent_frame_vote():
 event=new_event(1,ROI)
 for _ in range(3):quality_record(event,1,{'text':'Hello.','confidence':1,'alternatives':[{'text':'Hello.','confidence':1,'method':'scaled'}]})
 assert event['variants']['Hello.']['count']==1
 t=QualityTracker({'active':event,'pending':None,'blank_since':None})
 assert not t.finish(2)[0]['complete_supported']


def test_checkpoint_roundtrip_has_same_output():
 tracker=QualityTracker()
 for t,text in [(1,'Hello'),(1.1,'Hello world.'),(1.2,'Hello world.'),(1.3,'Hello world.'),(2,'Good')]:obs(tracker,t,text)
 restored=QualityTracker(json.loads(json.dumps(tracker.state)))
 for t,text in [(2.1,'Good morning.'),(2.2,'Good morning.'),(2.4,'Good morning.')]:
  assert obs(tracker,t,text)==obs(restored,t,text)
 assert tracker.finish(3)==restored.finish(3)


def test_three_modes_manual_results_and_invalid_config_are_atomic(tmp_path):
 p=Project.create(ROOT/'artifacts/fixtures/硬字幕 测试视频.mp4',tmp_path/'p')
 for mode in ['standard','progressive','progressive_hq']:
  p.update({'recognition_mode':mode});p.data['cues']=[{'id':mode,'source':mode,'translation':'人工','manual':True,'manual_translation':True,'start':1.,'end':2.,'issues':[]}];p.save()
 for mode in ['standard','progressive','progressive_hq']:
  p.update({'recognition_mode':mode});assert p.data['cues'][0]['id']==mode
 prior=copy.deepcopy(p.data)
 with pytest.raises(ValueError):p.update({'quality':{'layout':'dialogue','exclusions':[[.9,.9,.3,.3]]}})
 assert p.data==prior
 with pytest.raises(ValueError):scan(p,start=1,end=2,force=True)
 assert p.data==prior
 p.close()


def test_correlated_blinking_cursor_is_excluded_without_stripping_literals():
 rows=[(1,'Complete.'),(1.1,'Complete.'),(1.2,'Complete.'),(1.3,'Complete. |'),(1.4,'Complete. |'),(1.5,'Complete. |'),(1.6,'Complete.'),(1.7,'Complete.'),(1.8,'Complete. |'),(1.9,'Complete. |'),(2.,'Complete. |'),(2.1,'Complete.'),(2.2,''),(2.5,'')]
 assert run(rows)[0]['source']=='Complete.'
 assert run([(1,'Use x | y.'),(1.1,'Use x | y.'),(1.2,'Use x | y.'),(1.4,''),(1.7,'')])[0]['source']=='Use x | y.'


def test_short_distinct_caption_before_blank_is_kept_for_review():
 cues=run([(1,'First caption.'),(1.1,'First caption.'),(1.2,'First caption.'),(2,'Stop!'),(2.1,'Stop!'),(2.2,''),(2.5,'')])
 assert [c['source'] for c in cues]==['First caption.','Stop!']
 assert not cues[1]['complete_supported']


def test_corrupt_prefix_and_misread_cursor_then_growth_stay_one_caption():
 for prefix,body in [('Hi-yes, yes|',"Hi-yes, yes! I will finish the work perfectly!"),('Do you l','Do you remember our plan?'),('W','I wonder what is happening.')]:
  cues=run([(1,prefix),(1.1,prefix),(1.2,prefix),(1.3,body),(1.4,body),(1.5,body),(1.6,body),(1.8,''),(2.1,'')])
  assert len(cues)==1 and cues[0]['source']==body


def test_scan_cancel_resume_retains_evidence_and_matches_uninterrupted(tmp_path,monkeypatch):
 import numpy as np
 import worker.quality as quality
 rows=[(1.,'Hello'),(1.1,'Hello world.'),(1.2,'Hello world.'),(1.3,'Hello world.'),(1.4,'Hello world.'),(1.5,''),(1.6,''),(1.7,''),(1.8,'Good'),(1.9,'Good morning.'),(2.,'Good morning.'),(2.1,'Good morning.'),(2.2,'Good morning.'),(2.3,''),(2.4,''),(2.5,''),(2.6,'')]
 stop=threading.Event();interrupt=[True]
 class OCR:
  def __init__(self):self.calls=0
  def request(self,payload):return {'languages':['en-US']}
  def recognize_quality(self,pixels,*args):
   self.calls+=1;i=int(pixels[0,0,0]);t,text=rows[i]
   if interrupt[0] and t==1.2:stop.set()
   return {'text':text,'confidence':1,'items':[],'alternatives':[]}
  def close(self):pass
 def pixel_frames(path,start,stop_at,interval,meta):
  for i,(t,text) in enumerate(rows):
   if start<=t<stop_at:yield t,np.full((200,300,3),i,dtype=np.uint8)
 monkeypatch.setattr(quality,'QualityOCR',OCR);monkeypatch.setattr(quality,'frames',pixel_frames)
 p=Project.create(ROOT/'artifacts/fixtures/硬字幕 测试视频.mp4',tmp_path/'resume');p.update({'recognition_mode':'progressive_hq'})
 with pytest.raises(Cancelled):scan(p,cancel=stop,start=1,end=2.7)
 assert p.data['scan']['status']=='cancelled' and p.data['scan']['tracker']['active']['variants']
 p.close();p=Project(tmp_path/'resume');stop.clear();interrupt[0]=False;scan(p,cancel=stop,start=1,end=2.7)
 q=Project.create(ROOT/'artifacts/fixtures/硬字幕 测试视频.mp4',tmp_path/'whole');q.update({'recognition_mode':'progressive_hq'});scan(q,start=1,end=2.7)
 fields=lambda project:[(c['source'],c['start'],c['end'],c['complete_time'],c['quality_support']) for c in project.data['cues']]
 assert fields(p)==fields(q) and len(p.data['cues'])==2
 p.close();q.close()


def test_final_misread_negation_word_can_complete_but_real_rewrite_stays_split():
 body="We need to save the changes, and don't overwrite the source."
 cues=run([(1,"We need to save the changes, and don'l"),(1.1,"We need to save the changes, and don'l"),(1.2,"We need to save the changes, and don'l"),(1.3,body),(1.4,body),(1.5,body),(1.7,''),(2.,'')])
 assert len(cues)==1 and cues[0]['source']==body


def test_auto_layout_handles_scene_change_and_wrapped_upper_body():
 names=[];config={'layout':'auto','_speaker_keys':names}
 item=lambda text,box:{'text':text,'box':box,'confidence':.99}
 assert select_body({'items':[item('Speaker',[.46,.1,.08,.12]),item('First sentence.',[.3,.6,.4,.14])]},ROI,config)['text']=='First sentence.'
 assert names==['speaker']
 assert not select_body({'items':[item('Speaker',[.46,.1,.08,.12])]},ROI,config)['text']
 assert select_body({'items':[item('Now we are here.',[.2,.2,.6,.14])]},ROI,config)['text']=='Now we are here.'
 body=select_body({'items':[item('This is a long wrapped paragraph',[.1,.3,.8,.14]),item('continued on another long line.',[.1,.55,.8,.14])]},ROI,config)
 assert body['text']=='This is a long wrapped paragraph\ncontinued on another long line.'
