import { useEffect, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import type { Cue, Project, ROI, Settings, Task, TranslationConfig } from './types';

const api = window.studio;
const emptyConfig: TranslationConfig = { provider: 'mock', baseUrl: 'http://localhost:11434', model: '', glossary: '' };
const languages = [{ value: 'en-US', name: '英语 · 已验证' }, { value: 'ja-JP', name: '日语 · 待验证' }, { value: 'ko-KR', name: '韩语 · 待验证' }, { value: 'fr-FR', name: '法语 · 待验证' }, { value: 'de-DE', name: '德语 · 待验证' }, { value: 'es-ES', name: '西班牙语 · 待验证' }, { value: 'ru-RU', name: '俄语 · 待验证' }];
function clock(value: number) { return `${Math.floor(value / 60).toString().padStart(2, '0')}:${(value % 60).toFixed(1).padStart(4, '0')}`; }
function filename(value: string) { return value.split(/[\\/]/).pop() || value; }
function clamp(value: number, min: number, max: number) { return Math.max(min, Math.min(max, value)); }
function captionBox(cue: Cue | undefined, project: Project, fallback: ROI): ROI {
  let box = cue?.box || fallback;
  if (cue && project.style.mode !== 'above' && (project.style.coverArea === 'text' || project.style.mode === 'delogo') && cue.recognition_mode !== 'dynamic') {
    if (cue.source_box) box = cue.source_box;
    else if (cue.body_box) { const b = cue.body_box; box = [box[0] + b[0] * box[2], box[1] + b[1] * box[3], b[2] * box[2], b[3] * box[3]]; }
  }
  const px = project.style.padding / project.meta.width, py = project.style.padding / project.meta.height;
  const left = Math.max(0, box[0] - px), top = Math.max(0, box[1] - py);
  return [left, top, Math.min(1, box[0] + box[2] + px) - left, Math.min(1, box[1] + box[3] + py) - top];
}

export default function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [sourceUrl, setSourceUrl] = useState('');
  const [poster, setPoster] = useState('');
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewStart, setPreviewStart] = useState(0);
  const [selected, setSelected] = useState('');
  const [time, setTime] = useState(0);
  const [busy, setBusy] = useState(false);
  const [task, setTask] = useState<Task>({ stage: 'ready', status: 'idle' });
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [roi, setRoi] = useState<ROI>([.04, .76, .92, .21]);
  const roiRef = useRef(roi);
  const [regionEditing, setRegionEditing] = useState(false);
  const [search, setSearch] = useState('');
  const [onlyIssues, setOnlyIssues] = useState(false);
  const [loop, setLoop] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [config, setConfig] = useState<TranslationConfig>(emptyConfig);
  const [settingsInfo, setSettingsInfo] = useState<Settings | null>(null);
  const [key, setKey] = useState('');
  const [ocrInfo, setOcrInfo] = useState<{engine: string; languages: string[]} | null>(null);
  const [sampleStart, setSampleStart] = useState(0);
  const [sampleEnd, setSampleEnd] = useState(15);
  const [screenshot, setScreenshot] = useState('');
  const [draft, setDraft] = useState({ source: '', translation: '', start: 0, end: 1 });
  const draftRef = useRef(draft);
  const draftId = useRef('');
  const draftDirty = useRef(false);
  const [replaceFrom, setReplaceFrom] = useState('');
  const [replaceTo, setReplaceTo] = useState('');
  const video = useRef<HTMLVideoElement>(null);
  const pendingSeek = useRef<number | null>(null);
  const dynamicRenderInputs = useRef('');
  const dynamicRenderDirectory = useRef('');
  const previewView = useRef({ rendered: false, offset: 0 });
  const proxyAttempted = useRef(false);
  const gesture = useRef<{ kind: string; x: number; y: number; roi: ROI } | null>(null);
  const [showObjects, setShowObjects] = useState(true);
  const [mergeId, setMergeId] = useState('');
  const [splitAxis, setSplitAxis] = useState('x');
  const [splitFraction, setSplitFraction] = useState(50);
  const isDynamic = project?.recognition_mode === 'dynamic';
  const visibleObjects = project?.cues.filter(cue => (cue.visible_intervals || [[cue.first_seen ?? cue.start, cue.disappeared_at ?? cue.end]]).some(([a,b]) => a <= time && time < b)) || [];
  const selectedCue = project?.cues.find(cue => cue.id === selected);
  const shown = project?.cues.filter(cue => (!onlyIssues || cue.issues.length) && (!search || `${cue.source} ${cue.translation}`.toLowerCase().includes(search.toLowerCase()))) || [];
  const activeCue = project?.cues.find(cue => cue.start <= time && cue.end > time);
  const coverCue = project?.cues.find(cue => (cue.cover_intervals || [[cue.original_start ?? cue.first_seen ?? cue.start, cue.original_end ?? cue.disappeared_at ?? cue.end]]).some(([start,end]) => start <= time && end > time));
  const displayRoi = project ? captionBox(coverCue || activeCue, project, roi) : roi;
  const percentage = task.total ? clamp((task.time ?? task.count ?? 0) / task.total * 100, 0, 100) : 0;

  function receiveProject(value: Project) {
    const renderInputs = JSON.stringify([value.directory, value.recognition_mode, value.style, value.cues.map(cue => [cue.id, cue.start, cue.end, cue.translation, cue.translation_status, cue.box, cue.source_box, cue.body_box, cue.cover_intervals, cue.visible_intervals, cue.dynamic_verified, cue.ignored, cue.render_mode, cue.annotation_box, cue.annotation_font_size])]);
    if (renderInputs !== dynamicRenderInputs.current && (renderInputs || dynamicRenderInputs.current)) {
      if (previewView.current.rendered && value.directory === dynamicRenderDirectory.current && video.current) {
        const originalTime = clamp(video.current.currentTime + previewView.current.offset, 0, value.meta.duration);
        pendingSeek.current = originalTime; setTime(originalTime);
      }
      setPreviewUrl('');
    }
    dynamicRenderInputs.current = renderInputs;
    dynamicRenderDirectory.current = value.directory;
    setProject(value); setTask(value.task);
    setSelected(current => value.cues.some(cue => cue.id === current) ? current : value.cues[0]?.id || '');
  }
  async function operation<T>(action: () => Promise<T>) {
    setError('');
    try { return await action(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); return undefined; }
  }
  async function loadProject(value: Project) {
    receiveProject(value); setRoi(value.roi); roiRef.current = value.roi;
    proxyAttempted.current = Boolean(value.preview_path);
    setPreviewUrl(''); setSourceUrl(''); setTime(0);
    setSampleStart(0); setSampleEnd(Math.min(value.meta.duration, 15));
    if (value.missing_video) { setPoster(''); setError('找不到原视频。点击“重新定位原视频”选择同一个文件，编辑结果已经保留。'); return; }
    setSourceUrl(await api.mediaUrl(value.preview_path || value.meta.path));
    const frame = await api.request<{ path: string }>('frame', { time: Math.min(2, value.meta.duration / 2) });
    setPoster(await api.mediaUrl(frame.path));
    setMessage(value.recognition_mode === 'dynamic' ? '项目已保存。可继续全画面识别或校对已有事件，无需固定正文区域。' : '项目已保存。确认字幕区域后开始识别。');
  }
  async function importVideo(path?: string) {
    if (busy) return;
    if (draftDirty.current && !await saveCue()) return;
    await operation(async () => {
      const chosen = path || await api.chooseVideo(); if (!chosen) return;
      const directory = await api.newDirectory();
      const value = await api.request<Project>('create', { video: chosen, directory });
      await loadProject(value); setRegionEditing(true);
    });
  }
  async function openProject() {
    if (draftDirty.current && !await saveCue()) return;
    await operation(async () => { const directory = await api.chooseProject(); if (directory) await loadProject(await api.request('open', { directory })); });
  }
  async function relocateVideo() { await operation(async () => { const chosen = await api.chooseVideo(); if (chosen) await loadProject(await api.request('relocate', { video: chosen })); }); }
  async function update(changes: Record<string, unknown>) {
    const value = await operation(() => api.request<Project>('update', { changes }));
    if (value) { receiveProject(value); setMessage('设置已保存'); }
  }
  async function runJob(method: string, params: Record<string, unknown> = {}) {
    if (draftDirty.current && !await saveCue()) return;
    setError(''); setBusy(true); setTask({ stage: method, status: 'running', message: '正在准备任务' });
    try { await api.request(method, params); } catch (err) { setBusy(false); setError(err instanceof Error ? err.message : String(err)); }
  }
  async function changeRecognitionMode(mode: Project['recognition_mode']) {
    if (draftDirty.current && !await saveCue()) return;
    const value = await operation(() => api.request<Project>('update', { changes: { recognition_mode: mode } }));
    if (value) { receiveProject(value); setRoi(value.roi); roiRef.current = value.roi; setRegionEditing(false); setMergeId(''); setPreviewUrl(''); setMessage(`已切换到${mode === 'standard' ? '标准' : mode === 'dynamic' ? '全画面字幕' : mode === 'progressive_hq' ? '渐进高质量' : '逐步出现'}模式，另一模式的字幕与校对结果已保留。`); }
  }
  async function saveRegion() { if (!project) return; await update({ roi }); setRegionEditing(false); }
  async function scanVideo(sample = false, force = false) {
    if (!project) return;
    if (isDynamic) { setRegionEditing(false); await runJob('scan', sample ? {start:sampleStart,end:sampleEnd,force} : {force}); return; }
    const updated = await operation(() => api.request<Project>('update', { changes: { roi } }));
    if (!updated) return;
    receiveProject(updated); setRegionEditing(false);
    await runJob('scan', sample ? { start: sampleStart, end: sampleEnd, force } : { force });
  }
  async function chooseCue(cue: Cue) {
    if (draftDirty.current && !await saveCue()) return;
    setSelected(cue.id); pendingSeek.current = cue.start;
    if (previewUrl) setPreviewUrl('');
    else if (video.current) { video.current.currentTime = cue.start; pendingSeek.current = null; }
    setTime(cue.start);
  }
  async function saveCue() {
    if (!selectedCue) return true;
    const captured = { ...draftRef.current };
    const changes: Record<string, unknown> = {};
    for (const field of ['source', 'translation', 'start', 'end'] as const) if (captured[field] !== selectedCue[field]) changes[field] = captured[field];
    if (!Object.keys(changes).length) { draftDirty.current = false; return true; }
    const value = await operation(() => api.request<Project>('edit', { id: selected, changes }));
    if (value) { if (JSON.stringify(captured) === JSON.stringify(draftRef.current)) draftDirty.current = false; receiveProject(value); if (isDynamic) setPreviewUrl(''); setMessage('字幕修改已保存'); return true; }
    return false;
  }
  async function editEvent(changes: Record<string, unknown>) {
    if (!selectedCue || (draftDirty.current && !await saveCue())) return;
    const value = await operation(() => api.request<Project>('edit', {id:selectedCue.id,changes}));
    if (value) { receiveProject(value); setPreviewUrl(''); if (changes.box) setRegionEditing(false); setMessage('事件校对已保存；原画面与其他事件保留。'); }
  }
  async function mergeObjects() {
    if (!selectedCue || !mergeId || (draftDirty.current && !await saveCue())) return;
    const value = await operation(() => api.request<Project>('merge',{id:selectedCue.id,second_id:mergeId}));
    if (value) { receiveProject(value); setMergeId(''); setPreviewUrl(''); setMessage('已合并明确选中的两个对象，请核对范围和时间。'); }
  }
  function changeDraft(value: typeof draft) { draftDirty.current = true; draftRef.current = value; setDraft(value); }
  async function exportFile(extension: 'srt' | 'mp4') {
    if (!project) return;
    if (draftDirty.current && !await saveCue()) return;
    await operation(async () => {
      const output = await api.chooseOutput(extension, project.directory); if (!output) return;
      if (extension === 'mp4') await runJob('export', { output });
      else { await api.request('srt', { output }); receiveProject(await api.request('snapshot')); setMessage('已导出中文字幕 SRT；字幕文件本身不会遮盖原视频。'); }
    });
  }
  async function preview() {
    if (!project) return;
    const start = selectedCue ? Math.max(0, selectedCue.start - 1) : sampleStart;
    const end = Math.min(project.meta.duration, selectedCue ? selectedCue.end + 1 : sampleEnd);
    setPreviewStart(start);
    await runJob('preview', { output: `${project.directory}/preview-${Date.now()}.mp4`, start, end });
  }
  async function openSettings() {
    await operation(async () => { const info = await api.settings(); setSettingsInfo(info); setConfig(project?.translation || info.config); setKey(''); setSettingsOpen(true); });
  }
  async function saveSettings() {
    await operation(async () => { setSettingsInfo(await api.configure(config, key || undefined)); if (project) receiveProject(await api.request('update', { changes: { translation: config } })); setSettingsOpen(false); setKey(''); setMessage('翻译服务设置已保存'); });
  }
  async function replaceTerms() {
    if (!project || !replaceFrom) return;
    if (draftDirty.current && !await saveCue()) return;
    await operation(async () => {
      let count = 0;
      for (const cue of project.cues) if (cue.translation.includes(replaceFrom)) { await api.request('edit', { id: cue.id, changes: { translation: cue.translation.split(replaceFrom).join(replaceTo) } }); count++; }
      receiveProject(await api.request('snapshot')); setMessage(`已替换 ${count} 条译文，并作为人工修改保存。`);
    });
  }

  useEffect(() => { api.request<{ocr: {engine: string; languages: string[]}}>('dependencies').then(value => setOcrInfo(value.ocr)).catch(err => setError(String(err))); }, []);
  useEffect(() => api.subscribe(event => {
    if (event.event === 'progress') setTask({ ...event });
    if (event.event === 'fatal') { setBusy(false); setError(event.error || '处理组件异常'); }
    if (event.event === 'job') {
      setBusy(false);
      if (event.project) receiveProject(event.project);
      if (event.error) setError(event.error);
      else if (event.status === 'cancelled') setMessage('任务已取消，有效进度已保存；可继续处理。');
      else if (event.stage === 'recommend' && event.result?.roi) { setRoi(event.result.roi); roiRef.current = event.result.roi; setRegionEditing(true); setMessage(event.result.message || '请确认字幕区域'); }
      else if (event.stage === 'proxy' && event.result?.path) { api.mediaUrl(event.result.path).then(setSourceUrl).catch(err => setError(String(err))); setMessage('兼容预览已准备好，识别仍使用原视频。'); }
      else if ((event.stage === 'preview' || event.stage === 'export') && event.result?.path) {
        const path = event.result.path;
        if (event.stage === 'export') setPreviewStart(0);
        api.mediaUrl(path).then(setPreviewUrl).catch(err => setError(String(err)));
        setMessage(event.stage === 'preview' ? '效果预览已生成，与导出使用相同渲染链路。' : `视频已导出：${filename(path)}`);
      } else if (event.stage === 'scan') setMessage(event.project?.cues.length ? `识别完成，共 ${event.project.cues.length} 条字幕。` : '未识别到字幕，请检查字幕区域与语言。');
      else if (event.stage === 'split_object') setMessage('已划分两个区域并复读单帧；请分别校对文字与时间、确认事件后再翻译。');
      else if (event.stage === 'review') setMessage('图像复核完成，建议尚未采用。');
      else if (event.stage === 'translate') setMessage(event.project?.translation.provider === 'mock' ? '模拟翻译完成；未调用真实模型。' : '翻译完成，人工译文已保留。');
      else if (event.stage === 'audit') setMessage(`原文覆盖复核完成，共 ${event.project?.scan.coverage_report?.suspected_gaps.length || 0} 处疑似缺口，请校对。`);
    }
  }), []);
  useEffect(() => { roiRef.current = roi; }, [roi]);
  useEffect(() => { previewView.current = { rendered: Boolean(previewUrl), offset: previewStart }; }, [previewUrl, previewStart]);
  useEffect(() => {
    if (!selectedCue) { setScreenshot(''); return; }
    if (!draftDirty.current || draftId.current !== selectedCue.id) {
      const value = { source: selectedCue.source, translation: selectedCue.translation, start: selectedCue.start, end: selectedCue.end };
      draftId.current = selectedCue.id; draftRef.current = value; draftDirty.current = false; setDraft(value);
    }
    let live = true;
    api.mediaUrl(selectedCue.screenshot).then(url => { if (live) setScreenshot(url); }).catch(() => setScreenshot(''));
    return () => { live = false; };
  }, [selectedCue]);
  useEffect(() => {
    if (busy || !draftDirty.current) return;
    const timer = setTimeout(() => { void saveCue(); }, 900);
    return () => clearTimeout(timer);
  }, [draft, selected, busy]);

  function pointerDown(event: PointerEvent<HTMLDivElement>) {
    if (!regionEditing || busy) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = clamp((event.clientX - bounds.left) / bounds.width, 0, 1), y = clamp((event.clientY - bounds.top) / bounds.height, 0, 1);
    const kind = (event.target as HTMLElement).dataset.gesture || 'new';
    gesture.current = { kind, x, y, roi: [...roi] };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }
  function pointerMove(event: PointerEvent<HTMLDivElement>) {
    const g = gesture.current; if (!g) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = clamp((event.clientX - bounds.left) / bounds.width, 0, 1), y = clamp((event.clientY - bounds.top) / bounds.height, 0, 1);
    const dx = x - g.x, dy = y - g.y;
    let value: ROI;
    if (g.kind === 'move') value = [clamp(g.roi[0] + dx, 0, 1 - g.roi[2]), clamp(g.roi[1] + dy, 0, 1 - g.roi[3]), g.roi[2], g.roi[3]];
    else if (g.kind === 'resize') value = [g.roi[0], g.roi[1], clamp(g.roi[2] + dx, .02, 1 - g.roi[0]), clamp(g.roi[3] + dy, .02, 1 - g.roi[1])];
    else value = [Math.min(x, g.x), Math.min(y, g.y), Math.max(.02, Math.abs(dx)), Math.max(.02, Math.abs(dy))];
    setRoi(value); roiRef.current = value;
  }

  return <div className="studio" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); const file = event.dataTransfer.files[0]; if (file) void importVideo(api.getFilePath(file)); }}>
    <header className="topbar"><div className="brand"><span className="brand-mark">译</span><div><strong>字幕工作室</strong><span>SUBTITLE STUDIO</span></div></div>
      <div className="project-name">{project ? filename(project.meta.path) : '把外文画面，变成中文观看体验'}</div>
      <div className="header-actions"><button disabled={busy} onClick={openProject}>打开项目</button><button disabled={busy} onClick={openSettings}>翻译设置</button><button className="primary" disabled={busy} onClick={() => importVideo()}>＋ 导入视频</button></div>
    </header>
    {!project ? <main className="welcome"><div className="eyebrow">从视频画面开始</div><h1>外文字幕，<br/><em>中文呈现。</em></h1><p>导入已有外文硬字幕的视频。识别、校对、预览，<br/>保存一份带中文字幕的新视频。</p><button className="primary large" onClick={() => importVideo()}>选择视频文件</button><span className="drop-hint">也可以拖入 MP4、MOV 或 MKV 文件</span><div className="welcome-flow"><span>01 画面识别</span><span>02 翻译校对</span><span>03 中文字幕视频</span></div><div className="privacy-note">视频在本地处理 · 首版不安装独立模型 · 翻译支持 API 和本地服务</div></main> : <>
      <div className="info-strip"><span className="dot"/>项目自动保存<span title={project.meta.path}>{project.meta.width} × {project.meta.height}{project.meta.rotation ? ` · 旋转 ${project.meta.rotation}°` : ""}</span><span>{clock(project.meta.duration)}</span><span>{ocrInfo?.engine || '本地 OCR'}</span>{project.missing_video && <button disabled={busy} onClick={relocateVideo}>重新定位原视频</button>}<button onClick={() => api.reveal(`${project.directory}/project.sqlite`)}>查看项目目录 ↗</button></div>
      {project.translation.provider === 'mock' && <div className="mock-banner"><strong>模拟翻译模式</strong><span>不调用模型；译文仅用于验证处理流程，不能代表真实翻译质量。</span><button disabled={busy} onClick={openSettings}>连接模型服务 →</button></div>}
      <main className="workspace">
        <section className="viewer-panel"><div className="panel-title"><div><span className="eyebrow">PREVIEW</span><h2>{previewUrl ? '真实渲染效果' : '视频与字幕区域'}</h2></div><button disabled={busy} onClick={() => { setPreviewUrl(''); setRegionEditing(!regionEditing); }}>{regionEditing ? '退出框选' : isDynamic ? '框选对象 / 排除区域' : '框选字幕区域'}</button></div>
          <div className={`video-stage ${regionEditing ? 'selecting' : ''}`} style={{ aspectRatio: `${project.meta.width}/${project.meta.height}` }} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={() => { gesture.current = null; }} onPointerCancel={() => { gesture.current = null; }}>
            <video ref={video} src={previewUrl || sourceUrl} poster={poster} controls={!regionEditing} preload="metadata" onError={() => { if (!sourceUrl && !previewUrl) return; if (!previewUrl && !proxyAttempted.current && !busy) { proxyAttempted.current = true; void runJob('proxy'); } else setError('当前视频无法播放，请检查文件或重新生成预览。'); }} onLoadedMetadata={() => { if (pendingSeek.current !== null && video.current) { video.current.currentTime = pendingSeek.current; pendingSeek.current = null; } }} onTimeUpdate={() => { const current = video.current?.currentTime || 0; setTime(current + (previewUrl ? previewStart : 0)); if (loop && selectedCue && !previewUrl && current >= selectedCue.end && video.current) video.current.currentTime = selectedCue.start; }}/>
            {regionEditing && <div className="roi-mask" data-gesture="move" style={{ left: `${roi[0] * 100}%`, top: `${roi[1] * 100}%`, width: `${roi[2] * 100}%`, height: `${roi[3] * 100}%` }}><span data-gesture="move">字幕识别区域</span><i data-gesture="resize" aria-label="调整区域大小"/></div>}
            {!isDynamic && !regionEditing && !previewUrl && <>
              {project.style.mode === 'cover' && coverCue?.translation && <div className="caption-cover" style={{left:`${displayRoi[0]*100}%`,top:`${displayRoi[1]*100}%`,width:`${displayRoi[2]*100}%`,height:`${displayRoi[3]*100}%`,background:project.style.background}}/>}
              {activeCue?.translation && <div className="live-caption above" style={{left:`${displayRoi[0]*100}%`,top:`${(project.style.mode === 'above' ? Math.max(.02,displayRoi[1]-.15) : displayRoi[1])*100}%`,width:`${displayRoi[2]*100}%`,height:`${displayRoi[3]*100}%`,color:project.style.color,fontSize:`${project.style.fontSize/project.meta.width*100}cqw`}}>{activeCue.translation}</div>}
            </>}
            {isDynamic && !regionEditing && !previewUrl && !busy && visibleObjects.map((cue,index) => {
              const box=captionBox(cue,project,cue.annotation_box || cue.box);const objectBox=cue.box;const displaying=cue.start<=time && time<cue.end;
              return <div key={cue.id}>
                {cue.dynamic_verified && !cue.ignored && cue.translation && cue.render_mode !== 'outline' && project.style.mode === 'cover' && <div className="caption-cover" style={{left:`${box[0]*100}%`,top:`${box[1]*100}%`,width:`${box[2]*100}%`,height:`${box[3]*100}%`,background:project.style.background}}/>}
                {cue.dynamic_verified && !cue.ignored && cue.translation && displaying && <div className="live-caption dynamic-caption above" style={{left:`${box[0]*100}%`,top:`${(project.style.mode !== 'above' ? box[1] : Math.max(0,box[1]-.06))*100}%`,width:`${box[2]*100}%`,height:`${box[3]*100}%`,color:project.style.color,fontSize:`${(cue.annotation_font_size || project.style.fontSize)/project.meta.width*100}cqw`}}>{cue.translation}</div>}
                {showObjects && <div className={`object-box ${cue.id===selected ? 'selected-object' : ''} ${!cue.dynamic_verified || cue.ignored ? 'unconfirmed-object' : ''}`} style={{left:`${objectBox[0]*100}%`,top:`${objectBox[1]*100}%`,width:`${objectBox[2]*100}%`,height:`${objectBox[3]*100}%`}}><button aria-label={`选择字幕对象 ${cue.id.slice(0,6)}`} onClick={() => chooseCue(cue)}>{cue.id.slice(0,6)}{cue.ignored?' · 忽略':!cue.dynamic_verified?' · 待确认':''}</button></div>}
              </div>;
            })}
          </div>
          <div className="viewer-caption"><span>{previewUrl ? `效果预览 · 原片 ${clock(previewStart)} 起` : `原片 · ${clock(time)} / ${clock(project.meta.duration)}`}</span>{previewUrl ? <button onClick={() => setPreviewUrl('')}>返回原片</button> : <label className="inline"><input type="checkbox" checked={loop} onChange={event => setLoop(event.target.checked)}/>循环当前字幕</label>}</div>
          <div className="recognition-controls"><label>字幕识别模式<select aria-label="字幕识别模式" disabled={busy} value={project.recognition_mode || 'standard'} onChange={event => changeRecognitionMode(event.target.value as Project['recognition_mode'])}><option value="standard">标准模式 · 整句字幕</option><option value="progressive">扩展模式 · 逐步出现字幕</option><option value="progressive_hq">扩展模式 · 渐进字幕高质量</option><option value="dynamic">新模式 · 全画面字幕（任意位置 / 多对象）</option></select></label><p>{isDynamic ? '持续发现任意位置的文字；每个对象在自身出现、增长和消失期间独立处理。无需正文固定区域。' : project.recognition_mode !== 'standard' ? '合并逐字、逐词增长过程，恢复完整句。适用于固定区域；请核对完整文本证据。' : '使用原标准识别逻辑。各模式的结果独立保存。'}</p>{project.recognition_mode !== 'standard' && <label>中文显示时机<select aria-label="中文显示时机" disabled={busy} value={project.progressive?.display || 'first'} onChange={event => update({ progressive: { display: event.target.value } })}><option value="first">从原文首次出现时显示整句</option><option value="complete">等完整原文出现后显示整句</option></select><small>{isDynamic ? '仅已确认事件在可见区间内显示或覆盖；消失后恢复原画面。' : '原文遮盖始终从首次出现开始；人工修改的时间保持原值。'}</small></label>}</div>
          {project.recognition_mode === 'progressive_hq' && <div className="quality-controls"><label>正文布局<select aria-label="高质量正文布局" disabled={busy} value={project.quality?.layout || 'auto'} onChange={e => update({quality:{layout:e.target.value,exclusions:project.quality?.exclusions || []}})}><option value="auto">自动正文 · 分离名字与选项</option><option value="dialogue">游戏对话 · 识别框下半部正文</option><option value="all">完整区域 · 保留所有文字行</option></select></label><p>自动布局按位置关系分离正文，并适应字幕移到识别框上部。严格下半部预设适合固定对话框；混排不清时请框选或排除。</p><button disabled={busy || !regionEditing} onClick={() => update({quality:{layout:project.quality?.layout || 'auto',exclusions:[...(project.quality?.exclusions || []),roi]}})}>将当前框加入排除区域</button><button disabled={busy || !project.quality?.exclusions.length} onClick={() => update({quality:{layout:project.quality?.layout || 'auto',exclusions:[]}})}>清空排除区域（{project.quality?.exclusions.length || 0}）</button><p>排除区域独立保存；框选后加入排除，再恢复正文识别框。</p></div>}
          {isDynamic && <div className="dynamic-controls">
            <label>全画面识别质量<select aria-label="全画面识别质量" disabled={busy} value={project.dynamic?.profile || 'legacy'} onChange={e=>update({dynamic:{...project.dynamic,exclusions:project.dynamic?.exclusions||[],profile:e.target.value}})}><option value="legacy">兼容识别</option><option value="enhanced">增强识别 · 长句与短时漏显复核</option></select></label>
            <p>增强识别同时复核全画面和已发现的字幕对象，速度较慢；短暂失联只有在文字和画面证据一致时才补回。字幕搜索范围与画面遮盖范围独立。</p>
            <button disabled={busy||!regionEditing||project.dynamic?.profile!=='enhanced'} onClick={async()=>{await update({dynamic:{...project.dynamic,exclusions:project.dynamic?.exclusions||[],review_regions:[...(project.dynamic?.review_regions||[]),roi]}});setRegionEditing(false);}}>将当前框加入独立复核区域</button>
            <button disabled={busy||!project.dynamic?.review_regions?.length} onClick={()=>update({dynamic:{...project.dynamic,exclusions:project.dynamic?.exclusions||[],review_regions:[]}})}>清空复核区域（{project.dynamic?.review_regions?.length||0}）</button>
            <p>复核区域补充全画面发现，适合经常有对白但受特效干扰的区域；区域空白时不产生字幕。没有常见区域的视频可不设置。水印和界面文字可忽略。</p>
            <button disabled={busy||!project.cues.length} onClick={()=>runJob('audit',{start:0,end:project.meta.duration})}>独立检查原片字幕覆盖</button>
            {project.scan.gap_recovery_report && <p>短时漏显逐帧复核：检查 {project.scan.gap_recovery_report.checked} 处，恢复 {project.scan.gap_recovery_report.restored} 处。{project.scan.gap_recovery_report.method}</p>}
            {project.scan.coverage_report && <details><summary>原文覆盖复核 · {project.scan.coverage_report.suspected_gaps.length} 处疑似缺口</summary><p>{project.scan.coverage_report.method} · {project.scan.coverage_report.samples} 个检查点</p>{project.scan.coverage_report.suspected_gaps.slice(0,100).map((gap,index)=><div key={index}><button onClick={()=>{if(previewUrl){pendingSeek.current=gap.time;setPreviewUrl('');}else if(video.current)video.current.currentTime=gap.time;setTime(gap.time);}}>{clock(gap.time)}</button><span>{gap.source}</span></div>)}</details>}
            <label className="inline"><input type="checkbox" checked={showObjects} onChange={e=>setShowObjects(e.target.checked)}/>显示事件框与编号</label>
            <p>已确认 {project.cues.filter(c=>c.dynamic_verified&&!c.ignored).length} · 待确认 {project.cues.filter(c=>!c.dynamic_verified&&!c.ignored).length} · 忽略 {project.cues.filter(c=>c.ignored).length}{busy && task.objects ? ` · 当前发现 ${task.objects.length} 个对象` : ''}</p>
            <button disabled={busy||!regionEditing} onClick={async()=>{await update({dynamic:{...project.dynamic,exclusions:[...(project.dynamic?.exclusions||[]),roi]}});setRegionEditing(false);}}>将当前框加入全片排除</button>
            <button disabled={busy||!project.dynamic?.exclusions.length} onClick={()=>update({dynamic:{...project.dynamic,exclusions:[]}})}>清空全片排除（{project.dynamic?.exclusions.length||0}）</button>
            <p>全片排除只适用于明确不翻译的区域；临时文字建议使用“忽略此事件”。位置预览为示意，准确排版请生成效果预览。SRT 保存文字与时间，不保存原位置。</p>
          </div>}
          <div className="region-controls"><label>字幕语言<select disabled={busy} value={project.language} onChange={event => update({ language: event.target.value })}>{languages.filter(language => !ocrInfo || ocrInfo.languages.includes(language.value)).map(language => <option key={language.value} value={language.value}>{language.name}</option>)}</select></label>{!isDynamic && <><button disabled={busy} onClick={() => runJob('recommend')}>自动推荐区域</button><button disabled={busy} onClick={saveRegion}>保存区域</button></>}</div>
          {regionEditing && <div className="roi-fields">{['左边距', '上边距', '宽度', '高度'].map((name, index) => <label key={name}>{name} %<input aria-label={name} type="number" min="0" max="100" step=".1" value={+(roi[index] * 100).toFixed(1)} onChange={event => { const next: ROI = [...roi]; next[index] = +event.target.value / 100; setRoi(next); }}/></label>)}</div>}
          <div className="sample-controls"><span className="small-label">片段试处理</span><label>开始（秒）<input type="number" min="0" max={project.meta.duration} step=".1" value={sampleStart} onChange={event => setSampleStart(+event.target.value)}/></label><label>结束（秒）<input type="number" min="0" max={project.meta.duration} step=".1" value={sampleEnd} onChange={event => setSampleEnd(+event.target.value)}/></label><button disabled={busy} onClick={() => scanVideo(true)}>识别片段</button></div>
          {!isDynamic && <details className="segment-controls"><summary>字幕位置变化时，设置分段区域</summary><div><span>{clock(sampleStart)} — {clock(sampleEnd)} 使用当前框选区域</span><button disabled={busy} onClick={() => update({ regions: [...project.regions, { start: sampleStart, end: sampleEnd, roi }] })}>添加分段区域</button></div>{project.regions.map((region, index) => <div key={index}><span>{clock(region.start)} — {clock(region.end)} · 区域 {index + 1}</span><button disabled={busy} onClick={() => update({ regions: project.regions.filter((_, i) => i !== index) })}>删除</button></div>)}</details>}
          <div className="style-controls"><span className="small-label">中文显示</span><select aria-label="中文显示方式" disabled={busy} value={project.style.mode} onChange={event => update({ style: { ...project.style, mode: event.target.value } })}><option value="cover">背景覆盖外文</option><option value="delogo">局部去字 · 无背景条（实验）</option><option value="above">保留外文，中文在上方</option></select>{project.style.mode === 'cover' && <label>覆盖范围<select aria-label="覆盖范围" disabled={busy} value={project.style.coverArea || 'region'} onChange={event => update({style:{...project.style,coverArea:event.target.value}})}><option value="text">贴合原字幕</option><option value="region">完整识别区域（原方式）</option></select></label>}<label>字号<input aria-label="字号" disabled={busy} type="number" min="12" max="100" value={project.style.fontSize} onChange={event => update({ style: { ...project.style, fontSize: +event.target.value } })}/></label><label>边距<input aria-label="遮盖边距" disabled={busy} type="number" min="0" max="50" value={project.style.padding} onChange={event => update({ style: { ...project.style, padding: +event.target.value } })}/></label><label>文字<input aria-label="字幕颜色" disabled={busy} type="color" value={project.style.color} onChange={event => update({ style: { ...project.style, color: event.target.value } })}/></label><label>背景<input aria-label="背景颜色" disabled={busy || project.style.mode !== 'cover'} type="color" value={project.style.background} onChange={event => update({ style: { ...project.style, background: event.target.value } })}/></label><button disabled={busy || !project.cues.length} onClick={preview}>生成效果预览</button></div>
          <p className="appearance-note">{project.style.mode === 'delogo' ? '局部去字用每帧周围像素填补文字区域；复杂纹理可能模糊或闪烁。此处仅示意文字位置，点击“生成效果预览”查看实际去字结果。' : '贴合原字幕依据文字边界覆盖，并保留少量边距遮住描边；不会为容纳中文扩大背景。新项目默认贴合，旧项目可自行切换。播放器中文为位置示意，准确排版请生成效果预览。'}</p>
          {!isDynamic && project.style.coverArea === 'text' && project.cues.some(cue => !cue.source_box && !cue.body_box) && <p className="appearance-note">部分旧字幕未保存文字边界，暂按原识别区域覆盖；重新识别未校对的片段可获得精确范围。</p>}
          <details className="segment-controls"><summary>字幕检查阈值</summary><div>{([{key: 'maxCps', label: '每秒字数', value:12, max:50}, {key:'maxChars', label:'字幕总字数', value:44, max:200}, {key:'maxLines', label:'最多行数', value:2, max:4}] as const).map(item => <label key={item.key}>{item.label}<input aria-label={item.label} type="number" min="1" max={item.max} disabled={busy} value={project.style[item.key] ?? item.value} onChange={event => update({style:{...project.style,[item.key]:+event.target.value}})}/></label>)}</div></details>
          {project.cues.length > 0 && <div className="timeline"><div className="timeline-label"><span>字幕时间轴</span><span>{clock(project.meta.duration)}</span></div><div className="timeline-track">{project.cues.map(cue => <button key={cue.id} aria-label={`跳转字幕 ${clock(cue.start)}`} className={cue.id === selected ? 'active' : ''} style={{ left: `${cue.start / project.meta.duration * 100}%`, width: `${(cue.end - cue.start) / project.meta.duration * 100}%` }} onClick={() => chooseCue(cue)} title={cue.source}/>)}<i style={{ left: `${time / project.meta.duration * 100}%` }}/></div></div>}
          {selectedCue && <div className="evidence"><div className="small-label">原字幕证据 · OCR 平均置信度 {Math.round(selectedCue.confidence * 100)}%（不等于正确率）</div>{screenshot && <img src={screenshot} alt="当前字幕区域的原始画面截图"/>}</div>}
        </section>
        <section className="editor-panel"><div className="panel-title"><div><span className="eyebrow">SUBTITLES</span><h2>原文与中文 <span className="count">{project.cues.length}</span></h2></div><button disabled={busy || !project.cues.length} onClick={() => operation(async () => receiveProject(await api.request('check')))}>检查问题</button></div>
          <div className="editor-toolbar"><input aria-label="搜索字幕" placeholder="搜索原文或译文…" value={search} onChange={event => setSearch(event.target.value)}/><label className="inline"><input type="checkbox" checked={onlyIssues} onChange={event => setOnlyIssues(event.target.checked)}/>只看待检查</label></div>
          <div className="subtitle-list">{shown.length ? shown.map((cue, index) => <button className={`subtitle-row ${cue.id === selected ? 'selected' : ''}`} key={cue.id} onClick={() => chooseCue(cue)}><div className="row-meta"><span>{String(index + 1).padStart(2, '0')}{isDynamic ? ` · 对象 ${cue.id.slice(0,6)}` : ''} · {clock(cue.start)} — {clock(cue.end)}</span><span className={cue.translation_status === 'mock' ? 'mock-tag' : cue.manual_translation ? 'manual-tag' : ''}>{cue.translation_status === 'mock' ? '模拟' : cue.manual_translation ? '人工校对' : `${Math.round(cue.confidence * 100)}%`}</span></div><div className="source-text">{cue.source}</div><div className={`translation-text ${!cue.translation ? 'muted' : ''}`}>{cue.translation || '等待翻译'}</div>{cue.issues.length > 0 && <div className="issue-text">{cue.issues.join(' · ')}</div>}</button>) : <div className="empty-list"><span className="empty-symbol">Aa</span><strong>{project.cues.length ? '没有匹配的字幕' : '字幕将出现在这里'}</strong><p>{project.cues.length ? '调整搜索词或检查筛选条件。' : isDynamic ? '无需固定正文区域。先试处理一个片段，全画面发现独立字幕事件。' : '确认左侧区域后，先试处理一个片段，或直接识别全片。'}</p></div>}</div>
          {selectedCue && <div className="cue-editor"><div className="edit-title"><strong>校对当前字幕</strong><div><button disabled={busy} onClick={() => operation(async () => receiveProject(await api.request('undo')))}>撤销编辑</button><button className="primary" disabled={busy} onClick={saveCue}>保存修改</button></div></div><div className="time-fields"><label>开始（秒）<input aria-label="字幕开始时间" disabled={busy} type="number" step=".01" value={draft.start} onChange={event => changeDraft({ ...draft, start: +event.target.value })}/></label><label>结束（秒）<input aria-label="字幕结束时间" disabled={busy} type="number" step=".01" value={draft.end} onChange={event => changeDraft({ ...draft, end: +event.target.value })}/></label></div><label>识别原文<textarea aria-label="识别原文" disabled={busy} value={draft.source} onChange={event => changeDraft({ ...draft, source: event.target.value })}/></label><label>中文译文<textarea aria-label="中文译文" disabled={busy} value={draft.translation} onChange={event => changeDraft({ ...draft, translation: event.target.value })}/></label><div className="local-actions"><button disabled={busy} onClick={() => runJob('translate', { ids: [selected], force: true })}>重译这一条</button><button disabled={busy} onClick={() => runJob('scan', { start: selectedCue.first_seen ?? selectedCue.start, end: selectedCue.disappeared_at ?? selectedCue.end, force: true })}>重新识别片段</button>{!isDynamic && <button disabled={busy} onClick={() => operation(async () => receiveProject(await api.request('merge', { id: selected })))}>合并下一条</button>}<button disabled={busy} onClick={() => operation(async () => receiveProject(await api.request('split', { id: selected, time: selectedCue.start < time && time < selectedCue.end ? time : (selectedCue.start + selectedCue.end) / 2 })))}>拆分字幕</button></div></div>}
          {isDynamic && selectedCue && <div className="dynamic-controls">
            <strong>对象 {selectedCue.id.slice(0,6)} · 局部范围与生命周期</strong>
            {selectedCue.render_issue && <p>{selectedCue.render_issue}</p>}
            <p>文字确认：{selectedCue.dynamic_verified?'已确认':'证据不足，默认保留原画面'} · 事件{selectedCue.ignored?'已忽略':'有效'}</p>
            <button disabled={busy} onClick={()=>{setRoi(selectedCue.box);roiRef.current=selectedCue.box;setRegionEditing(true);setPreviewUrl('');}}>框选调整该对象范围</button>
            <button disabled={busy||!regionEditing} onClick={()=>editEvent({box:roi})}>将当前框应用到该事件</button>
            <button disabled={busy||selectedCue.dynamic_verified||selectedCue.ignored} onClick={()=>editEvent({dynamic_verified:true})}>校对后确认事件</button>
            <button disabled={busy} onClick={()=>editEvent({ignored:!selectedCue.ignored})}>{selectedCue.ignored?'恢复此事件':'忽略此事件'}</button>
            <label>明确选择要合并的另一个对象<select aria-label="合并对象" disabled={busy} value={mergeId} onChange={e=>setMergeId(e.target.value)}><option value="">请选择对象</option>{project.cues.filter(c=>c.id!==selectedCue.id).map(c=><option key={c.id} value={c.id}>{c.id.slice(0,6)} · {clock(c.start)} · {c.source.slice(0,24)}</option>)}</select></label><button disabled={busy||!mergeId} onClick={mergeObjects}>合并指定对象</button>
            <label>误合并区域划分<select aria-label="区域划分方向" disabled={busy} value={splitAxis} onChange={e=>setSplitAxis(e.target.value)}><option value="x">左右两个对象</option><option value="y">上下两个对象</option></select></label><label>分界位置 %<input aria-label="对象分界位置" disabled={busy} type="number" min="10" max="90" value={splitFraction} onChange={e=>setSplitFraction(+e.target.value)}/></label><button disabled={busy} onClick={()=>runJob('split_object',{id:selectedCue.id,axis:splitAxis,fraction:splitFraction/100})}>划分区域并复读</button><p>划分只复读一帧，请分别核对原文和时间，再确认新事件。重新识别时间段会扫描同一时段的全画面；人工事件受保护。</p>
          </div>}
          {selectedCue?.recognition_mode === 'progressive_hq' && <div className="visual-review"><p>图像复核默认关闭。点击将最多 3 张字幕区域截图发送至当前 API；返回建议，保留原识别和人工编辑。</p><button disabled={busy || project.translation.provider !== 'api'} onClick={() => runJob('review',{id:selectedCue.id})}>上传字幕截图并复核这一条</button>{selectedCue.visual_review && <><p>{selectedCue.visual_review.status === 'readable' ? '模型建议原文（尚未采用）' : '图像仍无法完整辨认'} · {selectedCue.visual_review.reason}</p><pre>{selectedCue.visual_review.text}</pre>{selectedCue.visual_review.status === 'readable' && <button disabled={busy} onClick={async () => {if (draftDirty.current && !await saveCue()) return;await operation(async () => receiveProject(await api.request<Project>('edit',{id:selectedCue.id,changes:{source:selectedCue.visual_review!.text}})));}}>采用并替换原文（译文需校对）</button>}</>}</div>}
          {selectedCue && ['progressive','progressive_hq','dynamic'].includes(selectedCue.recognition_mode || '') && <details className="growth-evidence"><summary>逐步出现证据 · {selectedCue.growth?.length || 0} 个文字阶段</summary><p>首次出现 {clock(selectedCue.first_seen ?? selectedCue.start)} · 完整候选 {selectedCue.complete_time == null ? '证据不足' : clock(selectedCue.complete_time)} · 消失 {clock(selectedCue.disappeared_at ?? selectedCue.end)}</p>{selectedCue.growth?.map((item, index) => <div key={index}><span>{clock(item.first)} · {item.count} 次 OCR</span><pre>{item.text}</pre></div>)}</details>}
          {project.cues.length > 0 && <details className="replace-controls"><summary>统一替换译文术语</summary><div><input aria-label="查找术语" placeholder="查找内容" value={replaceFrom} onChange={event => setReplaceFrom(event.target.value)}/><input aria-label="替换术语" placeholder="替换为" value={replaceTo} onChange={event => setReplaceTo(event.target.value)}/><button disabled={busy || !replaceFrom} onClick={replaceTerms}>替换译文</button></div></details>}
        </section>
      </main>
      <div className="actionbar"><div className="progress-info"><span className={`status-dot ${busy ? 'busy' : ''}`}/><div><strong>{busy ? task.message || '正在处理' : message || '准备就绪'}</strong><span>{busy && task.total ? `${task.stage === 'translate' ? `${task.count || 0} / ${task.total} 条` : `${clock(task.time || 0)} / ${clock(task.total)}`}` : '原视频保留 · 编辑与处理结果自动保存'}</span></div>{busy && <progress max="100" value={percentage}/>}</div><div className="main-actions">{busy ? <button className="danger" onClick={() => operation(async () => { await api.request('cancel'); setMessage('正在取消，请等待当前处理结束…'); })}>取消任务</button> : <><button onClick={() => scanVideo()}>识别全片 / 继续</button><button disabled={!project.cues.length} onClick={() => runJob('translate')}>翻译字幕</button><button disabled={!project.cues.length} onClick={() => exportFile('srt')}>导出 SRT</button><button className="primary" disabled={!project.cues.length} onClick={() => exportFile('mp4')}>导出中文视频 ↗</button></>}</div></div>
    </>}
    {error && <div className="error-toast" role="alert"><span>{error}</span><button aria-label="关闭错误提示" onClick={() => setError('')}>×</button></div>}
    {settingsOpen && <div className="modal-backdrop"><section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title"><div className="panel-title"><div><span className="eyebrow">TRANSLATION</span><h2 id="settings-title">翻译服务</h2></div><button aria-label="关闭设置" onClick={() => { setSettingsOpen(false); setKey(''); }}>×</button></div><label>服务类型<select aria-label="服务类型" value={config.provider} onChange={event => { const provider = event.target.value as TranslationConfig['provider']; setConfig({ ...config, provider, baseUrl: provider === 'api' ? 'https://api.openai.com/v1' : 'http://localhost:11434' }); }}><option value="mock">模拟模式 · 不调用模型</option><option value="api">兼容 OpenAI 的 API / 本地兼容接口</option><option value="ollama">本地 Ollama 服务</option></select></label>{config.provider === 'mock' ? <p className="settings-note">模拟模式仅验证字幕处理与导出流程，不提供真实翻译质量。</p> : <><label>服务地址<input aria-label="服务地址" value={config.baseUrl} onChange={event => setConfig({ ...config, baseUrl: event.target.value })}/></label><label>模型名称<input aria-label="模型名称" placeholder="填写已可用的模型名称" value={config.model} onChange={event => setConfig({ ...config, model: event.target.value })}/></label>{config.provider === 'api' && <label>API 密钥<input aria-label="API 密钥" type="password" autoComplete="off" placeholder={settingsInfo?.hasKey ? '已配置；留空保留现有密钥' : '输入密钥，或使用 SUBTITLE_API_KEY 环境变量'} value={key} onChange={event => setKey(event.target.value)}/></label>}<p className="settings-note">{config.provider === 'ollama' ? '连接本机已运行的服务，本应用不会下载模型。' : '仅发送字幕文字及上下文。密钥在主进程中使用，不写入项目。'}{settingsInfo && !settingsInfo.secureStorage && '系统安全存储不可用，密钥只在本次运行中保留。'}</p></>}<label>术语表<textarea aria-label="术语表" placeholder="每行一个约定，例如：Subtitle Studio = 字幕工作室" value={config.glossary} onChange={event => setConfig({ ...config, glossary: event.target.value })}/></label><div className="settings-footer"><button onClick={() => setSettingsOpen(false)}>取消</button><button className="primary" onClick={saveSettings}>保存设置</button></div></section></div>}
  </div>;
}
