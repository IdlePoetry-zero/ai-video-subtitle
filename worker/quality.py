"""Independent evidence-based progressive OCR. Baseline engines stay unchanged."""
from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
import json
import re
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

from worker.core import (VisionOCR, Cancelled, probe, file_fingerprint, frames, crop,
                         validate_roi, normalize, check_cues)
from worker.progressive import new_event, relation, event_to_cue

from worker.platform_runtime import rapid_ocr, ocr_identity, chinese_font

VERSION = 'quality-v3' + ('-' + ocr_identity() if rapid_ocr() else '')
MODE = 'progressive_hq'
DEFAULTS = {'layout': 'auto', 'exclusions': []}


def literal_reference(text):
    """Standalone URL rows are references, not prose to translate or cover."""
    tokens=text.strip().split()
    return bool(tokens) and all(bool(re.fullmatch(r'(?:https?[:;/][^\s]*|www\.[^\s]+|t\.me/[^\s]+)',token,re.IGNORECASE)) for token in tokens)


def reference_start(text):
    return bool(re.match(r'^\s*(?:https?[:;/]|www\.|t\.me/)',text,re.IGNORECASE))


def protected(text):
    return (re.findall(r'\d+(?:\.\d+)?', text),
            re.findall(r"\b(?:not|no|never|without|can't|don't|won't)\b", text.casefold()))


def similar(a, b):
    return protected(a) == protected(b) and SequenceMatcher(None, normalize(a).casefold(), normalize(b).casefold()).ratio() >= .88


def union_boxes(items):
    boxes = [item['box'] for item in items]
    x, y = min(b[0] for b in boxes), min(b[1] for b in boxes)
    return [x, y, max(b[0]+b[2] for b in boxes)-x, max(b[1]+b[3] for b in boxes)-y]


def select_body(result, roi, config=None):
    config = {**DEFAULTS, **(config or {})}
    kept, excluded, available = [], [], []
    learned = config.get('_speaker_keys', [])
    # RapidOCR's tight line boxes can put a short, left-aligned sentence in the
    # old side-option band. Preserve a sole high-confidence complete sentence;
    # manual exclusions and explicit dialogue/all layout still take precedence.
    items = result.get('items', [])
    standalone_sentence = rapid_ocr() and config['layout'] == 'auto' and len(items) == 1 and \
        items[0].get('confidence', 0) >= .85 and len(normalize(items[0]['text'])) >= 6 and \
        bool(re.search(r'[.!?。！？]$', items[0]['text'].strip()))
    for item in result.get('items', []):
        x, y, w, h = item['box']
        center_x, center_y = roi[0]+roi[2]*(x+w/2), roi[1]+roi[3]*(y+h/2)
        blocked = any(b[0] <= center_x <= b[0]+b[2] and b[1] <= center_y <= b[1]+b[3] for b in config['exclusions'])
        side_option = not standalone_sentence and config['layout'] != 'all' and y+h/2 < .48 and (x+w/2 > .8 or x+w/2 < .2)
        if blocked or side_option:
            excluded.append(item)
        else:
            available.append(item)
    if config['layout'] == 'all':
        kept = available
    elif config['layout'] == 'dialogue':
        kept = [i for i in available if i['box'][1]+i['box'][3]/2 >= .48]
        excluded.extend(i for i in available if i not in kept)
    else:
        kept = [i for i in available if i['box'][1]+i['box'][3]/2 >= .48]
        upper = [i for i in available if i not in kept]
        if kept:
            # Long adjacent upper rows can be the first lines of a wrapped
            # paragraph; short separated centered rows are likely speakers.
            remaining = list(upper)
            changed = True
            while changed:
                changed = False
                for item in list(remaining):
                    x,y,w,h = item['box']
                    near = any(abs((k['box'][1]+k['box'][3]/2)-(y+h/2)) <= max(.16,h*2.3) for k in kept)
                    if len(normalize(item['text'])) >= 24 and w >= .3 and near:
                        kept.append(item);remaining.remove(item);changed = True
            for item in remaining:
                if abs(item['box'][0]+item['box'][2]/2-.5) < .2 and len(item['text']) <= 24:
                    key = normalize(item['text']).casefold()
                    if key not in learned:
                        learned.append(key)
                        del learned[:-40]
            excluded.extend(remaining)
        else:
            # Scene changes may move a single subtitle above the former body
            # band. Admit sentence-shaped text, retaining learned speaker/UI
            # exclusions; never fall back to an observed speaker alone.
            for item in upper:
                key = normalize(item['text']).casefold();x,y,w,h = item['box']
                sentence = bool(re.search(r'[.!?。！？,，…]',item['text']))
                name_shape = w < .2 and len(key) < 24 and not sentence
                if key not in learned and not name_shape and (sentence or len(key) >= 6) and item['confidence'] >= .4:
                    kept.append(item)
                else:
                    excluded.append(item)
    rows = []
    for item in sorted(kept, key=lambda i: (i['box'][1]+i['box'][3]/2, i['box'][0])):
        row = next((r for r in rows if abs(r[0]['box'][1]+r[0]['box'][3]/2-item['box'][1]-item['box'][3]/2) < min(r[0]['box'][3],item['box'][3])*.45), None)
        if row is None:
            rows.append([item])
        else:
            row.append(item)
    text = '\n'.join(' '.join(i['text'] for i in sorted(r,key=lambda i:i['box'][0])) for r in rows)
    if text and re.search(r'[\u3400-\u9fff]', text):
        text = re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])', '', text)
    box = union_boxes(kept) if kept else None
    # If the only detected content belongs to excluded UI, do not keep an
    # unrelated unreadable hypothesis alive.
    return {**result, 'text': text.strip(), 'items': kept, 'excluded_items': excluded,
            'confidence': float(np.mean([i['confidence'] for i in kept])) if kept else 0.,
            'unreadable': bool(result.get('unreadable') and not excluded), 'body_box': box}


class QualityOCR(VisionOCR):
    def recognize_quality(self, pixels, language, roi, config, enhance=False):
        base = select_body(self.recognize(pixels, language), roi, config)
        alternatives = []
        if enhance and base.get('body_box'):
            x,y,w,h = base['body_box']
            # Read a tighter padded crop at a second scale. Alternatives are
            # still observations of this frame, never independent time votes.
            box = [max(0,x-.014), max(0,y-.07), min(1,x+w+.014), min(1,y+h+.07)]
            tight = pixels[int(box[1]*pixels.shape[0]):int(box[3]*pixels.shape[0]),
                           int(box[0]*pixels.shape[1]):int(box[2]*pixels.shape[1])]
            if tight.size:
                scaled = np.array(Image.fromarray(tight).resize((tight.shape[1]*2,tight.shape[0]*2),Image.Resampling.LANCZOS))
                reread = self.recognize(scaled,language)
                # Respect manual exclusion regions even for cropped rereads.
                mapped = []
                for item in reread['items']:
                    a,b,c,d = item['box']
                    mapped.append({**item,'box':[box[0]+a*(box[2]-box[0]),box[1]+b*(box[3]-box[1]),c*(box[2]-box[0]),d*(box[3]-box[1])]})
                refined = select_body({**reread,'items':mapped},roi,config)
                if refined['text']:
                    alternatives.append({'text':refined['text'],'confidence':refined['confidence'],'method':'tight-2x'})
        base['alternatives'] = alternatives
        return base


def plausible_growth(a, b, age):
    a, b = normalize(a).casefold(), normalize(b).casefold()
    if len(b) <= len(a):
        return False
    if len(a) <= 3 and age <= .5 and re.fullmatch(r'[a-z]+',a) and not protected(a)[1] and (a in b[:6] or a[0] == b[0]):
        return True
    if len(a) >= 4:
        prefix = b[:len(a)]
        same_protected = protected(a) == protected(prefix)
        # A partially typed/misread final word such as don'l must not turn
        # completing don't into a false protected-word replacement. Actual
        # numeric changes and changes to earlier completed negations stay split.
        if not same_protected and len(a) >= 12 and ' ' in a and ' ' in prefix and protected(a)[0] == protected(prefix)[0] and not re.search(r'[.!?。！？]$',a):
            head_a, tail_a = a.rsplit(' ',1); head_b, tail_b = prefix.rsplit(' ',1)
            same_protected = protected(head_a) == protected(head_b) and SequenceMatcher(None,tail_a,tail_b).ratio() >= .8
        return same_protected and SequenceMatcher(None,a,prefix).ratio() >= .8
    return False


def best_supported(event):
    values = event['variants']
    if not values:
        return None
    stable = [text for text,stats in values.items() if stats['count'] >= 3 and stats['last']-stats['first'] >= .159]
    candidates = stable or list(values)
    # Only suppress an isolated trailing cursor after actual on/off cycles.
    # Literal brackets/operators elsewhere in the text are preserved.
    history = event.get('primary_history', [])
    for extended in list(candidates):
        match = re.match(r'^(.*[.!?。！？…])\s+[|)\]]$', extended)
        if not match:
            continue
        base = match.group(1)
        if base not in values:
            continue
        states = [text == extended for _,text in history if text in (base,extended)]
        switches = sum(a != b for a,b in zip(states,states[1:]))
        if switches >= 3 and values[base]['count'] >= 3:
            candidates.remove(extended)
    # Growth prefixes cannot beat their corroborated completed descendants.
    terminals = [a for a in candidates if not any(relation(a,b)=='grow' and len(normalize(b))>len(normalize(a)) for b in candidates)]
    candidates = terminals or candidates
    def score(text):
        group = [v for v in values if similar(text,v)]
        # Count time observations; scaled crops from one frame do not inflate
        # support. Prefixes and unsupported garbage cannot manufacture evidence.
        times = {t for v in group for t in values[v].get('times', [])}
        support = len(times) or sum(values[v]['count'] for v in group)
        confidence = values[text]['confidence_sum']/max(1,values[text]['count'])
        return (support, values[text]['count']*(.5+.5*confidence), confidence, len(normalize(text)))
    return max(candidates,key=score)


def quality_record(event, timestamp, result):
    if result['text'].strip():
        history = event.setdefault('primary_history', [])
        if not history or history[-1][0] != timestamp:
            history.append([timestamp,result['text'].strip()])
            del history[:-300]
    observations = [{'text':result['text'],'confidence':result.get('confidence',0),'method':'original'},*result.get('alternatives',[])]
    for observation in observations:
        text = observation['text'].strip()
        if not text:
            continue
        stats = event['variants'].setdefault(text, {'count':0,'confidence':0.,'confidence_sum':0.,'first':timestamp,'last':timestamp,'times':[],'methods':[]})
        if timestamp not in stats['times']:
            stats['count'] += 1
            stats['confidence_sum'] += float(observation.get('confidence',0))
            stats['times'].append(timestamp)
        stats['last'] = timestamp
        stats['confidence'] = max(stats['confidence'],float(observation.get('confidence',0)))
        if observation['method'] not in stats['methods']:
            stats['methods'].append(observation['method'])
    event['last_seen'] = timestamp
    event['current'] = result['text'].strip() or event['current']
    if result.get('body_box'):
        event['body_box'] = union_boxes([{'box':event['body_box']},{'box':result['body_box']}]) if event.get('body_box') else result['body_box']
    event['excluded_items'] = result.get('excluded_items',[])


def quality_cue(event, end, display):
    best = best_supported(event)
    # Reuse the existing export schema while selecting with independent logic.
    selected = dict(event, variants={best:event['variants'][best]} if best else {})
    cue = event_to_cue(selected,end,display)
    stats = event['variants'].get(best,{})
    stable = stats.get('count',0)>=3 and stats.get('last',0)-stats.get('first',0)>=.159
    related = [v for v in event['variants'] if best and normalize(v).rstrip('.!?。！？') == normalize(best).rstrip('.!?。！？')]
    evidence = min(related,key=lambda v:event['variants'][v]['first']) if related else best
    complete = round(event['variants'][evidence]['first'],3) if stable else None
    cue.update(recognition_mode=MODE, complete_supported=stable, complete_time=complete,
               complete_evidence_text=evidence if stable else None,
               confidence=stats.get('confidence_sum',0)/max(1,stats.get('count',0)),
               raw_ocr=list(event['variants']),growth=[dict(text=text,**s) for text,s in event['variants'].items()],
               excluded_items=event.get('excluded_items',[]),body_box=event.get('body_box'),
               quality_support=stats.get('count',0),quality_methods=stats.get('methods',[]))
    if display=='complete' and complete is not None:
        cue['start']=complete
    evidence_files=event.get('evidence_files',{})
    selected_file=evidence_files.get(best,event.get('screenshot',''))
    cue['screenshot']=selected_file.get('path','') if isinstance(selected_file,dict) else selected_file
    cue['evidence_frames']=[{'text':text,'path':entry['path'] if isinstance(entry,dict) else entry,'time':entry['time'] if isinstance(entry,dict) else event['variants'][text]['first']} for text,entry in evidence_files.items() if text in event['variants']]
    issue = '' if stable else '完整文本缺少持续多帧证据，请核对'
    if stable and not re.search(r'[.!?。！？…]$',cue['source']):
        issue='未见结束标点，请确认文字是否完整'
    if stable and any(not similar(best,v) and relation(v,best) not in ('grow','same','correction') and relation(best,v)!='grow' and s['count']>=3 for v,s in event['variants'].items()):
        issue='多帧存在冲突原文，请检查截图'
    cue['recognition_issue']=issue
    return cue


class QualityTracker:
    def __init__(self,state=None,display='first'):
        self.state=state or {'active':None,'pending':None,'blank_since':None}
        self.display=display

    def finish(self,end):
        active=self.state['active'];pending=self.state['pending']
        self.state.update(active=None,pending=None,blank_since=None)
        if not active:return []
        # A short new caption ending before debounce must not disappear. It
        # remains reviewable instead of claiming three-frame completeness.
        if pending and pending['last_seen']-(pending['start']+.04)>=.079 and len({t for v in pending['variants'].values() for t in v['times']})>=2 and relation(best_supported(active) or '',best_supported(pending) or '')=='change':
            return [quality_cue(active,pending['start'],self.display),quality_cue(pending,end,self.display)]
        return [quality_cue(active,end,self.display)]

    def observe(self,timestamp,result,roi):
        s=self.state;active=s['active'];text=result['text'].strip()
        if not text and not result.get('unreadable'):
            if active:
                if s['blank_since'] is None:s['blank_since']=timestamp
                if timestamp-s['blank_since']>=.24-1e-6:return self.finish(max(active['start']+.01,s['blank_since']-.04))
            return []
        s['blank_since']=None
        if active and list(roi)!=active['roi']:
            closed=self.finish(timestamp-.04);s['active']=new_event(timestamp,roi);quality_record(s['active'],timestamp,result);return closed
        if active is None:
            s['active']=new_event(timestamp,roi);quality_record(s['active'],timestamp,result);return []
        if not text:
            active['last_seen']=timestamp;return []
        kind=relation(active['current'],text)
        best=best_supported(active)
        # Similar fading OCR is evidence of the same caption, except actual
        # number/negation replacements, which must remain distinct.
        same=kind in ('grow','same','correction') or (best and similar(best,text)) or plausible_growth(active['current'],text,timestamp-(active['start']+.04))
        if same:
            if s['pending']:active['transient_changes']+=1
            s['pending']=None;quality_record(active,timestamp,result);return []
        pending=s['pending']
        if pending is None or (relation(pending['current'],text) not in ('same','grow','correction') and not similar(pending['current'],text) and not plausible_growth(pending['current'],text,timestamp-(pending['start']+.04))):
            pending=new_event(timestamp,roi);s['pending']=pending
        quality_record(pending,timestamp,result)
        elapsed=timestamp-(pending['start']+.04)
        growing=len(pending['variants'])>1 and relation(next(iter(pending['variants'])),text)=='grow'
        # Prefix restarts need more than a short dropout; a new growing clause
        # gets a faster confirmation so short genuine captions are retained.
        threshold=.24 if growing else .40
        if elapsed>=threshold-1e-6 and len({t for v in pending['variants'].values() for t in v['times']})>=3:
            closed=quality_cue(active,pending['start'],self.display);s.update(active=pending,pending=None);return [closed]
        return []


def scan_quality(project,emit=lambda value:None,cancel=None,start=0.,end=None,force=False):
    cancel=cancel or threading.Event();data=project.data;meta=probe(data['meta']['path']);fingerprint=file_fingerprint(meta['path'])
    if data.get('fingerprint_version')==1 and fingerprint!=data['fingerprint']:raise ValueError('原视频内容已经变化，请创建新项目。')
    if not data.get('fingerprint_version'):data.update(fingerprint=fingerprint,fingerprint_version=1)
    end=min(end if end is not None else meta['duration'],meta['duration'])
    if not 0<=start<end:raise ValueError('试处理区间无效。')
    validate_roi(data['roi']);config={**DEFAULTS,**data.get('quality',{})}
    key=hashlib.sha256(json.dumps([fingerprint,data['roi'],data['regions'],data['language'],VERSION,config,start,end],sort_keys=True).encode()).hexdigest()
    checkpoint=data.get('scan',{});resume=checkpoint.get('key')==key and checkpoint.get('status') in ('running','cancelled','failed') and not force
    if checkpoint.get('key')==key and checkpoint.get('status')=='complete' and not force:
        emit({'stage':'scan','status':'cached','time':end,'total':end,'message':'高质量模式结果已缓存。'});return project.snapshot()
    if not resume:
        overlaps=lambda cue:cue.get('first_seen',cue['start'])<end and cue.get('disappeared_at',cue['end'])>start
        if any(c.get('manual') and overlaps(c) for c in data['cues']):raise ValueError('选定范围含人工修改字幕，请缩小范围或创建新项目。')
        data['cues']=[c for c in data['cues'] if not overlaps(c)]
        checkpoint={'key':key,'cursor':start-.0001,'status':'running','calls':0,'tracker':None,'mode':MODE,'version':VERSION};data['scan']=checkpoint;project.save(history=True)
    tracker=QualityTracker(checkpoint.get('tracker'),data.get('progressive',{}).get('display','first'));checkpoint['tracker']=tracker.state
    ocr=QualityOCR();started=saved=time.monotonic();last_enhance=-999.
    try:
        if data['language'] not in ocr.request({'operation':'languages'})['languages']:raise ValueError('系统 OCR 不支持所选语言。')
        for timestamp,image in frames(meta['path'],checkpoint['cursor']+.0001,end,.08,meta):
            if cancel.is_set():raise Cancelled()
            roi=next((r['roi'] for r in data['regions'] if r['start']<=timestamp<r['end']),data['roi']);pixels=crop(image,roi)
            enhance=timestamp-last_enhance>=.31
            layout_config={**config,'_speaker_keys':checkpoint.setdefault('speaker_keys',[])}
            result=ocr.recognize_quality(pixels,data['language'],roi,layout_config,enhance)
            if enhance:last_enhance=timestamp
            data['cues'].extend(tracker.observe(timestamp,result,roi))
            for event in (tracker.state['active'],tracker.state['pending']):
                if not event:continue
                best=best_supported(event)
                observed=[result['text'],*[v['text'] for v in result.get('alternatives',[])]]
                if best and best in observed:
                    files=event.setdefault('evidence_files',{})
                    if best not in files:
                        digest=hashlib.sha256(best.encode()).hexdigest()[:12];path=project.directory/'evidence'/f"{event['id']}-{digest}.jpg";Image.fromarray(pixels).save(path);files[best]={'path':str(path),'time':timestamp}
                        # Keep completed/consensus candidates, not every typed letter.
                        while len(files)>5:
                            removed=next(v for v in files if v!=best);entry=files.pop(removed);Path(entry['path'] if isinstance(entry,dict) else entry).unlink(missing_ok=True)
                    entry=files[best];event.update(screenshot=entry['path'] if isinstance(entry,dict) else entry,screenshot_text=best)
            checkpoint.update(cursor=timestamp,status='running')
            if time.monotonic()-saved>=.8:
                checkpoint['calls']+=ocr.calls;ocr.calls=0;data['cues'].sort(key=lambda c:c['start']);project.save()
                emit({'stage':'scan','status':'running','time':timestamp,'total':end,'count':len(data['cues']),'message':'正在分离正文并交叉确认完整字幕'});saved=time.monotonic()
        final_end=tracker.state['blank_since']-.04 if tracker.state['blank_since'] is not None else end
        data['cues'].extend(tracker.finish(final_end));checkpoint.update(status='complete',cursor=end);data['cues'].sort(key=lambda c:c['start']);check_cues(data['cues'],data['style'],data['translation'].get('glossary',''));return project.snapshot()
    except Cancelled:checkpoint['status']='cancelled';raise
    except Exception:checkpoint['status']='failed';raise
    finally:
        checkpoint['calls']+=ocr.calls;checkpoint['elapsed']=checkpoint.get('elapsed',0)+time.monotonic()-started;project.save();ocr.close()
