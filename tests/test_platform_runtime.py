import subprocess
import sys
from worker.platform_runtime import LineReader


def test_pipe_reader_handles_unicode_multiple_buffered_lines_and_eof():
    child = subprocess.Popen([sys.executable,'-c', "import sys;sys.stdout.buffer.write('中文\\nsecond\\n'.encode('utf-8'));sys.stdout.flush()"],
                             stdout=subprocess.PIPE,text=True,encoding='utf-8')
    reader = LineReader(child.stdout)
    assert reader.get(10) == '中文\n'
    assert reader.get(10) == 'second\n'
    assert reader.get(10) is None
    assert child.wait(5) == 0


def test_windows_quality_keeps_sole_sentence_but_respects_exclusion(monkeypatch):
    from worker import quality
    monkeypatch.setattr(quality,'rapid_ocr',lambda:True)
    item={'text':'Hello world.','confidence':.98,'box':[.02,.2,.16,.25]}
    result={'items':[item],'unreadable':False}
    assert quality.select_body(result,[0,0,1,1])['text']=='Hello world.'
    assert quality.select_body(result,[0,0,1,1],{'exclusions':[[0,0,.3,.6]]})['text']==''
    item['text']='Back'
    assert quality.select_body(result,[0,0,1,1])['text']==''


def test_external_encoder_does_not_read_parent_rpc_stdin():
    from worker.platform_runtime import external_process
    process=external_process([sys.executable,'-c','import sys;print(len(sys.stdin.read()))'],
                             stdout=subprocess.PIPE,text=True)
    output,_=process.communicate(timeout=5)
    assert process.returncode==0 and output.strip()=='0'
    monkeypatch.setattr(quality,'rapid_ocr',lambda:False)
    item['text']='Hello world.'
    assert quality.select_body(result,[0,0,1,1])['text']==''
