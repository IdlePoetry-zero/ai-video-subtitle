import copy
from pathlib import Path
import subprocess

import numpy as np
import pytest

from worker.appearance import pixel_box, source_box, remember_text_box, local_repair_filters
from worker.core import ROOT, Project, write_ass, export_video, ffmpeg_path, frames, probe


def test_crop_relative_quality_box_and_growth_are_mapped_to_frame():
    cue = {'box': [.1, .6, .8, .3], 'body_box': [.25, .5, .5, .2]}
    assert source_box(cue, [0, 0, 1, 1]) == pytest.approx([.3, .75, .4, .06])
    event = {'roi': [.1, .6, .8, .3]}
    remember_text_box(event, {'items': [{'text': 'Hello', 'box': [.25, .5, .2, .2]}]})
    remember_text_box(event, {'items': [{'text': 'Hello world.', 'box': [.25, .5, .5, .2]}]})
    assert event['source_box'] == pytest.approx([.3, .75, .4, .06])
    style = {'mode': 'cover', 'coverArea': 'text', 'padding': 0}
    left, top, right, bottom = pixel_box(cue, {'width': 1000, 'height': 1000}, style, [0, 0, 1, 1])
    assert 299 <= left <= 300 and top == 750 and right == 700 and 810 <= bottom <= 811
    # A manually corrected dynamic box supersedes inherited quality evidence.
    cue.update(recognition_mode='dynamic', box=[.5, .5, .1, .1])
    assert source_box(cue, [0, 0, 1, 1]) == [.5, .5, .1, .1]


def test_local_repair_uses_visibility_gaps_and_skips_unconfirmed_objects():
    base = {'id': 'a', 'recognition_mode': 'dynamic', 'box': [.1, .2, .3, .1],
            'source': 'Hello.', 'translation': '你好。', 'start': 1, 'end': 5,
            'dynamic_verified': True, 'visible_intervals': [[1, 2], [3, 5]]}
    data = {'recognition_mode': 'dynamic', 'meta': {'width': 1000, 'height': 500, 'duration': 10},
            'style': {'mode': 'delogo', 'padding': 0}, 'roi': [0, 0, 1, 1],
            'cues': [base, {**base, 'id': 'b', 'box': [.6, .2, .3, .1], 'dynamic_verified': False}]}
    filters = local_repair_filters(data, 1.5, 4)
    assert len(filters) == 1
    assert 'x=100:y=100:w=300:h=51' in filters[0] or 'x=100:y=100:w=300:h=50' in filters[0]
    assert 'gte(t,1.500000)*lt(t,2.000000)' in filters[0]
    assert 'gte(t,3.000000)*lt(t,4.000000)' in filters[0]
    data['cues'][0]['ignored'] = True
    assert not local_repair_filters(data)


def test_real_ffmpeg_local_repair_is_spatially_and_temporally_bounded(tmp_path):
    # Lossless RGB output isolates filter changes from video compression.
    width, height = 160, 90
    pixels = np.full((height, width, 3), (36, 92, 128), np.uint8)
    pixels[38:45, 63:90] = 255
    cue = {'box': [60/width, 35/height, 35/width, 15/height], 'start': .25, 'end': .75}
    data = {'style': {'mode': 'delogo', 'padding': 0}, 'meta': {'width': width, 'height': height, 'duration': 1},
            'roi': [0, 0, 1, 1], 'cues': [cue]}
    script = tmp_path / 'filters.txt'
    script.write_text(','.join(local_repair_filters(data)))
    raw = pixels.tobytes() * 4
    process = subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-f', 'rawvideo',
                              '-pixel_format', 'rgb24', '-video_size', f'{width}x{height}', '-framerate', '4',
                              '-i', 'pipe:0', '-filter_script:v', str(script), '-pix_fmt', 'rgb24',
                              '-f', 'rawvideo', 'pipe:1'], input=raw, capture_output=True, check=True)
    result = np.frombuffer(process.stdout, np.uint8).reshape(4, height, width, 3)
    assert np.array_equal(result[0], pixels) and np.array_equal(result[3], pixels)
    outside = np.ones((height, width), bool); outside[35:51, 60:96] = False
    assert np.array_equal(result[1][outside], pixels[outside])
    assert np.max(np.abs(result[1, 38:45, 63:90].astype(int) - [36, 92, 128])) <= 1


def test_tight_and_legacy_cover_exports_and_no_background_repair(tmp_path):
    project = Project.create(ROOT / 'artifacts/fixtures/硬字幕 测试视频.mp4', tmp_path / 'project')
    try:
        cue = {'id': 'a', 'source': 'Hello.', 'translation': '你好。', 'translation_status': 'translated',
               'start': 2, 'end': 4, 'box': [.04, .76, .92, .21],
               'body_box': [.3, .25, .4, .3], 'recognition_mode': 'progressive_hq',
               'cover_intervals': [[1.8, 4.2]]}
        project.data['cues'] = [cue]
        ass = tmp_path / 'render.ass'
        write_ass(project, ass)
        tight = ass.read_text()
        assert 'Dialogue: 0,0:00:01.80,0:00:04.20' in tight
        saved_body = cue['body_box']
        cue['body_box'] = [.3, .25, .003, .2]
        write_ass(project, ass)
        assert '你好。' in ass.read_text()
        # Translation layout falls back without widening the narrow source cover.
        cover = next(line for line in ass.read_text().splitlines() if line.startswith('Dialogue: 0,'))
        assert ' l 12 0' in cover or ' l 13 0' in cover
        cue['body_box'] = saved_body
        project.data['style'].pop('coverArea')
        write_ass(project, ass)
        legacy = ass.read_text()
        assert tight != legacy
        project.data['style']['mode'] = 'delogo'
        write_ass(project, ass)
        assert 'Dialogue: 0,' not in ass.read_text()
        output = tmp_path / 'repair.mp4'
        export_video(project, output, start=2, end=3)
        meta = probe(output)
        assert (meta['width'], meta['height']) == (1280, 720) and meta['audio']
        assert abs(meta['duration'] - 1) < .1
        prior = copy.deepcopy(project.data)
        with pytest.raises(ValueError):
            project.update({'style': {**project.data['style'], 'padding': float('nan')}})
        assert project.data == prior
    finally:
        project.close()
