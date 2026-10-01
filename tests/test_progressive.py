import copy
import json
from pathlib import Path
import threading
import pytest
from worker.core import Project, ROOT, scan, Cancelled, write_ass
from worker.progressive import Tracker, relation


def observe(tracker, at, text, confidence=.99):
 return tracker.observe(at, {'text':text,'confidence':confidence}, [.04,.76,.92,.21])


def test_growth_pause_and_single_frame_dropouts_recover_one_complete_sentence():
 tracker=Tracker();out=[]
 for t,text in [(1,'Hello'),(1.2,'Hello'),(1.4,'Hello world'),(1.6,'Hello world'),(1.8,'Hello'),(1.88,'Hello world!'),(2.08,'Hello world!'),(2.3,''),(2.5,'')]:out.extend(observe(tracker,t,text))
 assert len(out)==1
 assert out[0]['source']=='Hello world!'
 assert out[0]['complete_time']==1.4
 assert out[0]['complete_evidence_text']=='Hello world'
 assert out[0]['first_seen']==.96
 assert out[0]['end']==2.26


def test_restart_same_prefix_and_repeat_after_blank_are_separate_events():
 tracker=Tracker();out=[]
 for t,text in [(1,'Save'),(1.2,'Save before exporting.'),(1.4,'Save before exporting.'),(2,'Save'),(2.16,'Save after'),(2.4,'Save after exporting.'),(2.6,'Save after exporting.'),(3,''),(3.2,''),(4,'Save after exporting.'),(4.2,'Save after exporting.'),(5,''),(5.2,'')]:out.extend(observe(tracker,t,text))
 assert [c['source'] for c in out]==['Save before exporting.','Save after exporting.','Save after exporting.']
 assert out[0]['end']==1.96
 assert out[1]['start']==1.96
 assert len(set(c['id'] for c in out))==3


def test_numbers_negation_and_one_frame_long_garbage_are_not_silently_merged():
 assert relation('We need 12, not 20.','We need 20, not 20.')=='change'
 assert relation('Do not overwrite.','Do overwrite.')=='change'
 tracker=Tracker();out=[]
 for t,text in [(1,'Hello'),(1.2,'Hello world.'),(1.4,'Hello world.'),(1.6,'Hello world. random OCR hallucination'),(1.68,'Hello world.'),(1.88,'Hello world.'),(2,''),(2.2,'')]:out.extend(observe(tracker,t,text))
 assert len(out)==1 and out[0]['source']=='Hello world.'
 assert out[0]['complete_supported']


def test_unstable_final_fragment_is_explicitly_pending_review():
 tracker=Tracker();observe(tracker,1,'Partial')
 result=tracker.finish(1.1)[0]
 assert not result['complete_supported'] and result['complete_time'] is None
 assert '完整文本缺少' in result['recognition_issue']


def test_tracker_checkpoint_restores_growth_and_pending_sentence():
 tracker=Tracker()
 for t,text in [(1,'Hello'),(1.2,'Hello world.'),(1.4,'Hello world.'),(2,'Good')]:observe(tracker,t,text)
 restored=Tracker(json.loads(json.dumps(tracker.state)))
 closed=observe(restored,2.16,'Good morning.')
 assert len(closed)==1 and closed[0]['source']=='Hello world.'
 observe(restored,2.4,'Good morning.')
 assert restored.finish(3)[0]['source']=='Good morning.'


def test_legacy_default_and_modes_preserve_separate_manual_results(tmp_path):
 p=Project.create(ROOT/'artifacts/fixtures/硬字幕 测试视频.mp4',tmp_path/'project')
 p.data.pop('recognition_mode');p.data.pop('recognition_results')
 p.data['cues']=[{'id':'standard','source':'original','translation':'人工译文','manual':True,'manual_translation':True,'start':1.,'end':2.,'issues':[]}]
 p.data['scan']={'key':'standard','cursor':10,'status':'cancelled'};p.save()
 assert p.snapshot()['recognition_mode']=='standard'
 p.update({'recognition_mode':'progressive'})
 assert not p.data['cues']
 p.data['cues']=[{'id':'progressive','source':'Hello','translation':'扩展译文','manual':True,'start':3.,'end':4.,'issues':[]}];p.save()
 p.update({'recognition_mode':'standard'})
 assert p.data['cues'][0]['id']=='standard' and p.data['scan']['cursor']==10
 p.close();p=Project(tmp_path/'project')
 p.update({'recognition_mode':'progressive'})
 assert p.data['cues'][0]['translation']=='扩展译文'
 before=copy.deepcopy(p.data)
 with pytest.raises(ValueError):p.update({'recognition_mode':'bad'})
 assert p.data==before
 p.close()


def test_display_complete_keeps_cover_start_and_manual_times(tmp_path):
 p=Project.create(ROOT/'artifacts/fixtures/硬字幕 测试视频.mp4',tmp_path/'project')
 p.update({'recognition_mode':'progressive'})
 tracker=Tracker()
 for t,text in [(1,'Hello'),(2,'Hello world.'),(2.2,'Hello world.')]:observe(tracker,t,text)
 cue=tracker.finish(4)[0];cue['translation']='你好，世界。';p.data['cues']=[cue];p.save()
 p.update({'progressive':{'display':'complete'}})
 assert cue['start']==2 and cue['original_start']==.96
 ass=tmp_path/'render.ass';write_ass(p,ass)
 text=ass.read_text();assert 'Dialogue: 0,0:00:00.76' in text and 'Dialogue: 1,0:00:02.00' in text
 p.edit_cue(cue['id'],{'start':2.5})
 p.update({'progressive':{'display':'first'}})
 assert cue['start']==2.5
 p.close()


def test_confirmed_number_and_negation_rewrites_start_distinct_events():
 tracker=Tracker();out=[]
 phrases=['We need 12, not 20.','We need 20, not 20.','Do not overwrite.','Do overwrite.']
 for i,text in enumerate(phrases):
  out.extend(observe(tracker,1+i,text));out.extend(observe(tracker,1.2+i,text))
 out.extend(observe(tracker,5,''));out.extend(observe(tracker,5.2,''))
 assert [cue['source'] for cue in out]==phrases
