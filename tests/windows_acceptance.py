"""Pixels -> real OCR -> local test API -> Chinese MP4, through server RPC.

Runs against either source Python or the frozen executable. No user media or keys.
"""
import argparse
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument('--worker')
parser.add_argument('--resources',default=str(ROOT))
parser.add_argument('--output',default=str(ROOT/'artifacts/windows/acceptance'))
args = parser.parse_args()
os.environ['STUDIO_RESOURCE_ROOT'] = args.resources
os.environ['STUDIO_OCR_ENGINE'] = 'rapidocr'
os.environ['PYTHONUTF8'] = '1'

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from worker.core import frames, probe, ffmpeg_path, normalize
from worker.platform_runtime import chinese_font, subprocess_options

OUT = Path(args.output).resolve()
OUT.mkdir(parents=True,exist_ok=True)
FONT = ImageFont.truetype(str(chinese_font()[0]),38)
EVENTS = [
    {'start':1.,'end':4.,'complete':1.8,'x':80,'y':555,'text':'Hello world.','zh':'你好，世界。'},
    {'start':2.,'end':5.,'complete':2.6,'x':780,'y':90,'text':'Good morning.','zh':'早上好。'},
    {'start':6.,'end':8.,'complete':6.,'x':80,'y':555,'text':'We need 12 samples, not 20.','zh':'我们需要12个样本，不是20个。'},
    {'start':9.,'end':11.,'complete':9.,'x':80,'y':555,'text':'Goodbye now.','zh':'再见。'},
]


def fixture():
    silent = OUT/'无敏感素材 silent.mp4'
    with av.open(str(silent),'w') as container:
        stream=container.add_stream('libx264',rate=20)
        stream.width,stream.height,stream.pix_fmt=1280,720,'yuv420p'
        stream.options={'crf':'18','preset':'fast'}
        for index in range(240):
            t=index/20;image=Image.new('RGB',(1280,720),(24,43,57));draw=ImageDraw.Draw(image)
            draw.ellipse((500+int(t*8),350,550+int(t*8),400),fill=(53,106,120))
            for event in EVENTS:
                if not event['start']<=t<event['end']:continue
                x,y,text=event['x'],event['y'],event['text']
                draw.rounded_rectangle((x-12,y-8,x+FONT.getlength(text)+15,y+62),radius=8,fill=(245,247,249))
                if t<event['complete']:
                    fraction=(t-event['start'])/(event['complete']-event['start'])
                    text=text[:max(1,round(len(text)*fraction))]
                draw.text((x,y),text,font=FONT,fill=(10,15,20))
            frame=av.VideoFrame.from_ndarray(np.array(image),format='rgb24');frame.pts=index;frame.time_base=Fraction(1,20)
            for packet in stream.encode(frame):container.mux(packet)
        for packet in stream.encode():container.mux(packet)
    source=OUT/'中文路径 source.mp4'
    subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y','-i',str(silent),'-f','lavfi','-i',
                    'sine=frequency=440:sample_rate=44100:duration=12','-map','0:v','-map','1:a','-c:v','copy',
                    '-c:a','aac','-t','12',str(source)],check=True,**subprocess_options())
    return source


class API(BaseHTTPRequestHandler):
    calls=[]
    def do_POST(self):
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        payload=json.loads(request['messages'][-1]['content'])
        # Test-only transport: exercises real HTTP/frozen translation child with
        # deterministic Chinese. It makes no model-quality claim.
        batch=payload['targets']
        API.calls.append(request)
        translations=[]
        for cue in batch:
            text=cue.get('source',cue.get('text',''))
            event=next((e for e in EVENTS if normalize(e['text']).casefold()==normalize(text).casefold()),None)
            translations.append({'id':cue['id'],'text':event['zh'] if event else '需要校对的字幕。'})
        answer={'choices':[{'message':{'content':json.dumps({'translations':translations},ensure_ascii=False)}}]}
        data=json.dumps(answer,ensure_ascii=False).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def log_message(self,*args):pass


class RPC:
    def __init__(self):
        command=[args.worker] if args.worker else [sys.executable,str(ROOT/'worker/server.py')]
        self.log=(OUT/'server-errors.log').open('w',encoding='utf-8')
        self.process=subprocess.Popen(command,cwd=ROOT,env=os.environ.copy(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                      stderr=self.log,text=True,encoding='utf-8',bufsize=1,**subprocess_options())
        self.messages=queue.Queue();self.id=0;self.events=[]
        def read():
            for line in self.process.stdout:
                try:self.messages.put(json.loads(line))
                except json.JSONDecodeError:self.messages.put({'protocol_error':line})
        threading.Thread(target=read,daemon=True).start()
    def request(self,method,params=None):
        self.id+=1;self.process.stdin.write(json.dumps({'id':self.id,'method':method,'params':params or {}},ensure_ascii=False)+'\n');self.process.stdin.flush()
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            value=self.messages.get(timeout=120)
            assert not value.get('protocol_error'),value
            if value.get('id')==self.id:
                if 'error' in value:raise RuntimeError(value['error'])
                return value['result']
            self.events.append(value)
        raise TimeoutError(method)
    def job(self,method,params=None,cancel_at=None):
        self.events=[];self.request(method,params);cancelled=False;deadline=time.monotonic()+600
        while time.monotonic()<deadline:
            value=self.events.pop(0) if self.events else self.messages.get(timeout=120)
            if cancel_at is not None and not cancelled and value.get('event')=='progress' and value.get('time',0)>=cancel_at:
                self.request('cancel');cancelled=True
            if value.get('event')=='job' and value.get('status') in ('complete','cancelled','failed'):
                if value.get('error'):raise RuntimeError(value['error'])
                return value
        raise TimeoutError(method)
    def close(self):
        self.process.stdin.close()
        try:self.process.wait(10)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.log.close()


def normalized(text):return normalize(text).lower().replace(' ', '').rstrip('.!?')


def main():
    source=fixture();server=ThreadingHTTPServer(('127.0.0.1',0),API)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    rpc=RPC();report={'platform':sys.platform,'worker':args.worker or 'source','test_translation':'local HTTP fixture, no external model',
                     'source':probe(source),'modes':{},'dependencies':rpc.request('dependencies')}
    try:
        assert report['dependencies']['ocr']['engine'].startswith('RapidOCR')
        for mode in ('standard','progressive','progressive_hq','dynamic'):
            print('Checking',mode,flush=True)
            directory=OUT/('中文项目 '+mode)
            rpc.request('create',{'video':str(source),'directory':str(directory)})
            rpc.request('update',{'changes':{'recognition_mode':mode,'roi':[.03,.74,.93,.23],
                       'translation':{'provider':'api','baseUrl':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture','glossary':''}}})
            if mode=='dynamic':
                assert rpc.job('scan',{'start':0,'end':12},cancel_at=3)['status']=='cancelled'
                assert rpc.request('snapshot')['scan']['status']=='cancelled'
            rpc.job('scan',{'start':0,'end':12})
            project=rpc.request('snapshot');cues=project['cues']
            expected=[e for e in EVENTS if mode=='dynamic' or e['y']>500]
            selected=[]
            for event in expected:
                matches=[c for c in cues if normalized(c['source'])==normalized(event['text'])]
                assert matches,(mode,event['text'],[(c['source'],c.get('verified')) for c in cues])
                cue=max(matches,key=lambda c:c.get('confidence',0));selected.append(cue)
                if mode=='standard':
                    assert event['start']-.35 <= cue['start'] <= event['complete']+.4,(mode,'start',cue)
                else:
                    assert abs(cue['start']-event['start'])<.35,(mode,'start',cue)
                assert abs(cue['end']-event['end'])<.35,(mode,'end',cue)
                if mode=='dynamic':assert cue['verified'],cue
            first_key=project['scan']['key'];rpc.job('scan',{'start':0,'end':12})
            assert rpc.request('snapshot')['scan']['key']==first_key
            rpc.job('translate',{'apiKey':'fixture-key'})
            project=rpc.request('snapshot')
            for cue in selected:
                translated=next(c for c in project['cues'] if c['id']==cue['id'])
                assert any('\u4e00'<=char<='\u9fff' for char in translated['translation']),translated
            output=directory/'中文字幕完整测试.mp4'
            rpc.job('export',{'output':str(output)})
            srt=directory/'中文字幕.srt';rpc.request('srt',{'output':str(srt)})
            assert ' --> ' in srt.read_text('utf-8')
            metadata=probe(output)
            assert (metadata['width'],metadata['height'])==(1280,720)
            assert abs(metadata['duration']-12)<.15
            with av.open(str(output)) as media:
                assert len(media.streams.audio)==1
                count=sum(1 for _ in media.decode(video=0));assert count==240,count
            # Pixel evidence: bright source bubble is covered, Chinese glyphs exist.
            source_frame=next(frames(source,3,3.05,.05))[1]
            output_frame=next(frames(output,3,3.05,.05))[1]
            patch=output_frame[555:615,80:390]
            assert np.mean(np.abs(output_frame.astype(float)-source_frame.astype(float)))>.3
            assert np.percentile(patch,95)-np.percentile(patch,5)>50
            Image.fromarray(output_frame).save(directory/'中文导出证据.png')
            report['modes'][mode]={'passed':True,'recognized':[c['source'] for c in selected],
                                  'cues':len(cues),'frames':count,'output':str(output),'metadata':metadata,
                                  'cancel_resume':mode=='dynamic'}
        assert API.calls,'Frozen translation child did not call HTTP fixture'
        report['http_translation_requests']=len(API.calls);report['passed']=True
    finally:
        rpc.close();server.shutdown()
        (OUT/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Windows four-mode acceptance passed.',flush=True)


if __name__=='__main__':main()
