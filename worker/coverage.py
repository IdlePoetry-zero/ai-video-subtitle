"""Source-observation audit and conservative duplicate suppression.

The audit covers what OCR actually read, not unknowable ground truth. Its flags
remain visible for review and are never silently translated or marked verified.
"""
from difflib import SequenceMatcher
from worker.quality import similar, literal_reference


def complete_read(items, source):
    """Require the whole paragraph, including numbers and negation, in this frame."""
    lines=source.splitlines()
    reads=[i['text'] for i in sorted(items,key=lambda i:(i['box'][1],i['box'][0])) if i['confidence']>=.8]
    return bool(reads) and canonical(' '.join(reads))==canonical(' '.join(lines))


def recover_short_gaps(project, emit=lambda value:None, cancel=None, ocr=None):
    """Fill only gaps whose EVERY source frame independently reads the same text.

    No interpolation, boundary extension, text similarity or pixel-only votes.
    A blank, incomplete/new sentence or hard scene transition vetoes the gap.
    """
    import threading
    import numpy as np
    from PIL import Image
    from worker.core import VisionOCR, frames, crop, Cancelled, file_fingerprint
    from worker.dynamic import eligible, visible_intervals, expanded, deduplicate
    data=project.data;meta=data['meta'];cancel=cancel or threading.Event()
    if data.get('recognition_mode')!='dynamic' or data.get('dynamic',{}).get('profile')!='enhanced':return
    if data.get('fingerprint_version')==1 and file_fingerprint(meta['path'])!=data['fingerprint']:raise ValueError('原视频内容已经变化，请创建新项目。')
    finalize_enhanced(data['cues'])
    owned=ocr is None;ocr=ocr or VisionOCR();checked=restored=0
    try:
        for cue in data['cues']:
            if cancel.is_set():raise Cancelled()
            if not eligible(cue) or cue.get('manual') or cue.get('dedup_original_intervals') or len(canonical(cue['source']))<10:continue
            spans=visible_intervals(cue);out=[spans[0][:]] if spans else []
            for left,right in zip(spans,spans[1:]):
                a,b=left[1],right[0];evidence=[];valid=0<b-a<=.301;previous=None
                if valid:
                    checked+=1
                    for at,image in frames(meta['path'],max(0.,a-1/max(1.,meta['fps'])),b+1/max(1.,meta['fps']),0.,meta):
                        if cancel.is_set():raise Cancelled()
                        scene=np.asarray(Image.fromarray(image).resize((64,36)).convert('L'),dtype=float)/255
                        if previous is not None and np.mean(np.abs(scene-previous))>.25:valid=False;break
                        previous=scene
                        if not a<=at<b:continue
                        result=ocr.recognize(crop(image,expanded(cue['box'],.015,.015)),data['language'])
                        if not complete_read(deduplicate(result['items'],True),cue['source']):valid=False;break
                        evidence.append(round(at,6))
                    valid=valid and len(evidence)>=2
                if valid:
                    out[-1][1]=right[1];restored+=1
                    cue.setdefault('gap_recovery',[]).append({'start':a,'end':b,'frame_times':evidence,'method':'every-source-frame-exact-ocr'})
                else:out.append(right[:])
            if out!=spans:
                cue.setdefault('gap_recovery_original_intervals',[s[:] for s in spans])
                cue.update(visible_intervals=out,cover_intervals=[s[:] for s in out])
            if checked:emit({'stage':'audit','status':'running','message':f'逐帧复核短时漏显：已检查 {checked} 处，恢复 {restored} 处'})
        data.setdefault('scan',{})['gap_recovery_report']={'checked':checked,'restored':restored,'method':'逐帧完整原文一致才恢复；空白、换句与切镜保留缺口。'}
    finally:
        project.save()
        if owned:ocr.close()


def audit_source(project, emit=lambda value:None, cancel=None, start=0., end=None):
    """Independent native OCR pass, including intervals with no existing event."""
    import threading
    import numpy as np
    from PIL import Image
    from worker.core import VisionOCR, frames, crop, Cancelled, file_fingerprint
    from worker.dynamic import deduplicate, mapped_items, DEFAULTS
    data=project.data;meta=data['meta'];end=min(meta['duration'],end if end is not None else meta['duration'])
    if data.get('recognition_mode')!='dynamic':raise ValueError('原文覆盖复核适用于全画面模式。')
    if not 0<=start<end:raise ValueError('复核时间范围无效。')
    if data.get('fingerprint_version')==1 and file_fingerprint(meta['path'])!=data['fingerprint']:raise ValueError('原视频内容已经变化，请创建新项目。')
    config={**DEFAULTS,**data.get('dynamic',{})};cancel=cancel or threading.Event()
    observations=[];ocr=VisionOCR()
    try:
        recover_short_gaps(project,emit,cancel,ocr)
        for at,image in frames(meta['path'],start,end,1.,meta):
            if cancel.is_set():raise Cancelled()
            scale=min(1.,1280/image.shape[1])
            small=np.array(Image.fromarray(image).resize((round(image.shape[1]*scale),round(image.shape[0]*scale)),Image.Resampling.LANCZOS)) if scale<1 else image
            items=[{**item,'_resolution':scale} for item in ocr.recognize(small,data['language'])['items']]
            for roi in config['review_regions']:
                items.extend(mapped_items(ocr.recognize(crop(image,roi),data['language']),roi))
            lines=[i for i in deduplicate(items,True) if not any(b[0]<=i['box'][0]+i['box'][2]/2<=b[0]+b[2] and b[1]<=i['box'][1]+i['box'][3]/2<=b[1]+b[3] for b in config['exclusions'])]
            observations.append({'time':at,'groups':[{'text':g['text'],'box':g['box'],'confidence':g['confidence']} for g in lines]})
            if len(observations)%5==0:emit({'stage':'audit','status':'running','time':at,'total':end,'message':'正在独立读取原片，检查未生成字幕的区段'})
        report=audit_observations(data['cues'],observations)
        report.update(start=start,end=end,independent_pass=True)
        data.setdefault('scan',{})['coverage_report']=report
        project.save(history=True)
        return project.snapshot()
    finally:ocr.close()


def canonical(text):
    return ''.join(c.casefold() for c in text if c.isalnum())


def source_matches(observed, source):
    observed_text=observed
    observed = canonical(observed)
    lines = [source, *source.splitlines()]
    return any(observed in canonical(line) or canonical(line) in observed or
               similar(observed_text, line) for line in lines if canonical(line))


def audit_observations(cues, observations):
    from worker.dynamic import eligible, visible_intervals, intersection, area
    gaps = []
    for sample in observations:
        at = sample['time']
        active = [c for c in cues if eligible(c) and any(a <= at < b for a,b in visible_intervals(c, True))]
        for group in sample['groups']:
            if group['confidence'] < .8 or len(canonical(group['text'])) < 10:continue
            if literal_reference(group['text']):continue
            matching = [c for c in active if intersection(group['box'], c['box']) / max(1e-9, min(area(group['box']), area(c['box']))) > .5 and source_matches(group['text'], c['source'])]
            if not matching:
                gaps.append({'time':at,'source':group['text'],'box':group['box'],'confidence':group['confidence']})
    return {'status':'complete','samples':len(observations),'suspected_gaps':gaps,
            'method':'对照每秒实际 OCR 读到的高置信度文字；疑似缺口需校对，不代表所有原文的完整性证明。'}


def finalize_enhanced(cues):
    from worker.dynamic import eligible, visible_intervals, intersection, area, union, bounded, deduplicate
    automatic = [c for c in cues if eligible(c) and not c.get('manual')]
    for cue in automatic:
        if literal_reference(cue['source']):
            cue.update(ignored=True,recognition_issue='网址保留原样，不自动翻译或覆盖。')
            continue
        items = cue.get('detection_items', [])
        cleaned=deduplicate(items,True) if all('confidence' in i for i in items) else items
        if items and len(cleaned)<len(items) and canonical(' '.join(i['text'] for i in items))==canonical(cue['source']):
            cue['source_before_physical_dedup']=cue['source']
            cue['source']='\n'.join(i['text'] for i in sorted(cleaned,key=lambda i:(i['box'][1],i['box'][0])))
            cue['detection_items']=items=cleaned
            if cue.get('translation'):cue['translation_status']='stale'
        if items:
            actual = bounded(union([i['box'] for i in items]))
            original = cue['box']
            if actual[2] > 0 and actual[3] > 0:
                cue['detection_extent'] = original
                cue['box'] = actual
                if len(canonical(cue['source']))<=24 and (area(original)>max(.025,2*area(actual)) or actual[3]>.08 or area(actual)>.025):
                    cue['render_mode']='outline'
                    cue['recognition_issue']='大字或移动文字保留原画，以描边中文注释；请生成预览核对。'
    for short in automatic:
        for complete in automatic:
            if short['id']==complete['id']:continue
            short_text=canonical(short['source']);full_text=canonical(complete['source'])
            same=short_text==full_text
            contained=any(short_text==canonical(line) for line in complete['source'].splitlines())
            if not contained and not same:continue
            if same and (complete.get('quality_support',0), complete['id']) <= (short.get('quality_support',0),short['id']):continue
            if intersection(short['box'],complete['box'])/max(1e-9,min(area(short['box']),area(complete['box'])))<.65:continue
            before=visible_intervals(short);spans=[s[:] for s in before]
            for left,right in visible_intervals(complete):
                out=[]
                for a,b in spans:
                    if b<=left or a>=right:out.append([a,b]);continue
                    if a<left:out.append([a,left])
                    if b>right:out.append([right,b])
                spans=out
            if spans!=before:
                short.setdefault('dedup_original_intervals',before)
                short.update(visible_intervals=spans,cover_intervals=spans)
                if not spans:short['ignored']=True
