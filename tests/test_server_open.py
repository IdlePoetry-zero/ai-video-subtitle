import json
import subprocess
import sys
from worker.core import ROOT


def test_open_non_project_does_not_create_files(tmp_path):
 directory=tmp_path/'ordinary-folder';directory.mkdir()
 request={'id':1,'method':'open','params':{'directory':str(directory)}}
 result=subprocess.run([sys.executable,str(ROOT/'worker/server.py')],input=json.dumps(request)+'\n',text=True,capture_output=True,timeout=10)
 response=json.loads(result.stdout.splitlines()[0])
 assert 'error' in response and not list(directory.iterdir())
