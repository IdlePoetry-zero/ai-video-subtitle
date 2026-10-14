import copy
import json
import threading
from pathlib import Path

import numpy as np
import pytest
from worker.core import Project,ROOT,scan,translate,Cancelled,write_ass,export_srt
from worker.dynamic import (DynamicTracker,group_items,visible_intervals,eligible,layout,
                            merge_objects,split_time,check_dynamic_cues)

LEFT=[.08,.16,.31,.07];RIGHT=[.60,.64,.30,.07]
VIDEO=ROOT/'artifacts/fixtures/硬字幕 测试视频.mp4'

def group(text,box=LEFT,confidence=.99):
 return {'text':text,'box':list(box),'confidence':confidence,'items':[{'text':text,'box':list(box),'confidence':confidence}]}

def run(rows,end=None):
 tracker=DynamicTracker();out=[]
 for t,items in rows:out.extend(tracker.observe(t,items))
 out.extend(tracker.finish(end or rows[-1][0]+.1));return sorted(out,key=lambda c:c['start'])

def cue(text='Hello world.',box=LEFT,start=1):
 return run([(start,[group(text,box)]),(start+.1,[group(text,box)]),(start+.2,[group(text,box)])],start+.3)[0]


def test_grouping_separates_columns_and_combines_only_close_rows():
 item=lambda text,box:{'text':text,'box':box,'confidence':.99}
 items=[item('Left first.',[.08,.15,.25,.055]),item('Left second.',[.08,.22,.25,.055]),item('Right first.',[.65,.15,.25,.055]),item('Right second.',[.65,.22,.25,.055])]
 groups=group_items(items,(720,1280,3))
 assert [g['text'] for g in groups]==['Left first.\nLeft second.','Right first.\nRight second.']
 assert len(group_items(items,(720,1280,3),[[.6,0,.4,1]]))==1
 far_vertical=group_items([items[0],item('Another bubble.',[.08,.4,.25,.055])],(720,1280,3))
 assert len(far_vertical)==2


def test_parallel_growth_and_independent_disappearance():
 rows=[]
 for t in [1.,1.1,1.2,1.3,1.4,1.5]:rows.append((t,[group('Hello' if t<1.2 else 'Hello world.'),group('Good' if t<1.3 else 'Good morning.',RIGHT)]))
 for t in [1.6,1.7,1.8,1.9,2.0]:rows.append((t,[group('Good morning.',RIGHT)]))
 out=run(rows,2.1)
 assert [c['source'] for c in out]==['Hello world.','Good morning.']
 assert len({c['object_id'] for c in out})==2 and all(eligible(c) for c in out)
 assert out[0]['end']<1.7 and out[1]['end']>2
 assert all(b<1.7 for a,b in out[0]['cover_intervals'])


def test_same_text_elsewhere_and_reappearance_have_separate_identities():
 out=run([(t,[group('Again.'),group('Again.',RIGHT)]) for t in [1.,1.1,1.2]],1.3)
 assert len(out)==2 and out[0]['id']!=out[1]['id']
 out=run([(1,[group('Again.')]),(1.1,[group('Again.')]),(1.2,[group('Again.')]),(1.4,[]),(1.5,[]),(1.6,[group('Again.')]),(1.7,[group('Again.')]),(1.8,[group('Again.')])],1.9)
 assert len(out)==2 and out[0]['end']<out[1]['start']
 out=run([(t,[group('Same.',LEFT if t<1.3 else RIGHT)]) for t in [1.,1.1,1.2,1.3,1.4,1.5]],1.6)
 assert len(out)==2


def test_numbers_negation_and_same_prefix_replacements_are_not_growth():
 for first,second in [('We need 12.','We need 20.'),('Do not overwrite.','Do overwrite.'),('Save before exporting.','Save after exporting.')]:
  out=run([(t,[group(first if t<1.3 else second)]) for t in [1.,1.1,1.2,1.3,1.4,1.5,1.6,1.7]],1.8)
  assert [c['source'] for c in out]==[first,second]
  assert out[0]['end']<=out[1]['start']+.01


def test_low_evidence_preserves_original_and_json_state_roundtrips():
 out=run([(1,[group('Short.')])],1.1)
 assert len(out)==1 and not eligible(out[0])
 tracker=DynamicTracker()
 for t in [1.,1.1,1.2]:tracker.observe(t,[group('First.'),group('Second.',RIGHT)])
 restored=DynamicTracker(json.loads(json.dumps(tracker.state)))
 for t in [1.3,1.4,1.5]:assert tracker.observe(t,[group('First.')])==restored.observe(t,[group('First.')])
 assert tracker.finish(1.6)==restored.finish(1.6)


def test_missing_observation_does_not_create_a_permanent_cover():
 rows=[(1,[group('A sentence.')]),(1.1,[group('A sentence.')]),(1.2,[]),(1.3,[group('A sentence.')]),(1.4,[group('A sentence.')])]
 out=run(rows,1.5)
 assert len(out)==1
 assert not any(a<=1.2<b for a,b in visible_intervals(out[0]))
 assert not any(a<=3<b for a,b in visible_intervals(out[0]))


def test_long_chinese_annotation_does_not_expand_original_cover(tmp_path):
 p=Project.create(VIDEO,tmp_path/'annotation')
 try:
  p.update({'recognition_mode':'dynamic','dynamic':{'exclusions':[],'profile':'enhanced'}})
  c=cue('A small label.',box=[.5,.6,.025,.04]);c.update(translation='需要完整保留的中文\n第二行中文\n第三行',translation_status='translated')
  p.data['cues']=[c]
  original_box=c['box'][:]
  bounded=layout(c,p.data['meta'],p.data['style'])
  assert not bounded['fits']
  annotation=layout(c,p.data['meta'],p.data['style'],True)
  assert annotation['fits'] and annotation['annotation']
  assert annotation['box']==bounded['box']
  path=p.directory/'annotation.ass';write_ass(p,path)
  assert 'Dialogue: 0,' not in path.read_text()  # No larger opaque backdrop.
  assert c['box']==original_box and c['render_mode']=='outline'
 finally:p.close()


def test_tiny_weak_text_preserves_original_in_both_srt_and_video(tmp_path):
 p=Project.create(VIDEO,tmp_path/'tiny')
 try:
  p.update({'recognition_mode':'dynamic','dynamic':{'exclusions':[],'profile':'enhanced'}})
  tiny=cue('Unclear label.',box=[.3,.6,.03,.005]);tiny.update(confidence=.5,translation='不可靠标记',translation_status='translated')
  clear=cue('Clear sentence.',start=2);clear.update(translation='清晰字幕',translation_status='translated')
  p.data['cues']=[tiny,clear]
  export_srt(p,p.directory/'captions.srt');write_ass(p,p.directory/'captions.ass')
  assert not tiny['dynamic_verified'] and tiny['translation'] not in (p.directory/'captions.srt').read_text()
  assert clear['translation'] in (p.directory/'captions.srt').read_text()
 finally:p.close()


def test_four_modes_results_and_manual_box_validation_are_isolated(tmp_path):
 p=Project.create(VIDEO,tmp_path/'p')
 try:
  for mode in ('standard','progressive','progressive_hq','dynamic'):
   p.update({'recognition_mode':mode});p.data['cues']=[{**cue(mode), 'recognition_mode':mode,'id':mode,'translation':'人工','manual':True,'manual_translation':True}];p.save()
  for mode in ('standard','progressive','progressive_hq','dynamic'):
   p.update({'recognition_mode':mode});assert p.data['cues'][0]['id']==mode
  original=copy.deepcopy(p.data)
  with pytest.raises(ValueError):p.edit_cue('dynamic',{'box':[.9,.9,.3,.3],'translation':'不得保存'})
  assert p.data==original
  with pytest.raises(ValueError):p.update({'dynamic':{'exclusions':[[0,.9,1,.3]]}})
  assert p.data==original
  with pytest.raises(ValueError):scan(p,start=1,end=2,force=True)
  assert p.data==original
 finally:p.close()


def test_cancel_resume_preserves_parallel_active_tracks_and_evidence(tmp_path,monkeypatch):
 import worker.dynamic as dynamic
 stop=threading.Event();interrupt=[True]
 rows=[(t,[group('Hello' if t<1.2 else 'Hello world.'),group('Second.',RIGHT)] if t<1.6 else []) for t in [1.,1.1,1.2,1.3,1.4,1.5,1.6,1.7,1.8]]
 class OCR:
  def __init__(self):self.calls=0
  def request(self,payload):return {'languages':['en-US']}
  def recognize(self,pixels,language):
   self.calls+=1;index=int(pixels[0,0,0]);t,groups=rows[index]
   if interrupt[0] and t==1.2:stop.set()
   return {'items':[i for g in groups for i in g['items']],'unreadable':False}
  def close(self):pass
 def pixels(path,start,stop_at,interval,meta):
  for i,(t,_) in enumerate(rows):
   if start<=t<stop_at:yield t,np.full((720,1280,3),i,dtype=np.uint8)
 monkeypatch.setattr(dynamic,'VisionOCR',OCR);monkeypatch.setattr(dynamic,'frames',pixels);monkeypatch.setattr(dynamic,'DISCOVERY_INTERVAL',0)
 p=Project.create(VIDEO,tmp_path/'resume');p.update({'recognition_mode':'dynamic','dynamic':{'exclusions':[],'profile':'legacy'}})
 with pytest.raises(Cancelled):scan(p,cancel=stop,start=1,end=1.9)
 assert p.data['scan']['status']=='cancelled' and len(p.data['scan']['tracker']['tracks'])==2
 p.close();p=Project(tmp_path/'resume');stop.clear();interrupt[0]=False;scan(p,start=1,end=1.9)
 q=Project.create(VIDEO,tmp_path/'whole');q.update({'recognition_mode':'dynamic','dynamic':{'exclusions':[],'profile':'legacy'}});scan(q,start=1,end=1.9)
 fields=lambda p:[(c['source'],c['start'],c['end'],c['quality_support'],c['visible_intervals']) for c in p.data['cues']]
 assert fields(p)==fields(q) and len(p.data['cues'])==2
 assert all(Path(c['screenshot']).exists() for c in p.data['cues'])
 p.close();q.close()


def test_parallel_overlap_is_valid_but_spatial_conflicts_are_flagged():
 cues=[cue('First.'),cue('Second.',RIGHT)]
 check_dynamic_cues(cues)
 assert not any('重叠' in issue for c in cues for issue in c['issues'])
 cues[1]['box']=LEFT;check_dynamic_cues(cues)
 assert all('同屏字幕框重叠，请调整区域' in c['issues'] for c in cues)


def test_render_srt_and_manual_event_operations_follow_visibility(tmp_path):
 p=Project.create(VIDEO,tmp_path/'p');p.update({'recognition_mode':'dynamic'})
 try:
  p.data['cues']=[cue('First.'),cue('Second.',RIGHT),{**cue('Weak.',[.4,.4,.1,.05]),'dynamic_verified':False}]
  for c in p.data['cues']:c.update(translation='中文字幕。',translation_status='translated')
  first,second,weak=p.data['cues'];ass=tmp_path/'out.ass';write_ass(p,ass)
  content=ass.read_text();assert content.count('Dialogue: 0,')==2 and content.count('Dialogue: 1,')==2
  srt=tmp_path/'out.srt';export_srt(p,srt);assert srt.read_text().count(' --> ')==2
  p.edit_cue(first['id'],{'ignored':True});write_ass(p,ass);assert ass.read_text().count('Dialogue: 0,')==1
  p.undo();assert not p.data['cues'][0]['ignored']
  merge_objects(p,first['id'],second['id']);assert len(p.data['cues'])==2
  merged=next(c for c in p.data['cues'] if c['id']==first['id']);assert '\n' in merged['source']
  split_time(p,merged['id'],(merged['start']+merged['end'])/2);assert len(p.data['cues'])==3
  split_cues=[c for c in p.data['cues'] if c['id']!=weak['id']];assert split_cues[0]['cover_intervals'][-1][1]<=split_cues[1]['cover_intervals'][0][0]
 finally:p.close()


def test_auto_font_fit_and_safe_translation_skips_unconfirmed_or_ignored(tmp_path):
 p=Project.create(VIDEO,tmp_path/'p');p.update({'recognition_mode':'dynamic'})
 try:
  first=cue();weak={**cue('Uncertain.',RIGHT),'dynamic_verified':False};ignored={**cue('Ignore.',[.5,.2,.1,.1]),'ignored':True};p.data['cues']=[first,weak,ignored]
  translate(p);assert first['translation'] and not weak['translation'] and not ignored['translation']
  fitted=layout({**first,'translation':'这是比较长的中文字幕，需要在局部区域内换行。'},p.data['meta'],p.data['style'])
  assert fitted['fits'] and fitted['font_size']>=12
  assert not layout({**first,'box':[.1,.1,.02,.01],'translation':'很长的字幕'*60},p.data['meta'],p.data['style'])['fits']
 finally:p.close()


def test_visual_presence_bridges_unreadable_growth_without_inventing_votes():
 tracker=DynamicTracker();tracker.observe(1,[group('H')]);identity=tracker.state['tracks'][0]['id']
 for t in [1.1,1.2,1.3]:assert not tracker.observe(t,[],[identity])
 assert tracker.state['tracks'][0]['event']['variants']['H']['count']==1
 for t in [1.4,1.5,1.6]:tracker.observe(t,[group('Hello world.')])
 out=tracker.finish(1.7)
 assert len(out)==1 and out[0]['source']=='Hello world.' and out[0]['first_seen']==.95
 assert out[0]['quality_support']==3 and out[0]['visual_visibility_samples']==3
 assert out[0]['cover_intervals']==[[.95,1.65]]


def test_pixel_visibility_rejects_an_empty_patch_and_a_different_glyph():
 from worker.dynamic import capture_presence,presence_matches
 image=np.full((200,300,3),240,dtype=np.uint8);image[45:75,45:51]=10;image[45:75,64:70]=10;image[57:63,45:70]=10
 box=[.15,.225,.0834,.15];track={'presence_box':box,'presence':capture_presence(image,box)}
 assert presence_matches(image.copy(),track)
 assert not presence_matches(np.full_like(image,240),track)
 other=np.full_like(image,240);other[45:50,45:70]=10;other[58:62,45:70]=10;other[70:75,45:70]=10
 assert not presence_matches(other,track)


def test_above_multiline_stays_inside_top_edge_and_complete_display_keeps_cover(tmp_path):
 import re
 p=Project.create(VIDEO,tmp_path/'p');p.update({'recognition_mode':'dynamic'})
 try:
  c=cue(box=[.1,.002,.3,.18]);c.update(translation='第一行\n第二行',translation_status='translated',complete_time=1.15,complete_supported=True)
  p.data['cues']=[c];p.update({'progressive':{'display':'complete'}})
  ass=tmp_path/'out.ass';write_ass(p,ass);rows=ass.read_text().splitlines()
  masks=[r for r in rows if r.startswith('Dialogue: 0,')];texts=[r for r in rows if r.startswith('Dialogue: 1,')]
  assert masks[0].split(',')[1]=='0:00:00.95' and texts[0].split(',')[1]=='0:00:01.15'
  p.update({'style':{**p.data['style'],'mode':'above'}});write_ass(p,ass)
  text=next(r for r in ass.read_text().splitlines() if r.startswith('Dialogue: 1,'))
  y=float(re.search(r'\\pos\(\d+,(\d+)\)',text).group(1));size=float(re.search(r'\\fs(\d+)',text).group(1))
  assert y>=size*1.3+2 and not any(r.startswith('Dialogue: 0,') for r in ass.read_text().splitlines())
 finally:p.close()


def test_spatial_split_unreadable_second_half_does_not_change_original(tmp_path,monkeypatch):
 import worker.dynamic as dynamic
 p=Project.create(VIDEO,tmp_path/'p');p.update({'recognition_mode':'dynamic'});p.data['cues']=[cue()];p.save();original=copy.deepcopy(p.data['cues'])
 class OCR:
  def __init__(self):self.calls=0
  def recognize(self,pixels,language):
   self.calls+=1;return {'text':'Readable.' if self.calls==1 else '', 'confidence':.99}
  def close(self):pass
 monkeypatch.setattr(dynamic,'VisionOCR',OCR);monkeypatch.setattr(dynamic,'frames',lambda *a:iter([(1.2,np.full((720,1280,3),220,dtype=np.uint8))]))
 try:
  with pytest.raises(ValueError,match='原事件未修改'):dynamic.split_object(p,original[0]['id'],'x',.5)
  assert p.data['cues']==original
  p.close();p=Project(tmp_path/'p');assert p.data['cues']==original
 finally:p.close()
