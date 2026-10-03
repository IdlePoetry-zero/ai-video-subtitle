"""Public reproducible source for private multi-region pixel fixtures (macOS)."""
import json,sys,subprocess
from fractions import Fraction
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import av
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from worker.core import ROOT,ffmpeg_path

out=ROOT/'artifacts/dynamic-fixtures';out.mkdir(parents=True,exist_ok=True)
width,height,fps,duration=1280,720,30,20
font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',36)
small=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',20)
events=[
 {'id':'a','start':1.,'end':5.,'complete':2.1,'x':80,'y':90,'text':'Hello world.'},
 {'id':'b','start':1.5,'end':6.,'complete':2.8,'x':820,'y':540,'text':'Good morning.'},
 {'id':'short','start':3.5,'end':4.2,'complete':3.5,'x':960,'y':70,'text':'Stop!'},
 {'id':'same-left','start':7.,'end':9.5,'complete':7.,'x':100,'y':300,'text':'Again.'},
 {'id':'same-right','start':7.,'end':9.5,'complete':7.,'x':890,'y':300,'text':'Again.'},
 {'id':'return','start':10.,'end':12.,'complete':10.7,'x':80,'y':90,'text':'Hello again.'},
 {'id':'jump-first','start':13.,'end':14.5,'complete':13.,'x':390,'y':230,'text':'Keep the original timing.'},
 {'id':'jump-second','start':14.6,'end':16.,'complete':14.6,'x':70,'y':540,'text':'Keep the original timing.'},
 {'id':'two-lines','start':16.5,'end':19.,'complete':17.4,'x':750,'y':350,'text':'Read both lines.\nThey belong together.'},
]
for event in events:
 lines=event['text'].splitlines();w=max(font.getlength(line) for line in lines)+24;h=46*len(lines)+16
 event['bubble_box']=[(event['x']-12)/width,(event['y']-8)/height,w/width,h/height]
video=out/'silent.mp4'
with av.open(str(video),'w') as container:
 stream=container.add_stream('libx264',rate=fps);stream.width=width;stream.height=height;stream.pix_fmt='yuv420p';stream.options={'crf':'18','preset':'fast'}
 for index in range(fps*duration):
  t=index/fps;image=Image.new('RGB',(width,height),(24,43,57));draw=ImageDraw.Draw(image)
  for x in range(0,width,80):draw.line((x,0,x,height),fill=(30,52,67),width=2)
  for y in range(0,height,80):draw.line((0,y,width,y),fill=(30,52,67),width=2)
  draw.ellipse((500+int(t*9)%120,560,560+int(t*9)%120,620),fill=(53,106,120))
  draw.text((25,680),'DEMO',font=small,fill=(205,222,229))
  for event in events:
   if not event['start']<=t<event['end']:continue
   x,y,w,h=event['bubble_box'];box=(round(x*width),round(y*height),round((x+w)*width),round((y+h)*height))
   draw.rounded_rectangle(box,radius=10,fill=(245,247,249),outline=(95,117,132),width=2)
   text=event['text']
   if event['complete']>event['start'] and t<event['complete']:
    fraction=(t-event['start'])/(event['complete']-event['start']);text=text[:max(1,round(len(text)*fraction))]
   draw.multiline_text((event['x'],event['y']),text,font=font,fill=(10,15,20),spacing=7)
  frame=av.VideoFrame.from_ndarray(np.array(image),format='rgb24');frame.pts=index;frame.time_base=Fraction(1,fps)
  for packet in stream.encode(frame):container.mux(packet)
 for packet in stream.encode():container.mux(packet)
output=out/'多区域字幕测试.mp4'
subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-y','-i',str(video),'-f','lavfi','-i','sine=frequency=440:sample_rate=44100:duration=20','-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-t','20','-movflags','+faststart',str(output)],check=True)
(out/'reference.json').write_text(json.dumps({'width':width,'height':height,'fps':fps,'duration':duration,'events':events,'watermark_exclusion':[0,.91,.2,.09]},ensure_ascii=False,indent=2))
print(output)
