"""Independent reference evaluation; the worker never reads the reference file."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from tests.evaluate_ocr import evaluate, normalized
from worker.core import ROOT, Project

def evaluation(data):
 reference=json.loads((ROOT/'artifacts/progressive-fixtures/reference.json').read_text())
 result=evaluate(reference,data['cues'])
 complete_good=0
 for row in result['rows']:
  if not row['actual']:continue
  cue=next(c for c in data['cues'] if c['start']==row['actual']['start'] and c['source']==row['actual']['source'])
  complete=cue.get('complete_time')
  row['complete_time']=complete
  row['complete_error']=abs(complete-row['expected']['complete_time']) if complete is not None else None
  row['full_text_has_pixel_evidence']=any(item['text']==cue.get('complete_evidence_text',cue['source']) and abs(item['first']-complete)<.001 for item in cue.get('growth',[]))
  if row['complete_error'] is not None and row['complete_error']<=.20001 and row['full_text_has_pixel_evidence']:complete_good+=1
 result['complete_within_200ms']=complete_good/len(reference)
 result['passed']=result['passed'] and result['complete_within_200ms']>=.95
 result['scan']=data['scan']
 return result
if __name__=='__main__':
 p=Path(sys.argv[1])
 if p.suffix=='.json':data=json.loads(p.read_text())
 else:
  project=Project(p);data=project.snapshot();project.close()
 result=evaluation(data)
 out=Path(sys.argv[2]) if len(sys.argv)>2 else ROOT/'artifacts/progressive-evaluation.json'
 out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps({k:v for k,v in result.items() if k not in ('rows','scan')},indent=2))
 if not result['passed']:sys.exit(1)
