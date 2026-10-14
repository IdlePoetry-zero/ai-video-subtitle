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
