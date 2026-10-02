"""Independent real-video evaluator. Private annotations never enter the worker.

Usage: python tests/evaluate_quality.py manifest.json output.json
Manifest cases have name, start, end, baseline, quality, references [{time,source}],
optional speaker_labels and ignore_intervals. Paths point to project snapshots.
Frame-conditioned coverage is not full-video recall; all punctuation is counted.
"""
import json
from pathlib import Path
import re
import sys
import unicodedata
from evaluate_ocr import distance


def norm(text):
    return ' '.join(unicodedata.normalize('NFKC',text).split())


def evaluate(manifest):
    reports=[]
    for case in manifest['cases']:
        for mode in ('baseline','quality'):
            data=json.loads(Path(case[mode]).read_text())
            cues=[c for c in data['cues'] if c.get('first_seen',c['start'])<case['end'] and c.get('disappeared_at',c['end'])>case['start']]
            cues=[c for c in cues if not any(a <= (max(case['start'],c['start'])+min(case['end'],c['end']))/2 < b for a,b in case.get('ignore_intervals',[]))]
            names={norm(s).casefold() for s in case.get('speaker_labels',[])}
            errors=raw_errors=chars=missing=0;matched=[];rows=[]
            for ref in case['references']:
                cue=next((c for c in cues if c.get('first_seen',c['start'])<=ref['time']<c.get('disappeared_at',c['end'])),None)
                source=cue['source'] if cue else ''
                if cue and source!='[无法识别的字幕]':matched.append(cue['id'])
                else:missing+=1
                body='\n'.join(line for line in source.splitlines() if norm(line).casefold() not in names)
                n=norm(ref['source']);edit=distance(n,norm(body));raw=distance(n,norm(source));chars+=len(n);errors+=edit;raw_errors+=raw
                rows.append({'time':ref['time'],'reference':ref['source'],'source':source,'body_edits':edit})
            reports.append({'case':case['name'],'mode':mode,'reference_events':len(case['references']),'segments':len(cues),'complete_frame_missing':missing,'additional_segments':len(cues)-len(set(matched)),'merged_reference_matches':len(matched)-len(set(matched)),'body_CER':errors/max(1,chars),'raw_CER':raw_errors/max(1,chars),'body_edits':errors,'characters':chars,'rows':rows})
    return reports


if __name__=='__main__':
    reports=evaluate(json.loads(Path(sys.argv[1]).read_text()));Path(sys.argv[2]).write_text(json.dumps(reports,ensure_ascii=False,indent=2));print(json.dumps([{k:v for k,v in row.items() if k!='rows'} for row in reports],ensure_ascii=False,indent=2))
