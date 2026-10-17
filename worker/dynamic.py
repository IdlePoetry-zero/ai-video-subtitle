"""Independent spatially stationary multi-caption events; no permanent subtitle ROI."""
from __future__ import annotations

from difflib import SequenceMatcher
import base64
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time

import numpy as np
from PIL import Image, ImageFont

from worker.core import (VisionOCR, Cancelled, frames, crop, probe, file_fingerprint,
                         normalize, validate_roi, ass_color, ass_text, ass_time, srt_time)
from worker.progressive import new_event, relation
from worker.quality import quality_record, quality_cue, best_supported, similar, plausible_growth, literal_reference, reference_start
from worker.appearance import pixel_box

MODE = 'dynamic'
from worker.platform_runtime import rapid_ocr, ocr_identity, chinese_font

VERSION = 'dynamic-v2.3' + ('-' + ocr_identity() if rapid_ocr() else '')
INTERVAL = .1
DISCOVERY_INTERVAL = .2
MISS_GRACE = .16
DEFAULTS = {'exclusions': [], 'profile': 'legacy', 'review_regions': [], 'shards': 1, 'interval': 0}


def search_region(track):
    """Search the candidate sentence too; these bounds never become cover bounds."""
    boxes = [track['box']]
    if track.get('pending'):
        boxes.append(track['pending']['box'])
    box = union(boxes)
    return expanded(box, max(.012, box[2]*.3), max(.02, box[3]*.4))


def mapped_items(result, roi):
    items = []
    for item in result.get('items', []):
        x, y, w, h = item['box']
        items.append({**item, '_resolution':1., 'box': [roi[0]+x*roi[2], roi[1]+y*roi[3], w*roi[2], h*roi[3]]})
    return items


def union(boxes):
    x, y = min(b[0] for b in boxes), min(b[1] for b in boxes)
    return [x, y, max(b[0]+b[2] for b in boxes)-x, max(b[1]+b[3] for b in boxes)-y]


def area(box):
    return box[2]*box[3]


def intersection(a, b):
    return max(0., min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0]))*max(0.,min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1]))


def bounded(box):
    x,y,w,h=box;left,top=max(0.,x),max(0.,y);right,bottom=min(1.,x+w),min(1.,y+h)
    return [left,top,max(0.,right-left),max(0.,bottom-top)]


def expanded(box, x=.015, y=.025):
    return bounded([box[0]-x,box[1]-y,box[2]+x*2,box[3]+y*2])


def deduplicate(items, enhanced=False):
    out=[]
    key=(lambda i:(-int(i['confidence']>=.8),-len(normalize(i['text'])),-i.get('_resolution',1.),-i['confidence'])) if enhanced else (lambda i:(-i['confidence'],-len(i['text'])))
    for item in sorted(items,key=key):
        duplicated=False
        for other in out:
            a,b=item['box'],other['box'];overlap=intersection(a,b);containment=overlap/max(1e-9,min(area(a),area(b)))
            if enhanced:
                same_scale=max(a[3],b[3])/max(1e-9,min(a[3],b[3]))<1.6
                first,second=normalize(item['text']).casefold(),normalize(other['text']).casefold()
                shorter,longer=sorted([first,second],key=len)
                fragment=bool(shorter) and (shorter in longer or SequenceMatcher(None,shorter,longer).find_longest_match().size/len(shorter)>.85)
                # These are competing reads of one physical row in one frame,
                # not number/negation changes across time. Never concatenate.
                exact_row=first==second and bool(first) and containment>.65 and abs(a[1]+a[3]/2-b[1]-b[3]/2)<.4*max(a[3],b[3]) and max(a[3],b[3])/max(1e-9,min(a[3],b[3]))<2.5
                duplicated=exact_row or (same_scale and (overlap/max(1e-9,area(a)+area(b)-overlap)>.75 or (containment>.88 and fragment)))
            else:
                duplicated=containment>.78 and (similar(item['text'],other['text']) or relation(item['text'],other['text']) in ('grow','shrink'))
            if duplicated:break
        if duplicated:continue
        out.append(item)
    return out


def group_items(items, shape, exclusions=(), enhanced=False):
    """Conservative row/paragraph grouping in physical pixels, never whole-frame text."""
    height,width=shape[:2];kept=[]
    for item in items:
        text=item.get('text','').strip();box=bounded(item['box']);x,y,w,h=box
        if not text or w<=0 or h<=0:continue
        if any(b[0]<=x+w/2<=b[0]+b[2] and b[1]<=y+h/2<=b[1]+b[3] for b in exclusions):continue
        kept.append({**item,'text':text,'box':box,'confidence':float(item.get('confidence',0))})
    rows=[]
    for item in sorted(deduplicate(kept,enhanced),key=lambda i:(i['box'][1]+i['box'][3]/2,i['box'][0])):
        b=item['box'];choices=[]
        for index,row in enumerate(rows):
            a=union([i['box'] for i in row]);gap=max(b[0]-a[0]-a[2],a[0]-b[0]-b[2],0)*width
            same_y=abs(a[1]+a[3]/2-b[1]-b[3]/2)*height < min(a[3],b[3])*height*.4
            if enhanced and max(a[3],b[3])>2*min(a[3],b[3]):same_y=False
            if same_y and gap<=max(5.,min(a[3],b[3])*height*.7):choices.append((gap,index))
        if choices:rows[min(choices)[1]].append(item)
        else:rows.append([item])
    lines=[]
    for row in rows:
        row.sort(key=lambda i:i['box'][0]);text=' '.join(i['text'] for i in row)
        text=re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])','',text)
        lines.append({'text':text,'box':union([i['box'] for i in row]),'items':row})
    paragraphs=[]
    for line in sorted(lines,key=lambda i:i['box'][1]):
        b=line['box'];choices=[]
        for index,paragraph in enumerate(paragraphs):
            if enhanced and (reference_start(line['text']) or reference_start(paragraph[-1]['text'])):continue
            a=paragraph[-1]['box'];gap=(b[1]-a[1]-a[3])*height
            overlap=max(0.,min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0]))/max(1e-9,min(a[2],b[2]))
            centered=abs(a[0]+a[2]/2-b[0]-b[2]/2)<=max(.012,min(a[2],b[2])*.22)
            aligned=abs(a[0]-b[0])*width<=max(8.,min(a[3],b[3])*height*.65)
            if -.2*min(a[3],b[3])*height<=gap<=min(a[3],b[3])*height*.65 and overlap>=.72 and (centered or aligned):choices.append((abs(gap),index))
        if choices:paragraphs[min(choices)[1]].append(line)
        else:paragraphs.append([line])
    groups=[]
    for paragraph in paragraphs:
        members=[i for line in paragraph for i in line['items']]
        groups.append({'text':'\n'.join(line['text'] for line in paragraph),'box':union([line['box'] for line in paragraph]),'items':members,'confidence':float(np.mean([i['confidence'] for i in members]))})
    return groups


def presence_pixels(image, box, size=(48,32)):
    if box[2]*image.shape[1]<16 or box[3]*image.shape[0]<12:return None
    return np.array(Image.fromarray(crop(image,box)).convert('L').resize(size,Image.Resampling.BILINEAR))


def glyph_signature(image, box):
    pixels=presence_pixels(image,box,(384,64))
    if pixels is None:return None
    lo,hi=np.percentile(pixels,[5,95])
    if hi-lo<45:return None
    bits=pixels>(lo+hi)/2
    if not .03<float(bits.mean())<.94:return None
    return {'bits':base64.b64encode(np.packbits(bits).tobytes()).decode('ascii')}


def glyph_matches(known, current):
    if not known or not current:return False
    a=np.unpackbits(np.frombuffer(base64.b64decode(known['bits']),dtype=np.uint8))
    b=np.unpackbits(np.frombuffer(base64.b64decode(current['bits']),dtype=np.uint8))
    # Whole-patch agreement is dominated by background. Compare foreground
    # instead: changed digits/negation must not disappear in a large black ROI.
    return float(np.count_nonzero(a!=b))/max(1,min(np.count_nonzero(a),np.count_nonzero(b)))<.002


def capture_presence(image,box,threshold=None):
    # A stationary glyph patch can establish visibility even when a partial
    # word is not readable. It never contributes an OCR text/frame vote.
    patch=presence_pixels(image,box)
    if patch is None:return None
    lo,hi=np.percentile(patch,[5,95])
    if hi-lo<45:return None
    threshold=float((lo+hi)/2) if threshold is None else threshold
    mask=patch>threshold
    if not .06<float(mask.mean())<.94:return None
    return {'threshold':threshold,'bits':np.packbits(mask).tolist()}


def presence_matches(image,track,strict=False):
    if strict:
        known=track.get('strict_presence')
        if not known or known['text']!=best_supported(track['event']):return False
        return glyph_matches(known['signature'],glyph_signature(image,known['box']))
    known=track.get('presence')
    if not known:return False
    now=capture_presence(image,track['presence_box'],known['threshold'])
    if not now:return False
    a=np.unpackbits(np.array(known['bits'],dtype=np.uint8));b=np.unpackbits(np.array(now['bits'],dtype=np.uint8))
    return float(np.mean(a!=b))<.045


def association(track, group):
    a,b=track['box'],group['box'];overlap=intersection(a,b)
    containment=overlap/max(1e-9,min(area(a),area(b)))
    iou=overlap/max(1e-9,area(a)+area(b)-overlap)
    dy=abs(a[1]+a[3]/2-b[1]-b[3]/2);dx=abs(a[0]+a[2]/2-b[0]-b[2]/2)
    if containment<.35 and not (dy<min(a[3],b[3])*.55 and dx<min(a[2],b[2])*.3):return None
    # Text aids association only inside a geometric gate. Identical text far
    # away must always create a separate object.
    text=best_supported(track['event']) or track['event']['current']
    similarity=SequenceMatcher(None,normalize(text).casefold(),normalize(group['text']).casefold()).ratio()
    return .55*containment+.25*iou+.2*similarity


def make_track(t, group, start=0.):
    event=new_event(t,group['box']);event['start']=max(start,t-INTERVAL/2)
    return {'id':event['id'],'event':event,'box':list(group['box']),'last_seen':t,'missing_since':None,'pending':None,'visible_intervals':[],'items_by_text':{},'evidence':{},'ambiguity':False}


def record(track,t,group):
    track.update(last_seen=t,missing_since=None,box=union([track['box'],group['box']]))
    track.update(last_ocr_time=t,last_ocr_text=group['text'])
    quality_record(track['event'],t,{'text':group['text'],'confidence':group['confidence']})
    track['items_by_text'][group['text']]=group['items']
    spans=track['visible_intervals'];left=max(track['event']['start'],t-INTERVAL/2);right=t+INTERVAL/2
    if spans and left<=spans[-1][1]+.001:spans[-1][1]=right
    else:spans.append([left,right])


def recover_visibility(track, at, image):
    """Retroactively fill only short misses with matching glyph pixels and text.

    The missed frame itself must match the newly OCR-confirmed template. Merely
    seeing the same words on both sides never bridges a real blank/cut.
    """
    best=best_supported(track['event'])
    if not best or track['event']['variants'].get(best,{}).get('count',0)<3:return
    previous=track.get('strict_presence')
    items=track['items_by_text'].get(best,[])
    observed_box=bounded(union([i['box'] for i in items])) if items else list(track['box'])
    stationary=previous and intersection(previous['box'],observed_box)/max(1e-9,area(previous['box'])+area(observed_box)-intersection(previous['box'],observed_box))>.98
    box=previous['box'] if stationary and previous['text']==best else observed_box
    if track.get('last_ocr_time') == at and track.get('last_ocr_text') == best:
        signature=glyph_signature(image,box)
        if signature:
            track['strict_presence']={'box':box,'text':best,'signature':signature}
            spans=track['visible_intervals']
            for gap in track.pop('gap_pixels',[]):
                if gap['text'] != best or at-gap['time']>.31 or intersection(gap['box'],box)/max(1e-9,area(gap['box'])+area(box)-intersection(gap['box'],box))<.98:continue
                if not glyph_matches(signature,gap.get('signature')):continue
                spans.append([max(track['event']['start'],gap['time']-INTERVAL/2),gap['time']+INTERVAL/2])
                track['recovered_visibility_samples']=track.get('recovered_visibility_samples',0)+1
            merged=[]
            for left,right in sorted(spans):
                if merged and left<=merged[-1][1]+.001:merged[-1][1]=max(merged[-1][1],right)
                else:merged.append([left,right])
            track['visible_intervals']=merged
    elif track.get('missing_since') is not None:
        signature=glyph_signature(image,box)
        if signature:
            gaps=track.setdefault('gap_pixels',[])
            gaps.append({'time':at,'text':best,'box':box,'signature':signature})
            del gaps[:-3]


def finish_track(track,end,display='first'):
    event=track['event'];last=min(end,event['last_seen']+INTERVAL/2)
    if not event['variants'] or last<=event['start']:return None
    cue=quality_cue(event,last,display);source=cue['source'];confidence=cue['confidence']
    spans=[[round(max(event['start'],a),3),round(min(last,b),3)] for a,b in track['visible_intervals'] if max(event['start'],a)<min(last,b)]
    selected=track['evidence'].get(source,{})
    cue.update(recognition_mode=MODE,object_id=track['id'],box=bounded(track['box']),visible_intervals=spans,cover_intervals=spans,
               original_end=round(last,3),disappeared_at=round(last,3),ignored=False,
               dynamic_verified=bool(cue['complete_supported'] and confidence>=.45 and any(c.isalnum() for c in source)),
               screenshot=selected.get('path',''),screenshot_box=selected.get('box'),detection_items=track['items_by_text'].get(source,[]),
                    evidence_frames=[{'text':text,**entry} for text,entry in track['evidence'].items()],visual_visibility_samples=track.get('visual_visibility_samples',0),recovered_visibility_samples=track.get('recovered_visibility_samples',0))
    if not cue['dynamic_verified']:cue['recognition_issue']='文字证据不足，保留原画面；请校对并确认事件'
    if track['ambiguity']:cue['recognition_issue']='相邻文字区域的关联不明确，请检查是否属于不同对象'
    return cue


class DynamicTracker:
    def __init__(self,state=None,display='first',start=0.,miss_grace=MISS_GRACE):
        self.state=state if state is not None else {'tracks':[]}
        self.display=display;self.start=start
        self.miss_grace=miss_grace

    def observe(self,t,groups,present_ids=()):
        out=[];tracks=self.state['tracks'];alive=[]
        for track in tracks:
            if track['missing_since'] is not None and t-track['missing_since']>=self.miss_grace-1e-6:
                for current in [track,track.get('pending')]:
                    if current:
                        cue=finish_track(current,track['missing_since'],self.display)
                        if cue:out.append(cue)
            else:alive.append(track)
        tracks[:]=alive
        pairs=[]
        for i,track in enumerate(tracks):
            for j,group in enumerate(groups):
                score=association(track,group)
                if score is not None:pairs.append((score,i,j))
        used_tracks=set();used_groups=set()
        for score,i,j in sorted(pairs,reverse=True):
            if i in used_tracks or j in used_groups:continue
            used_tracks.add(i);used_groups.add(j);track=tracks[i];group=groups[j]
            track.update(last_seen=t,missing_since=None)
            text=group['text'];current=track['event']['current'];best=best_supported(track['event'])
            kind=relation(current,text)
            same=kind in ('same','grow','correction') or bool(best and similar(best,text)) or plausible_growth(current,text,t-track['event']['start'])
            if same:
                track['pending']=None;record(track,t,group)
            else:
                pending=track.get('pending')
                if pending is None or (relation(pending['event']['current'],text) not in ('same','grow','correction') and not similar(pending['event']['current'],text)):
                    pending=make_track(t,group,self.start);track['pending']=pending
                record(pending,t,group)
                best_pending=best_supported(pending['event']);stats=pending['event']['variants'].get(best_pending,{})
                if t-pending['event']['start']>=.25 and stats.get('count',0)>=3:
                    cue=finish_track(track,pending['event']['start'],self.display)
                    if cue:out.append(cue)
                    tracks[i]=pending
        for i,track in enumerate(tracks):
            if i not in used_tracks:
                if track['id'] in present_ids:
                    track.update(last_seen=t,missing_since=None);track['event']['last_seen']=t
                    track['visual_visibility_samples']=track.get('visual_visibility_samples',0)+1
                    spans=track['visible_intervals'];left=max(track['event']['start'],t-INTERVAL/2);right=t+INTERVAL/2
                    if spans and left<=spans[-1][1]+.001:spans[-1][1]=right
                    else:spans.append([left,right])
                elif track['missing_since'] is None:track['missing_since']=t
        for j,group in enumerate(groups):
            if j not in used_groups:
                track=make_track(t,group,self.start);record(track,t,group);tracks.append(track)
        return out

    def finish(self,end):
        out=[]
        for track in self.state['tracks']:
            for current in [track,track.get('pending')]:
                if current:
                    cue=finish_track(current,min(end,track['missing_since'] if track['missing_since'] is not None else end),self.display)
                    if cue:out.append(cue)
        self.state['tracks']=[]
        return out


def visible_intervals(cue,display=False):
    start,end=cue['start'],cue['end']
    spans=cue.get('visible_intervals',[[cue.get('first_seen',start),cue.get('disappeared_at',end)]])
    return [[max(a,start) if display else a,min(b,end) if display else b] for a,b in spans if (max(a,start) if display else a)<(min(b,end) if display else b)]


def eligible(cue):
    return not cue.get('ignored') and cue.get('dynamic_verified',False)


def scan_dynamic(project,emit=lambda value:None,cancel=None,start=0.,end=None,force=False):
    cancel=cancel or threading.Event();data=project.data;meta=probe(data['meta']['path']);fingerprint=file_fingerprint(meta['path'])
    if data.get('fingerprint_version')==1 and fingerprint!=data['fingerprint']:raise ValueError('原视频内容已经变化，请创建新项目。')
    end=min(meta['duration'],end if end is not None else meta['duration'])
    if not 0<=start<end:raise ValueError('试处理区间无效。')
    config={**DEFAULTS,**data.get('dynamic',{})}
    for box in config['exclusions']:validate_roi(box)
    import os as _os
    # Shard-parallel scan: each shard runs this same scan on its own time window
    # in a child process; the parent merges the events afterwards.
    if int(config.get('shards') or 1) > 1 and not _os.environ.get('STUDIO_SHARD_CHILD'):
        from worker.shard import scan_sharded
        return scan_sharded(project, emit, cancel, start, end, config)
    key=hashlib.sha256(json.dumps([fingerprint,data['language'],VERSION,config,start,end],sort_keys=True).encode()).hexdigest()
    checkpoint=data.get('scan',{});resume=checkpoint.get('key')==key and checkpoint.get('status') in ('running','cancelled','failed') and not force
    if checkpoint.get('key')==key and checkpoint.get('status')=='complete' and not force:
        emit({'stage':'scan','status':'cached','time':end,'total':end,'message':'全画面模式结果已缓存。'});return project.snapshot()
    if not resume:
        overlaps=lambda c:c.get('first_seen',c['start'])<end and c.get('disappeared_at',c['end'])>start
        if any(c.get('manual') and overlaps(c) for c in data['cues']):raise ValueError('该时间段含人工校对事件，请缩小范围或创建新项目。')
        data['cues']=[c for c in data['cues'] if not overlaps(c)]
        checkpoint={'key':key,'cursor':start-.0001,'status':'running','calls':0,'tracker':{'tracks':[]},'last_discovery':-999.,'mode':MODE,'version':VERSION,'unreadable_samples':0};data['scan']=checkpoint;project.save(history=True)
    # Optional throughput knobs for long batch jobs; defaults keep the shipped behaviour.
    scan_gap = float(config.get('interval') or _os.environ.get('STUDIO_DYNAMIC_DISCOVERY') or 0) or (INTERVAL if config['profile']=='enhanced' else DISCOVERY_INTERVAL)
    scan_width = int(_os.environ.get('STUDIO_DYNAMIC_WIDTH') or 1280)
    tracker=DynamicTracker(checkpoint['tracker'],data.get('progressive',{}).get('display','first'),start, max(.35 if config['profile']=='enhanced' else MISS_GRACE, scan_gap*1.3))
    ocr=VisionOCR();started=saved=time.monotonic()
    try:
        if data['language'] not in ocr.request({'operation':'languages'})['languages']:raise ValueError('系统 OCR 不支持所选语言。')
        for at,image in frames(meta['path'],checkpoint['cursor']+.0001,end,INTERVAL,meta):
            if cancel.is_set():raise Cancelled()
            items=[]
            enhanced = config['profile'] == 'enhanced'
            discovery_interval = scan_gap
            discovered = at-checkpoint.get('last_discovery',-999)>=discovery_interval-.0001 or not tracker.state['tracks']
            if discovered:
                scale=min(1.,scan_width/image.shape[1]);small=np.array(Image.fromarray(image).resize((round(image.shape[1]*scale),round(image.shape[0]*scale)),Image.Resampling.LANCZOS)) if scale<1 else image
                result=ocr.recognize(small,data['language']);items=[{**item,'_resolution':scale} for item in result['items']];checkpoint['last_discovery']=at
                checkpoint['unreadable_samples']+=int(bool(result.get('unreadable')))
            if enhanced or not discovered:
                # Long batch jobs can throttle the per-track re-read; discovery still
                # covers the whole frame every scan_gap seconds.
                recheck = float(_os.environ.get('STUDIO_DYNAMIC_RECHECK') or 0) or (max(scan_gap, 1.0) if float(config.get('interval') or 0) else 0)
                run_recheck = ((not discovered) and at - checkpoint.get('last_recheck', -999.) >= recheck) if recheck > 0 else (enhanced or not discovered)
                if run_recheck and recheck > 0:
                    checkpoint['last_recheck'] = at
            else:
                run_recheck = False
            if run_recheck:
                rois = []
                global_groups=group_items(items,image.shape,config['exclusions'],True) if enhanced else []
                tracks=sorted(tracker.state['tracks'],key=lambda t:(bool(t.get('pending')),len(normalize(best_supported(t['event']) or t['event']['current']))),reverse=True) if enhanced else tracker.state['tracks']
                for track in tracks:
                    roi=search_region(track) if enhanced else expanded(track['box'],max(.012,track['box'][2]*.3),max(.02,track['box'][3]*.4))
                    if roi[2]*image.shape[1]<16 or roi[3]*image.shape[0]<12:continue
                    # Recheck readable stationary paragraphs, not every tiny animated word.
                    if enhanced and len(normalize(best_supported(track['event']) or track['event']['current'])) < 10 and not track.get('pending'):
                        continue
                    if enhanced:
                        best=best_supported(track['event']) or track['event']['current']
                        if not track.get('pending') and any(g['text']==best and association(track,g) is not None for g in global_groups):continue
                        if any(intersection(roi,region)/max(1e-9,area(roi))>.95 for region in config['review_regions']):continue
                        if len(rois)>=3:break
                    rois.append(roi)
                rois.extend(config['review_regions'] if enhanced else [])
                unique=[]
                for roi in rois:
                    if any(intersection(roi,other)/max(1e-9,area(roi)+area(other)-intersection(roi,other))>.85 for other in unique):continue
                    unique.append(roi)
                for roi in unique:
                    result=ocr.recognize(crop(image,roi),data['language'])
                    items.extend(mapped_items(result,roi))
            groups=group_items(items,image.shape,config['exclusions'],enhanced)
            if enhanced and at-checkpoint.get('last_coverage',-999)>=.999:
                audit_lines=[i for i in deduplicate(items,True) if not any(b[0]<=i['box'][0]+i['box'][2]/2<=b[0]+b[2] and b[1]<=i['box'][1]+i['box'][3]/2<=b[1]+b[3] for b in config['exclusions'])]
                checkpoint.setdefault('coverage_observations',[]).append({'time':at,'groups':[{'text':g['text'],'box':g['box'],'confidence':g['confidence']} for g in audit_lines]})
                checkpoint['last_coverage']=at
            present_ids=[t['id'] for t in tracker.state['tracks'] if presence_matches(image,t,enhanced)];data['cues'].extend(tracker.observe(at,groups,present_ids))
            for track in tracker.state['tracks']:
                for current in [track,track.get('pending')]:
                    if not current:continue
                    if enhanced:recover_visibility(current,at,image)
                    if not current.get('presence') or (enhanced and best_supported(current['event']) and current.get('presence_text') != best_supported(current['event'])):
                        current['presence_box']=list(current['box']);current['presence']=capture_presence(image,current['presence_box'])
                        current['presence_text']=best_supported(current['event'])
                    best=best_supported(current['event'])
                    group=next((g for g in groups if g['text']==best and association(current,g) is not None),None)
                    if group and best not in current['evidence']:
                        roi=expanded(current['box']);path=project.directory/'evidence'/f"dynamic-{current['id']}-{hashlib.sha256(best.encode()).hexdigest()[:12]}.jpg"
                        if roi[2]*image.shape[1]>=16 and roi[3]*image.shape[0]>=12:
                            Image.fromarray(crop(image,roi)).save(path);current['evidence'][best]={'path':str(path),'time':at,'box':roi}
                            if len(current['evidence'])>5:
                                removed=next(k for k in current['evidence'] if k!=best);old=current['evidence'].pop(removed);Path(old['path']).unlink(missing_ok=True)
            checkpoint.update(cursor=at,status='running')
            if time.monotonic()-saved>=.8:
                checkpoint['calls']+=ocr.calls;ocr.calls=0;data['cues'].sort(key=lambda c:(c['start'],c['box'][1],c['box'][0]));project.save()
                emit({'stage':'scan','status':'running','time':at,'total':end,'count':len(data['cues']),'objects':[{'id':t['id'],'box':t['box']} for t in tracker.state['tracks']], 'message':f"全画面识别：当前 {len(tracker.state['tracks'])} 个文字对象"});saved=time.monotonic()
        data['cues'].extend(tracker.finish(end))
        # OCR is finished: a cancellation during gap review resumes review,
        # without rediscovering the final frames as duplicate new events.
        checkpoint['cursor']=end
        if config['profile']=='enhanced':
            from worker.coverage import finalize_enhanced, audit_observations, recover_short_gaps
            finalize_enhanced(data['cues'])
            recover_short_gaps(project,lambda value:emit({**value,'stage':'scan'}),cancel,ocr)
            checkpoint['coverage_report']=audit_observations(data['cues'],checkpoint.get('coverage_observations',[]))
        checkpoint.update(cursor=end,status='complete');data['cues'].sort(key=lambda c:(c['start'],c['box'][1],c['box'][0]));check_dynamic_cues(data['cues'],data['style']);return project.snapshot()
    except Cancelled:checkpoint['status']='cancelled';raise
    except Exception:checkpoint['status']='failed';raise
    finally:
        checkpoint['calls']+=ocr.calls;checkpoint['elapsed']=checkpoint.get('elapsed',0)+time.monotonic()-started;project.save();ocr.close()


def layout(cue,meta,style,allow_annotation=False):
    width,height=meta['width'],meta['height']
    left,top,right,bottom=pixel_box(cue,meta,style,cue['box'])
    available_w=max(1,right-left-8);available_h=max(1,bottom-top-6)
    for size in range(max(12,min(100,int(style['fontSize']))),11,-1):
        font=ImageFont.truetype(str(chinese_font()[0]),size)
        lines=[]
        for original in cue.get('translation','').splitlines() or ['']:
            line=''
            for char in original:
                if line and font.getlength(line+char)>available_w:lines.append(line);line=''
                line+=char
            lines.append(line)
        if max((font.getlength(line) for line in lines),default=0)<=available_w and len(lines)*size*1.3<=available_h:return {'box':[left,top,right,bottom],'font_size':size,'text':'\n'.join(lines),'fits':True}
    if allow_annotation:
        # A separate transparent text box never expands the original cover.
        size=min(24,max(12,int(style['fontSize'])))
        font=ImageFont.truetype(str(chinese_font()[0]),size)
        max_width=max(1,min(width-12,max(80,width*.4)));lines=[]
        for original in cue.get('translation','').splitlines() or ['']:
            line=''
            for char in original:
                if line and font.getlength(line+char)>max_width:lines.append(line);line=''
                line+=char
            lines.append(line)
        text_width=min(width-8,max(24,math.ceil(max((font.getlength(line) for line in lines),default=0))+8))
        text_height=math.ceil(len(lines)*size*1.3)+6
        if text_height<=height-8:
            x=max(4,min(width-text_width-4,(left+right-text_width)/2))
            y=top-text_height-4 if top>=text_height+8 else min(height-text_height-4,bottom+4)
            return {'box':[left,top,right,bottom],'text_box':[x,y,x+text_width,y+text_height],
                    'font_size':size,'text':'\n'.join(lines),'fits':True,'annotation':True}
    return {'box':[left,top,right,bottom],'font_size':12,'text':cue.get('translation',''),'fits':False}


def prepare_presentation(project):
    if project.data.get('dynamic',{}).get('profile')!='enhanced':return
    for cue in project.data['cues']:
        if eligible(cue) and not cue.get('manual') and cue['box'][3]*project.data['meta']['height']<12 and cue.get('confidence',0)<.8:
            cue.update(dynamic_verified=False,recognition_issue='文字过小且证据较弱，保留原画；请校对并确认。')


def check_dynamic_cues(cues,style=None):
    from worker.core import check_cues
    check_cues(cues,style)


def write_dynamic_ass(project,path):
    prepare_presentation(project)
    data=project.data;width,height=data['meta']['width'],data['meta']['height'];style=data['style'];events=[]
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Chinese,{chinese_font()[1]},36,{ass_color(style['color'])},&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,5,0,0,0,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
'''
    for cue in data['cues']:
        if not eligible(cue):continue
        if not cue.get('translation','').strip() or cue.get('translation_status')=='stale':raise ValueError('存在已确认但尚未完成翻译的事件，请先翻译或校对。')
        cue_style={**style,'mode':cue.get('render_mode',style['mode']) if style['mode']!='above' else 'above'}
        enhanced=data.get('dynamic',{}).get('profile')=='enhanced' and not cue.get('manual')
        fitted=layout(cue,data['meta'],cue_style,enhanced)
        if not fitted['fits']:raise ValueError('译文无法放入字幕框，请调整区域、字号或译文后导出。')
        left,top,right,bottom=fitted['box'];mid_x=(left+right)//2;mid_y=(top+bottom)//2
        if fitted.get('annotation'):
            box=fitted['text_box']
            cue.update(annotation_box=[box[0]/width,box[1]/height,(box[2]-box[0])/width,(box[3]-box[1])/height],annotation_font_size=fitted['font_size'],render_mode='outline',render_issue='译文较长，使用无背景中文注释；原画保留，请预览核对。')
            mid_x=(box[0]+box[2])/2;mid_y=(box[1]+box[3])/2
        if cue_style['mode']=='cover' and not fitted.get('annotation'):
            drawing=f"{{\\an7\\pos({left},{top})\\bord0\\shad0\\1c{ass_color(style['background'])}\\p1}}m 0 0 l {right-left} 0 l {right-left} {bottom-top} l 0 {bottom-top}"
            for a,b in visible_intervals(cue):events.append(f'Dialogue: 0,{ass_time(a)},{ass_time(b)},Chinese,,0,0,0,,{drawing}')
        elif cue_style['mode']=='above' and not fitted.get('annotation'):
            text_height=len(fitted['text'].splitlines())*fitted['font_size']*1.3
            mid_y=round(max(text_height/2+3,min(height-text_height/2-3,top-text_height/2-4)))
        text=f"{{\\an5\\pos({mid_x},{mid_y})\\fs{fitted['font_size']}\\q2}}"+ass_text(fitted['text'])
        for a,b in visible_intervals(cue,True):events.append(f'Dialogue: 1,{ass_time(a)},{ass_time(b)},Chinese,,0,0,0,,{text}')
    Path(path).write_text(header+'\n'.join(events)+'\n',encoding='utf-8')


def export_dynamic_srt(project,output,bilingual=False):
    prepare_presentation(project)
    output=Path(output)
    if output.exists():raise ValueError('输出已存在，请选择新文件名。')
    rows=[]
    for cue in project.data['cues']:
        if not eligible(cue):continue
        if not cue.get('translation','').strip() or cue.get('translation_status')=='stale':raise ValueError('存在尚未完成翻译的已确认事件。')
        for a,b in visible_intervals(cue,True):rows.append((a,b,cue['translation']+('\n'+cue['source'] if bilingual else '')))
    if not rows:raise ValueError('没有已确认且可导出的字幕事件，请校对候选。')
    rows.sort(key=lambda row:row[0]);output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_name(output.name+'.partial');temporary.write_text('\n'.join(f'{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n' for i,(a,b,text) in enumerate(rows,1)),encoding='utf-8');temporary.replace(output)
    project.data['outputs'].append(str(output));project.save();return {'path':str(output),'events':len(rows)}


def extra_issues(cue,cues):
    if cue.get('ignored'):return ['已忽略此事件，导出保留原画面']
    issues=[]
    if not cue.get('dynamic_verified'):issues.append('未确认事件，导出保留原画面')
    if eligible(cue):
        for other in cues:
            if other['id']==cue['id'] or not eligible(other):continue
            if intersection(cue['box'],other['box'])/max(1e-9,min(area(cue['box']),area(other['box'])))>.1 and any(max(a,c)<min(b,d)-.02 for a,b in visible_intervals(cue) for c,d in visible_intervals(other)):
                issues.append('同屏字幕框重叠，请调整区域');break
    return issues


def merge_objects(project,first_id,second_id):
    if first_id==second_id:raise ValueError('请选择另一个明确的字幕对象。')
    cues=project.data['cues'];first=next(c for c in cues if c['id']==first_id);second=next(c for c in cues if c['id']==second_id)
    if first.get('recognition_mode')!=MODE or second.get('recognition_mode')!=MODE:raise ValueError('请选择当前全画面模式中的两个对象。')
    import copy
    merged=copy.deepcopy(first);merged.update(source=first['source']+'\n'+second['source'],translation=(first['translation']+'\n'+second['translation']).strip(),box=union([first['box'],second['box']]),
        start=min(first['start'],second['start']),end=max(first['end'],second['end']),first_seen=min(first['first_seen'],second['first_seen']),disappeared_at=max(first['disappeared_at'],second['disappeared_at']),
        dynamic_verified=first.get('dynamic_verified',False) and second.get('dynamic_verified',False),manual=True,manual_time=True,manual_translation=bool(first['translation'] and second['translation']),
        translation_status='manual' if first['translation'] and second['translation'] else 'missing',complete_time=None,complete_supported=False,recognition_issue='人工合并了指定对象，请核对范围和时间',
        detection_items=first.get('detection_items',[])+second.get('detection_items',[]),evidence_frames=first.get('evidence_frames',[])+second.get('evidence_frames',[]))
    spans=[]
    for a,b in sorted(visible_intervals(first)+visible_intervals(second)):
        if spans and a<=spans[-1][1]+.001:spans[-1][1]=max(b,spans[-1][1])
        else:spans.append([a,b])
    merged.update(visible_intervals=spans,cover_intervals=spans,original_start=merged['first_seen'],original_end=merged['disappeared_at'])
    project.save(history=True);cues[:]=[merged if c['id']==first_id else c for c in cues if c['id']!=second_id];cues.sort(key=lambda c:c['start']);check_dynamic_cues(cues,project.data['style']);project.save();return project.snapshot()


def split_time(project,cue_id,at):
    import copy,uuid
    cues=project.data['cues'];first=next(c for c in cues if c['id']==cue_id)
    if not first['start']+.05<at<first['end']-.05:raise ValueError('拆分位置需在当前事件时间内。')
    second=copy.deepcopy(first);spans=visible_intervals(first);project.save(history=True)
    second.update(id=str(uuid.uuid4()),start=at,manual=True,manual_time=True);second['object_id']=second['id']
    first.update(end=at,manual=True,manual_time=True)
    for cue,lo,hi in [(first,first['first_seen'],at),(second,at,second['disappeared_at'])]:
        clipped=[[max(a,lo),min(b,hi)] for a,b in spans if max(a,lo)<min(b,hi)]
        cue.update(visible_intervals=clipped,cover_intervals=clipped,first_seen=lo,disappeared_at=hi,original_start=lo,original_end=hi)
    cues.append(second);cues.sort(key=lambda c:c['start']);check_dynamic_cues(cues,project.data['style']);project.save();return project.snapshot()


def split_object(project,cue_id,axis,fraction,cancel=None):
    """Explicit spatial repair. Single-frame rereads require user confirmation."""
    import copy,uuid
    if axis not in ('x','y') or not isinstance(fraction,(int,float)) or not .1<=fraction<=.9:raise ValueError('请选择左右或上下划分，分界需在 10% 到 90% 之间。')
    original=next(c for c in project.data['cues'] if c['id']==cue_id)
    if original.get('recognition_mode')!=MODE:raise ValueError('区域划分仅适用于全画面模式。')
    x,y,w,h=original['box'];boxes=([[x,y,w*fraction,h],[x+w*fraction,y,w*(1-fraction),h]] if axis=='x' else [[x,y,w,h*fraction],[x,y+h*fraction,w,h*(1-fraction)]])
    for box in boxes:
        validate_roi(box)
        if box[2]*project.data['meta']['width']<16 or box[3]*project.data['meta']['height']<12:raise ValueError('划分后的区域过小，请调整分界或对象范围。')
    when=next((e['time'] for e in original.get('evidence_frames',[]) if e['text']==original['source']), (original['start']+original['end'])/2)
    at,image=next(frames(project.data['meta']['path'],when,None,INTERVAL,project.data['meta']));ocr=VisionOCR();parts=[]
    try:
        for box in boxes:
            if cancel and cancel.is_set():raise Cancelled()
            result=ocr.recognize(crop(image,box),project.data['language'])
            if not result['text'].strip():raise ValueError('某个子区域未读出文字，请调整范围或分界，原事件未修改。')
            part=copy.deepcopy(original);identity=str(uuid.uuid4());path=project.directory/'evidence'/f'dynamic-split-{identity}.jpg';Image.fromarray(crop(image,box)).save(path)
            part.update(id=identity,object_id=identity,box=box,source=result['text'],translation='',translation_status='missing',manual=True,manual_time=True,manual_translation=False,
                        screenshot=str(path),screenshot_box=box,evidence_frames=[{'text':result['text'],'path':str(path),'time':at,'box':box}],quality_support=1,
                        complete_supported=False,complete_time=None,dynamic_verified=False,confidence=result['confidence'],recognition_issue='区域划分仅复读单帧，请校对文字与时间后确认事件',
                        growth=[{'text':result['text'],'first':at,'last':at,'count':1,'confidence':result['confidence']}],detection_items=[])
            parts.append(part)
        if cancel and cancel.is_set():raise Cancelled()
        project.save(history=True);project.data['cues']=[c for c in project.data['cues'] if c['id']!=cue_id]+parts;project.data['cues'].sort(key=lambda c:c['start']);check_dynamic_cues(project.data['cues'],project.data['style']);project.save();return project.snapshot()
    finally:ocr.close()
