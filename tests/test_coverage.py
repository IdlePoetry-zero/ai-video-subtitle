import pytest
from worker.coverage import audit_observations, finalize_enhanced, source_matches


BOX=[.1,.3,.7,.15]


def cue(identity, source, spans, support=5, box=None):
    return {'id':identity,'source':source,'box':box or BOX[:], 'start':spans[0][0],'end':spans[-1][1],
            'visible_intervals':spans,'cover_intervals':spans,'dynamic_verified':True,'confidence':1.,
            'quality_support':support,'ignored':False}


def test_source_audit_finds_a_gap_and_accepts_multiline_subsets():
    c=cue('whole','First sentence.\nSecond sentence.',[[1,2]])
    groups=[{'text':'Second sentence.','box':BOX,'confidence':1.}]
    report=audit_observations([c],[{'time':1.5,'groups':groups},{'time':2.5,'groups':groups}])
    assert report['samples']==2
    assert [gap['time'] for gap in report['suspected_gaps']]==[2.5]


def test_audit_does_not_hide_negation_or_number_replacements():
    assert not source_matches('Do not overwrite.','Do overwrite.')
    assert not source_matches('Spend 12.','Spend 20.')


def test_duplicates_suppress_only_shared_times_and_locations():
    a=cue('line','Second sentence.',[[1,3]])
    b=cue('whole','First sentence.\nSecond sentence.',[[2,4]])
    distant=cue('elsewhere','Second sentence.',[[1,3]],box=[.1,.7,.7,.15])
    finalize_enhanced([a,b,distant])
    assert a['visible_intervals']==[[1,2]]
    assert b['visible_intervals']==[[2,4]]
    assert distant['visible_intervals']==[[1,3]]


def test_manual_events_and_numbers_are_not_suppressed():
    manual=cue('manual','Second sentence.',[[1,3]]);manual['manual']=True
    whole=cue('whole','First sentence.\nSecond sentence.',[[1,3]])
    twelve=cue('12','Spend 12.',[[1,3]])
    twenty=cue('20','Spend 20.',[[1,3]])
    finalize_enhanced([manual,whole,twelve,twenty])
    assert all(c['visible_intervals']==[[1,3]] and not c['ignored'] for c in [manual,twelve,twenty])


def test_moving_extent_does_not_become_large_opaque_cover():
    c=cue('moving','Hello.',[[1,3]])
    c['box']=[.1,.1,.8,.7]
    c['detection_items']=[{'box':[.4,.4,.12,.07],'text':'Hello.'}]
    finalize_enhanced([c])
    assert c['box']==pytest.approx([.4,.4,.12,.07])
    assert c['render_mode']=='outline'


def test_literal_url_is_preserved_without_a_false_gap():
    link=cue('url','https://example.org/12',[[1,3]])
    finalize_enhanced([link]);assert link['ignored']
    report=audit_observations([link],[{'time':2.,'groups':[{'text':link['source'],'box':BOX,'confidence':1.}]}])
    assert report['suspected_gaps']==[]


def test_complete_gap_read_preserves_numbers_negation_and_all_rows():
    from worker.coverage import complete_read
    def items(text):return [{'text':line,'box':[0,i*.1,1,.08],'confidence':1.} for i,line in enumerate(text.splitlines())]
    assert complete_read(items('Do not spend 12.\nKeep it.'),'Do not spend 12.\nKeep it.')
    for wrong in ['Do spend 12.\nKeep it.','Do not spend 20.\nKeep it.','Keep it.','']:
        assert not complete_read(items(wrong),'Do not spend 12.\nKeep it.')


@pytest.mark.parametrize('failure',[None,'blank','changed','cut','manual','legacy'])
def test_gap_recovery_requires_every_actual_frame(monkeypatch,failure):
    import numpy as np
    import worker.core as core
    from worker.coverage import recover_short_gaps
    c=cue('whole','Do not spend 12.',[[1,1.2],[1.4,2]])
    if failure=='manual':c['manual']=True
    class Project:
        data={'meta':{'path':'unused','fps':20.},'recognition_mode':'dynamic','language':'en-US',
              'dynamic':{'profile':'legacy' if failure=='legacy' else 'enhanced'},'cues':[c]}
        def save(self):pass
    samples=[(1.15,np.zeros((200,400,3),dtype=np.uint8))]+[(t,np.full((200,400,3),255 if failure=='cut' and t>=1.3 else 0,dtype=np.uint8)) for t in [1.2,1.25,1.3,1.35,1.4]]
    monkeypatch.setattr(core,'frames',lambda *args:iter(samples))
    class OCR:
        calls=0
        def recognize(self,*args):
            self.calls+=1;text='Do not spend 12.'
            if self.calls==2 and failure=='blank':return {'items':[]}
            if self.calls==2 and failure=='changed':text='Do spend 12.'
            return {'items':[{'text':text,'box':[0,0,1,1],'confidence':1.}]}
    recover_short_gaps(Project(),ocr=OCR())
    assert c['visible_intervals']==([[1,2]] if failure is None else [[1,1.2],[1.4,2]])
    if failure is None:assert len(c['gap_recovery'][0]['frame_times'])==4


def test_identical_same_frame_row_deduplicates_crop_height_variation():
    from worker.dynamic import deduplicate
    reads=[{'text':'Same whole sentence.','confidence':1.,'box':b} for b in [[.2,.4,.6,.02],[.2,.39,.6,.04],[.2,.7,.6,.02]]]
    assert len(deduplicate(reads,True))==2
    assert len(deduplicate(reads,False))==2


def test_existing_duplicate_read_repair_requires_physical_evidence():
    text='Same whole sentence.'
    c=cue('double',text+' '+text,[[1,2]])
    c.update(translation='old',translation_status='complete',detection_items=[{'text':text,'box':b,'confidence':1.} for b in [[.2,.877,.45,.034],[.2,.884,.45,.031]]])
    finalize_enhanced([c])
    assert c['source']==text and c['translation_status']=='stale'
    distant=cue('intentional',text+' '+text,[[1,2]])
    distant['detection_items']=[{'text':text,'box':b,'confidence':1.} for b in [[.2,.4,.45,.03],[.2,.6,.45,.03]]]
    finalize_enhanced([distant])
    assert distant['source']==text+' '+text


def test_cancelled_gap_review_saves_partial_progress_without_filling():
    import threading
    from worker.core import Cancelled
    from worker.coverage import recover_short_gaps
    c=cue('whole','A complete sentence.',[[1,1.2],[1.4,2]])
    class Project:
        saved=False
        data={'meta':{'path':'unused','fps':20},'recognition_mode':'dynamic','dynamic':{'profile':'enhanced'},'cues':[c]}
        def save(self):self.saved=True
    class OCR:pass
    p=Project();cancel=threading.Event();cancel.set()
    with pytest.raises(Cancelled):recover_short_gaps(p,cancel=cancel,ocr=OCR())
    assert p.saved and c['visible_intervals']==[[1,1.2],[1.4,2]]


def test_gap_and_audit_do_not_confuse_decimal_or_lost_apostrophe():
    from worker.coverage import complete_read
    for observed,expected in [('Spend 12 dollars.','Spend 1.2 dollars.'),("I cant do this.","I can't do this.")]:
        items=[{'text':observed,'box':BOX,'confidence':1.}]
        assert not complete_read(items,expected)
        assert not source_matches(observed,expected)
