import subprocess
import sys
import pytest
from worker.export_lock import export_lock


@pytest.mark.parametrize('crash', [False, True])
def test_second_process_cannot_export_and_crash_releases_lock(tmp_path, crash):
    script = ('from pathlib import Path;import sys;'
              'from worker.export_lock import export_lock;'
              'lock=export_lock(Path(sys.argv[1]));lock.__enter__();'
              'print("locked",flush=True);sys.stdin.readline();lock.__exit__(None,None,None)')
    child = subprocess.Popen([sys.executable, '-u', '-c', script, str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'locked'
        with pytest.raises(ValueError, match='已有导出任务'):
            with export_lock(tmp_path):
                pytest.fail('Two processes acquired the same project export lock')
        if crash:
            child.kill()
            child.wait(timeout=5)
        else:
            child.communicate('\n', timeout=5)
        with export_lock(tmp_path):
            pass
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
