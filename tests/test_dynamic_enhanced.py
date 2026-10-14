"""Regression for growing search bounds and evidence-backed short OCR misses."""
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont
from worker.dynamic import DynamicTracker, recover_visibility, search_region, visible_intervals, presence_matches, group_items

BOX = [.1, .3, .5, .15]


def group(text='A complete sentence.'):
    return {'text': text, 'box': BOX[:], 'confidence': 1., 'items': []}


def frame(blank=False):
    pixels = np.zeros((200, 400, 3), dtype=np.uint8)
    if not blank:
        # A stable high-contrast glyph-like silhouette, independent of OCR votes.
        pixels[62:87, 50:95] = 255
        pixels[64:85, 120:180] = 255
        pixels[61:88, 200:232] = 255
    return pixels


def test_pending_long_sentence_expands_only_search_not_cover():
    tracker = DynamicTracker()
    for t in [1., 1.1, 1.2]:
        tracker.observe(t, [group()])
    track = tracker.state['tracks'][0]
    old = track['box'][:]
    longer = {**group('A different and much longer sentence.'), 'box': [.1, .3, .85, .15]}
    tracker.observe(1.3, [longer])
    assert track['pending']
    region = search_region(track)
    assert region[0] + region[2] >= .95
    assert track['box'] == old  # Expanded OCR bounds never turn into cover bounds.


@pytest.mark.parametrize('blank,expect_bridge', [(False, True), (True, False)])
def test_short_miss_requires_pixels_from_the_missed_frame(blank, expect_bridge):
    tracker = DynamicTracker(miss_grace=.35)
    for t in [1., 1.1, 1.2]:
        tracker.observe(t, [group()])
        recover_visibility(tracker.state['tracks'][0], t, frame())
    tracker.observe(1.3, [])
    recover_visibility(tracker.state['tracks'][0], 1.3, frame(blank))
    tracker.observe(1.4, [group()])
    recover_visibility(tracker.state['tracks'][0], 1.4, frame())
    cue = tracker.finish(1.5)[0]
    assert any(a <= 1.3 < b for a, b in visible_intervals(cue)) == expect_bridge
    assert cue['quality_support'] == 4  # Recovered pixels are never fake OCR votes.


def test_long_real_disappearance_is_not_bridged():
    tracker = DynamicTracker(miss_grace=.35)
    for t in [1., 1.1, 1.2]:
        tracker.observe(t, [group()])
        recover_visibility(tracker.state['tracks'][0], t, frame())
    out = []
    for t in [1.3, 1.4, 1.5, 1.6, 1.7]:
        out.extend(tracker.observe(t, []))
        for track in tracker.state['tracks']:
            recover_visibility(track, t, frame(True))
    for t in [1.8, 1.9, 2.]:
        out.extend(tracker.observe(t, [group()]))
    out.extend(tracker.finish(2.1))
    assert len(out) == 2
    assert not any(a <= 1.5 < b for cue in out for a, b in visible_intervals(cue))


@pytest.mark.parametrize('first,changed',[('We need 12.','We need 20.'),('Do not erase.','Do erase.')])
def test_same_words_returning_do_not_hide_a_changed_digit_or_negation(first,changed):
    def pixels(text):
        image=Image.new('RGB',(400,200),'black')
        ImageDraw.Draw(image).text((45,64),text,font=ImageFont.load_default(size=20),fill='white')
        return np.array(image)
    tracker=DynamicTracker(miss_grace=.35)
    for at in [1.,1.1,1.2]:
        tracker.observe(at,[group(first)])
        recover_visibility(tracker.state['tracks'][0],at,pixels(first))
    track=tracker.state['tracks'][0]
    assert not presence_matches(pixels(changed),track,strict=True)
    tracker.observe(1.3,[])
    recover_visibility(track,1.3,pixels(changed))
    tracker.observe(1.4,[group(first)])
    recover_visibility(track,1.4,pixels(first))
    assert not any(a<=1.3<b for cue in tracker.finish(1.5) for a,b in visible_intervals(cue))


def test_header_and_url_have_independent_stability_and_objects():
    items=[{'text':'Read more next week.','box':[.1,.8,.7,.04],'confidence':1.},
           {'text':'https://example.org/12','box':[.1,.855,.7,.03],'confidence':.55}]
    groups=group_items(items,(720,1280,3),enhanced=True)
    assert [g['text'] for g in groups]==['Read more next week.','https://example.org/12']
    assert groups[0]['confidence']==1.


def test_large_effect_word_does_not_merge_into_small_dialogue_row():
    items=[{'text':'BIG','box':[.1,.25,.4,.14],'confidence':1.},
           {'text':'Normal dialogue.','box':[.45,.3,.5,.04],'confidence':1.}]
    assert len(group_items(items,(720,1280,3),enhanced=True))==2


def test_competing_reads_and_cropped_fragments_are_not_concatenated():
    items=[{'text':'We need 12.','box':BOX,'confidence':1.,'_resolution':1.},
           {'text':'We need I2.','box':BOX,'confidence':1.,'_resolution':.67}]
    assert [g['text'] for g in group_items(items,(720,1280,3),enhanced=True)]==['We need 12.']
    items=[{'text':'Read this entire sentence.','box':BOX,'confidence':.95},
           {'text':'entire sentence.','box':[.3,.3,.3,.15],'confidence':1.}]
    assert [g['text'] for g in group_items(items,(720,1280,3),enhanced=True)]==['Read this entire sentence.']
