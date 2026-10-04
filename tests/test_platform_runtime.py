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
