"""Credentials are passed over stdin; errors exclude request bodies and headers."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from worker.visual_review import review_request
try:
    value=json.loads(sys.stdin.readline())
    print(json.dumps({'result':review_request(value['config'],value['cue'],value.get('key',''))},ensure_ascii=False))
except Exception as exc:
    # Remote response content may contain user data; keep transport failures
    # useful while hiding unexpected parsing details.
    message=str(exc) if isinstance(exc,(RuntimeError,ValueError)) and not isinstance(exc,json.JSONDecodeError) else '图像复核响应不可用，请重试。'
    print(json.dumps({'error':message},ensure_ascii=False))
