"""Translate the cues of a project through the configured model service."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DEFAULT_WORKDIR, Worker, api_key, project_path  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='翻译字幕（DeepSeek / OpenAI 兼容 / Ollama）')
    parser.add_argument('project')
    parser.add_argument('--workdir', default=str(DEFAULT_WORKDIR))
    parser.add_argument('--api-key', default=None, help='密钥；缺省读 SUBTITLE_API_KEY 或 runtime/.apikey')
    parser.add_argument('--force', action='store_true', help='重新翻译已有译文（人工译文仍受保护）')
    parser.add_argument('--retries', type=int, default=3, help='接口失败时的重试次数')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    folder = project_path(args.project, Path(args.workdir))
    key = api_key(args.api_key)
    worker = Worker()
    started = time.time()
    try:
        project = worker.call('open', {'directory': str(folder)})
        provider = project['translation']['provider']
        pending = [cue for cue in project['cues']
                   if (cue.get('dynamic_verified') or project.get('recognition_mode') != 'dynamic')
                   and not cue.get('ignored') and not cue.get('manual_translation')
                   and (args.force or not cue.get('translation') or cue.get('translation_status') == 'stale')]
        print(f"{folder.name}: 模型={project['translation'].get('model') or provider}  "
              f"待翻译 {len(pending)} 条")
        for attempt in range(1, args.retries + 1):
            try:
                worker.call('translate', {'apiKey': key, 'force': args.force})
                status, project, error = worker.wait_job(quiet=not args.verbose)
                if status != 'complete':
                    raise RuntimeError(error or status)
                break
            except Exception as exc:  # network hiccups are common on long jobs
                if attempt == args.retries:
                    raise
                print(f'  第 {attempt} 次失败：{exc}；重试…')
                time.sleep(5)
        translated = [cue for cue in project['cues'] if cue.get('translation')]
        print(f'完成：{len(translated)} 条有译文，用时 {(time.time()-started)/60:.1f} 分钟')
        for cue in translated[:5]:
            print(f"  {cue['start']:7.1f}  {cue['source'][:42]!r} → {cue['translation'][:30]}")
    finally:
        worker.close()


if __name__ == '__main__':
    main()