"""Cancellable transport helper. Credentials arrive on stdin, never on the command line."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from worker.core import translate_request
try:
    value = json.loads(sys.stdin.readline())
    result = translate_request(value["config"], value["batch"], value["context"], value.get("key", ""))
    print(json.dumps({"result": result}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"error": str(exc), "format_error": isinstance(exc, (ValueError, KeyError))}, ensure_ascii=False))
