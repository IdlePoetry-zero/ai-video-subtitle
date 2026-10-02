import json
from pathlib import Path
from PIL import Image
import pytest
from worker.visual_review import review_request


class Response:
 def __init__(self,value):self.value=value
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def read(self):return json.dumps({'choices':[{'message':{'content':json.dumps(self.value)}}]}).encode()


def test_review_sends_only_bounded_crops_and_returns_suggestion(monkeypatch,tmp_path):
 path=tmp_path/'evidence.jpg';Image.new('RGB',(900,240),'white').save(path)
 calls=[]
 class Opener:
  def open(self,request,timeout):
   calls.append(json.loads(request.data));assert timeout==90;return Response({'status':'readable','text':'Use 12, not 20.','reason':'多帧清晰'})
 monkeypatch.setattr('urllib.request.build_opener',lambda *args:Opener())
 cue={'source':'Use 12, not 2O.','screenshot':str(path),'body_box':[.1,.5,.8,.2],'translation':'人工译文','manual':True}
 prior=dict(cue)
 value=review_request({'provider':'api','baseUrl':'https://api.deepseek.com','model':'deepseek-flash'},cue,'test-key')
 assert cue==prior and value['suggestion_only'] and value['image_count']==1
 assert calls[0]['thinking']=={'type':'disabled'}
 content=calls[0]['messages'][1]['content'];assert content[1]['image_url']['url'].startswith('data:image/jpeg;base64,')
 assert '不能凭剧情' in content[0]['text']


def test_unclear_review_does_not_invent_text(monkeypatch,tmp_path):
 path=tmp_path/'e.jpg';Image.new('RGB',(100,40)).save(path)
 class Opener:
  def open(self,*args,**kwargs):return Response({'status':'unclear','text':'guessed sentence','reason':'无法辨认'})
 monkeypatch.setattr('urllib.request.build_opener',lambda *args:Opener())
 result=review_request({'provider':'api','baseUrl':'http://localhost:1234','model':'vision'}, {'source':'a','screenshot':str(path)})
 assert result['text']=='' and result['status']=='unclear'


def test_mock_cannot_be_mislabeled_as_image_review():
 with pytest.raises(ValueError):review_request({'provider':'mock'},{'source':'anything'})
