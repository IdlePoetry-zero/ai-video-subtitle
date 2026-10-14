from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import threading
import uuid
import traceback

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image
from worker.core import (Project, VisionOCR, Cancelled, scan, translate, recommend, frames,
                         export_video, export_srt, check_cues, compatible, ffmpeg_path, prepare_proxy, file_fingerprint, probe)

output_lock = threading.Lock()
project = None
job = None
cancel = threading.Event()


def send(payload):
    with output_lock:
        print(json.dumps(payload, ensure_ascii=False), flush=True)


def require_project():
    if project is None or not project.data:
        raise ValueError("请先导入视频或打开项目。")
    return project


def idle():
    if job and job.is_alive():
        raise ValueError("任务正在运行，请等待完成或先取消。")


def start_job(kind, params):
    global job, cancel
    idle()
    p = require_project()
    cancel = threading.Event()
    job_id = str(uuid.uuid4())
    p.data["task"] = {"id": job_id, "stage": kind, "status": "running"}
    p.save()

    def progress(value):
        p.data["task"].update(value)
        send({"event": "progress", "job": job_id, **value})

    def run():
        global job
        result = None
        error = None
        status = "complete"
        try:
            if kind == "scan":
                result = scan(p, progress, cancel, params.get("start", 0), params.get("end"), params.get("force", False))
                if not p.data["cues"]:
                    progress({"stage": "scan", "status": "complete", "message": "未识别到字幕，请检查区域与语言后重试。"})
            elif kind == "review":
                from worker.visual_review import review
                result = review(p, params["id"], params.get("apiKey", ""), cancel)
            elif kind == "split_object":
                from worker.dynamic import split_object
                result = split_object(p, params["id"], params.get("axis", "x"), params.get("fraction", .5), cancel)
            elif kind == "translate":
                result = translate(p, progress, cancel, params.get("ids"), params.get("apiKey", ""), params.get("force", False))
            elif kind == 'audit':
                from worker.coverage import audit_source
                result = audit_source(p, progress, cancel, params.get('start',0.), params.get('end'))
            elif kind in ("export", "preview"):
                result = export_video(p, params["output"], progress, cancel, params.get("start"), params.get("end"))
            elif kind == "recommend":
                result = recommend(p)
            elif kind == "proxy":
                result = prepare_proxy(p, progress, cancel)
        except Cancelled:
            status = "cancelled"
        except Exception as exc:
            status, error = "failed", str(exc)
            # Stack trace contains no request payload or model credentials.
            traceback.print_exc(file=sys.stderr)
        finally:
            p.data["task"].update(status=status)
            if error:
                p.data["task"]["error"] = error
            p.save()
            completed_snapshot=p.snapshot()
            # All project writes are finished before advertising completion.
            # A client may immediately resume after the terminal notification;
            # the old thread can still be flushing stdout at that instant.
            job=None
            send({"event": "job", "job": job_id, "stage": kind, "status": status,
                  "result": result if kind in ("recommend", "preview", "export", "proxy") else None,
                  "error": error, "project": completed_snapshot})

    job = threading.Thread(target=run, daemon=True)
    job.start()
    return {"job": job_id}


def invoke(method, params):
    global project
    if method == "cancel":
        cancel.set()
        return {"requested": bool(job and job.is_alive())}
    if method == "snapshot":
        return require_project().snapshot()
    if method in ("scan", "audit", "translate", "review", "export", "preview", "recommend", "proxy", "split_object"):
        return start_job(method, params)
    idle()
    if method == "dependencies":
        ocr = VisionOCR()
        try:
            return {"ffmpeg": ffmpeg_path(), "ocr": ocr.request({"operation": "languages"}), "python": sys.version.split()[0]}
        finally:
            ocr.close()
    if method in ("create", "open"):
        if method == "open" and not (Path(params["directory"]) / "project.sqlite").is_file():
            raise ValueError("该目录没有可用项目，请选择包含 project.sqlite 的目录。")
        candidate = Project.create(params["video"], params["directory"]) if method == "create" else Project(params["directory"])
        if not candidate.data:
            candidate.close()
            raise ValueError("该目录没有可用项目，请选择包含 project.sqlite 的目录。")
        if project:
            project.close()
        project = candidate
        if project.data.get("task", {}).get("status") == "running":
            project.data["task"]["status"] = "cancelled"
            project.save()
        return project.snapshot()
    p = require_project()
    if method == "relocate":
        meta = probe(params["video"])
        fingerprint = file_fingerprint(meta["path"])
        if p.data.get("fingerprint_version") == 1 and fingerprint != p.data["fingerprint"]:
            raise ValueError("选中的视频与原项目不同，请选择原视频文件，或创建新项目。")
        p.data.update(meta=meta, fingerprint=fingerprint, fingerprint_version=1)
        p.save(history=True)
        return p.snapshot()
    if method == "update":
        return p.update(params["changes"])
    if method == "edit":
        return p.edit_cue(params["id"], params["changes"])
    if method == "undo":
        return p.undo()
    if method == "check":
        check_cues(p.data["cues"], p.data["style"], p.data["translation"].get("glossary", ""))
        p.save()
        return p.snapshot()
    if method == "frame":
        timestamp = float(params.get("time", 0))
        meta = p.data["meta"]
        timestamp = max(0., min(timestamp, meta["duration"] - .05))
        _, pixels = next(frames(meta["path"], timestamp, None, .1, meta))
        output = p.directory / "evidence" / f"frame-{timestamp:.3f}.jpg"
        Image.fromarray(pixels).save(output)
        return {"path": str(output), "time": timestamp}
    if method == "srt":
        return export_srt(p, params["output"], params.get("bilingual", False))
    if method == "merge":
        if p.data.get("recognition_mode") == "dynamic":
            from worker.dynamic import merge_objects
            if not params.get("second_id"):
                raise ValueError("全画面模式需要明确选择另一个对象，不能按时间列表自动合并下一条。")
            return merge_objects(p, params["id"], params["second_id"])
        cues = p.data["cues"]
        index = next(i for i, cue in enumerate(cues) if cue["id"] == params["id"])
        if index + 1 >= len(cues):
            raise ValueError("已经是最后一条字幕。")
        first, second = cues[index:index + 2]
        first["source"] += "\n" + second["source"]
        first["translation"] = (first["translation"] + "\n" + second["translation"]).strip()
        first["end"] = second["end"]
        first["cover_intervals"] = first.get("cover_intervals", [[first["original_start"], first["original_end"]]]) + second.get("cover_intervals", [[second["original_start"], second["original_end"]]])
        first.update(manual=True, manual_translation=bool(first["translation"]), translation_status="manual" if first["translation"] else "missing")
        if first.get("recognition_mode") in ("progressive", "progressive_hq"):
            first.update(manual_time=True, disappeared_at=second.get("disappeared_at", second["end"]),
                         complete_time=None, complete_supported=False, complete_evidence_text=None)
            first["growth"] = first.get("growth", []) + second.get("growth", [])
        del cues[index + 1]
        check_cues(cues, p.data["style"], p.data["translation"].get("glossary", ""))
        p.save(history=True)
        return p.snapshot()
    if method == "split":
        if p.data.get("recognition_mode") == "dynamic":
            from worker.dynamic import split_time
            return split_time(p, params["id"], float(params["time"]))
        cues = p.data["cues"]
        index = next(i for i, cue in enumerate(cues) if cue["id"] == params["id"])
        first = cues[index]
        at = float(params["time"])
        if not first["start"] + .05 < at < first["end"] - .05:
            raise ValueError("拆分位置需在当前字幕时间内。")
        second = json.loads(json.dumps(first))
        second.update(id=str(uuid.uuid4()), start=at, manual=True, manual_time=True)
        first.update(end=at, manual=True, manual_time=True)
        # Split by visual lines when possible; otherwise user may edit each half.
        for field in ("source", "translation"):
            lines = first[field].splitlines()
            if len(lines) > 1:
                first[field], second[field] = lines[0], "\n".join(lines[1:])
        for cue in (first, second):
            if cue.get("recognition_mode") in ("progressive", "progressive_hq"):
                cue.update(manual_translation=bool(cue["translation"]),
                           translation_status="manual" if cue["translation"] else "missing")
        cues.insert(index + 1, second)
        check_cues(cues, p.data["style"], p.data["translation"].get("glossary", ""))
        p.save(history=True)
        return p.snapshot()
    raise ValueError("未知操作。")


def shutdown(signum, frame):
    cancel.set()
    if job and job.is_alive():
        job.join(4)
    raise SystemExit(0)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
for line in sys.stdin:
    request = {}
    try:
        request = json.loads(line)
        result = invoke(request["method"], request.get("params", {}))
        send({"id": request["id"], "result": result})
    except Exception as exc:
        send({"id": request.get("id"), "error": str(exc)})
shutdown(None, None)
