import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import subprocess
import shutil
import threading
import time

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from worker.core import (Project, compatible, validate_translations, translate_request, translate,
                         Cancelled, cancellable_translation, write_ass, export_srt, export_video,
                         frames, probe, scan, ROOT, ffmpeg_progress_time, event_to_cue)

VIDEO = ROOT / 'artifacts/fixtures/硬字幕 测试视频.mp4'


@pytest.fixture
def project(tmp_path):
    p = Project.create(VIDEO, tmp_path / '中文 project')
    # Seed data only for isolated edit/transport/render tests; OCR acceptance uses pixels separately.
    reference = json.loads((ROOT / 'artifacts/fixtures/reference.json').read_text())
    p.data['cues'] = [event_to_cue({'id': str(i), 'start': item['start']-.01,
        'end': item['end']-.01, 'roi': p.data['roi'], 'screenshot': '',
        'variants': {item['text']: {'count': 3, 'confidence': .99}}}) for i,item in enumerate(reference)]
    translate(p)
    p.save()
    yield p
    p.close()


def test_near_text_cannot_merge_different_numbers_or_negation():
    assert compatible('Hello again.', 'Hello again.')
    assert not compatible('We need 12 samples, not 20.', 'We need 20 samples, not 20.')
    assert not compatible('Do not overwrite edits.', 'Do overwrite edits.')


def test_ffmpeg_initial_na_progress_is_not_an_export_failure():
    assert ffmpeg_progress_time('out_time_us=N/A') is None
    assert ffmpeg_progress_time('out_time_us=3500000') == 3.5
    assert ffmpeg_progress_time('fps=25') is None


def test_validation_rejects_missing_duplicate_and_empty_translations():
    for value in ({'translations': []}, {'translations': [{'id': 'a', 'text': '甲'}, {'id': 'a', 'text': '乙'}]}, {'translations': [{'id': 'a', 'text': ''}, {'id': 'b', 'text': '乙'}]}):
        with pytest.raises(ValueError): validate_translations(value, ['a', 'b'])
    assert validate_translations({'translations': [{'id': 'a', 'text': '甲'}, {'id': 'b', 'text': '乙'}]}, ['a', 'b']) == {'a': '甲', 'b': '乙'}


def test_edits_persist_undo_and_translation_protection(project):
    first = project.data['cues'][0]
    project.edit_cue(first['id'], {'source': 'A corrected source.'})
    assert first['translation_status'] == 'stale'
    project.edit_cue(first['id'], {'translation': '人工译文。', 'start': 2.05})
    translate(project, force=True)
    assert first['translation'] == '人工译文。'
    restored = Project(project.directory)
    assert restored.data['cues'][0]['translation'] == '人工译文。'
    assert restored.data['cues'][0]['start'] == 2.05
    restored.close()
    result = project.undo()
    assert result['cues'][0]['source'] == 'A corrected source.'
    assert result['cues'][0]['translation'] != '人工译文。'


def test_invalid_edit_never_overwrites_saved_project(project):
    first = copy.deepcopy(project.data['cues'][0])
    with pytest.raises(ValueError): project.edit_cue(first['id'], {'start': 10, 'end': 5})
    assert project.data['cues'][0] == first
    with pytest.raises(ValueError): project.update({'roi': [0, .9, 1, .5]})
    with pytest.raises(ValueError): project.update({'translation': {'apiKey': 'not-a-real-key'}})


def test_cover_timing_is_independent_of_edited_translation_timing(project, tmp_path):
    first = project.data['cues'][0]
    first['start'] = 3
    first['translation'] = '中文 {\\p1} 字幕'
    output = tmp_path / 'render.ass'
    write_ass(project, output)
    content = output.read_text()
    assert 'Dialogue: 0,0:00:01.99,0:00:04.99' in content
    assert 'Dialogue: 1,0:00:03.00' in content
    assert '中文 ｛＼p1｝ 字幕' in content


def test_srt_requires_translation_and_never_overwrites(project, tmp_path):
    output = tmp_path / '字幕.srt'
    project.data['cues'][0]['translation'] = ''
    with pytest.raises(ValueError): export_srt(project, output)
    translate(project)
    export_srt(project, output, bilingual=True)
    assert '欢迎使用' in output.read_text()
    assert 'Welcome to the subtitle studio.' in output.read_text()
    with pytest.raises(ValueError): export_srt(project, output)


@pytest.fixture
def service():
    received = []
    release = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received.append((self.path, body, self.headers.get('Authorization')))
            if body['model'] == 'slow-contract-test': release.wait(5)
            payload = json.loads(body['messages'][1]['content'])
            content = json.dumps({'translations': [{'id': cue['id'], 'text': '传输契约测试译文。'} for cue in payload['targets']]})
            response = {'message': {'content': content}} if self.path == '/api/chat' else {'choices': [{'message': {'content': content}}]}
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
            try: self.wfile.write(json.dumps(response).encode())
            except BrokenPipeError: pass
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield f'http://127.0.0.1:{server.server_port}', received
    release.set(); server.shutdown(); server.server_close(); thread.join()


def test_api_and_ollama_transport_contracts(project, service):
    base, received = service
    batch = project.data['cues'][:2]
    for provider in ('api', 'ollama'):
        config = {'provider': provider, 'baseUrl': base + ('/v1' if provider == 'api' else ''), 'model': 'contract-test', 'glossary': 'Studio = 工作室'}
        response = translate_request(config, batch, batch, 'transport-test-not-a-real-key')
        assert len(response) == 2
    assert received[0][0] == '/v1/chat/completions'
    assert received[0][1]['response_format'] == {'type': 'json_object'}
    assert received[0][2] == 'Bearer transport-test-not-a-real-key'
    assert received[1][0] == '/api/chat'
    assert received[1][1]['format'] == 'json'
    assert received[1][1]['stream'] is False
    assert 'glossary' in json.loads(received[1][1]['messages'][1]['content'])


@pytest.mark.parametrize('base,thinking', [
    ('https://api.deepseek.com', {'type': 'disabled'}),
    ('https://api.example.com/v1', None),
])
def test_deepseek_batch_translation_disables_default_thinking_only_at_official_host(monkeypatch, base, thinking):
    import io
    import urllib.request
    received = []
    class Opener:
        def open(self, request, timeout):
            received.append(json.loads(request.data))
            content = json.dumps({'translations': [{'id': 'a', 'text': '希望不会花太久。'}]})
            return io.BytesIO(json.dumps({'choices': [{'message': {'content': content}}]}).encode())
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Opener())
    response = translate_request({'provider': 'api', 'baseUrl': base, 'model': 'deepseek-flash'},
                                 [{'id': 'a', 'source': "Hopefully it won't take long."}], [], 'test-only')
    assert response == {'a': '希望不会花太久。'}
    assert received[0].get('thinking') == thinking
    assert received[0]['response_format'] == {'type': 'json_object'}


def test_translation_transport_cancels_without_installing_model(project, service):
    cancel = threading.Event()
    timer = threading.Timer(.6, cancel.set); timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(Cancelled):
            cancellable_translation({'provider': 'ollama', 'baseUrl': service[0], 'model': 'slow-contract-test'}, project.data['cues'][:1], [], '', cancel)
    finally:
        timer.cancel()
    assert time.monotonic() - started < 3


def test_variable_timestamps_use_pts_not_average_rate():
    path = ROOT / 'artifacts/fixtures/variable-timestamps.mp4'
    timestamps = [timestamp for timestamp, _ in frames(path, interval=0)]
    deltas = {round(b-a, 3) for a,b in zip(timestamps,timestamps[1:])}
    assert deltas == {.08,.12}
    assert all(b>a for a,b in zip(timestamps,timestamps[1:]))
    assert abs(timestamps[-1] - (len(timestamps)-1) / probe(path)['fps']) > .01


def test_cancel_export_removes_partial_and_preserves_original(project, tmp_path):
    cancel = threading.Event(); cancel.set()
    output = tmp_path / '未完成.mp4'
    size = VIDEO.stat().st_size
    with pytest.raises(Cancelled): export_video(project, output, cancel=cancel)
    assert not output.exists()
    assert not list(output.parent.glob('未完成*.partial.mp4'))
    assert VIDEO.stat().st_size == size


def test_export_preserves_variable_frame_count_and_timestamps(tmp_path):
    source = ROOT / 'artifacts/fixtures/variable-timestamps.mp4'
    p = Project.create(source, tmp_path / 'vfr-project')
    try:
        duration = p.data['meta']['duration']
        p.data['cues'] = [{'id':'vfr','start':0.,'end':duration,'source':'Timestamp test.',
                          'translation':'时间戳验证','translation_status':'manual','confidence':1.,
                          'issues':[],'box':p.data['roi']}]
        before = [t for t,_ in frames(source, interval=0)]
        output = tmp_path / 'vfr-output.mp4'
        export_video(p, output)
        after = [t for t,_ in frames(output, interval=0)]
        assert len(after) == len(before)
        assert after == pytest.approx(before, abs=.002)
    finally:
        p.close()


def test_file_content_change_invalidates_saved_scan(tmp_path):
    source = tmp_path / 'source.mp4'
    shutil.copyfile(VIDEO, source)
    p = Project.create(source, tmp_path / 'project')
    try:
        # Change trailing media bytes while retaining a valid MP4 container.
        with source.open('r+b') as stream:
            stream.seek(-100, 2)
            original = stream.read(1)
            stream.seek(-1, 1)
            stream.write(bytes([original[0] ^ 1]))
        with pytest.raises(ValueError, match='原视频内容已经变化'):
            scan(p)
    finally:
        p.close()


def test_failed_import_preserves_open_project_and_missing_video_can_relocate(tmp_path):
    source = tmp_path / '原视频.mp4'
    shutil.copyfile(VIDEO, source)
    process = subprocess.Popen([sys.executable, str(ROOT/'worker/server.py')],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    counter = 0
    def rpc(method, **params):
        nonlocal counter
        counter += 1
        process.stdin.write(json.dumps({'id':counter, 'method':method, 'params':params})+'\n')
        process.stdin.flush()
        return json.loads(process.stdout.readline())
    try:
        first = rpc('create', video=str(source), directory=str(tmp_path/'project'))['result']
        assert 'error' in rpc('create', video=str(tmp_path/'absent.mp4'), directory=str(tmp_path/'failed'))
        assert rpc('snapshot')['result']['id'] == first['id']
        relocated = source.with_name('移动后的 原视频.mp4')
        source.rename(relocated)
        assert rpc('snapshot')['result']['missing_video']
        recovered = rpc('relocate', video=str(relocated))['result']
        assert not recovered['missing_video']
        assert recovered['meta']['path'] == str(relocated)
        assert recovered['id'] == first['id']
    finally:
        process.stdin.close()
        process.wait(timeout=5)
