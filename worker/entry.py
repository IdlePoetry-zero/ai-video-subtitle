"""Single frozen executable: RPC server and isolated OCR child."""
import runpy
import sys
from pathlib import Path
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdin.reconfigure(encoding='utf-8')

if '--ocr-worker' in sys.argv:
    from worker.ocr_rapid import main
    main()
elif '--translation-worker' in sys.argv:
    runpy.run_module('worker.translation_client', run_name='__main__')
elif '--visual-worker' in sys.argv:
    runpy.run_module('worker.visual_client', run_name='__main__')
else:
    runpy.run_module('worker.server', run_name='__main__')
