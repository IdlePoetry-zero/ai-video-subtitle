"""Reference data is only consumed by generation and the independent evaluator."""
from pathlib import Path
import json
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from worker.core import ROOT, ffmpeg_path, ass_time
OUT=ROOT/'artifacts/progressive-fixtures'
# start, end, text, reveal strategy. One fixed area, actual text painted in pixels.
CASES=[
 (1.,6.,'Welcome to the subtitle studio.','char'),
 (7.,12.,'Today we will translate a video.','word'),
 (13.,19.,'We need 12 samples, not 20.','pause'),
 (20.,25.,'Read both lines.\nThey belong together.','word'),
 (26.,30.,'Keep the original timing.','char'),
 (30.,34.,'Check the sound and the picture.','word'),
 (35.,39.,'Hello again.','word'),
 (40.,44.,'Hello again.','word'),
 (45.,49.,'Save the project before exporting.','word'),
 (49.,53.,'Save the project after exporting.','word'),
 (54.,59.,'Do not overwrite my edits.','char'),
]

def stages(start,end,text,strategy):
 if strategy=='word':
  # Reveal whole words while retaining intended line breaks.
  import re
  ends=[match.end() for match in re.finditer(r'\S+',text)]
 else:ends=list(range(1,len(text)+1))
 reveal=min(2.4,(end-start)*.6)
 values=[]
 for i,last in enumerate(ends):
  t=start+reveal*i/max(1,len(ends)-1)
  if strategy=='pause' and i>=len(ends)//2:t+=.6
  values.append((round(t/0.04)*.04,text[:last]))
 # The pause offsets the tail; full text still holds >1 s.
 return values

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 header='''[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Caption,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,1,80,20,42,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
'''
 reference=[];events=[]
 for start,end,text,strategy in CASES:
  parts=stages(start,end,text,strategy)
  for i,(at,partial) in enumerate(parts):
   until=parts[i+1][0] if i+1<len(parts) else end
   if until<=at:continue
   encoded=partial.replace('\n',r'\N')
   events.append(f'Dialogue: 0,{ass_time(at)},{ass_time(until)},Caption,,0,0,0,,{encoded}')
  reference.append({'start':start,'end':end,'text':text,'complete_time':parts[-1][0],'strategy':strategy})
 (OUT/'progressive.ass').write_text(header+'\n'.join(events)+'\n')
 (OUT/'reference.json').write_text(json.dumps(reference,ensure_ascii=False,indent=2))
 command=[ffmpeg_path(),'-hide_banner','-y','-f','lavfi','-i','testsrc2=size=1280x720:rate=25:duration=60','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=60','-vf','drawbox=x=0:y=530:w=iw:h=180:color=black@0.95:t=fill,ass=progressive.ass','-c:v','libx264','-crf','20','-preset','fast','-c:a','aac','-movflags','+faststart','逐步出现字幕 测试.mp4']
 with (OUT/'generate.log').open('w') as log:subprocess.run(command,cwd=OUT,stdout=log,stderr=log,check=True)
 print(OUT/'逐步出现字幕 测试.mp4')
if __name__=='__main__':main()
