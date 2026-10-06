export type ROI = [number, number, number, number];
export type TranslationConfig = { provider: 'mock' | 'api' | 'ollama'; baseUrl: string; model: string; glossary: string };
export type Cue = { id: string; start: number; end: number; source: string; translation: string; confidence: number; screenshot: string; issues: string[]; translation_status: string; manual_translation?: boolean; cover_intervals?: [number,number][]; recognition_mode?: string; first_seen?: number; complete_time?: number | null; disappeared_at?: number; complete_supported?: boolean; growth?: {text: string; first: number; last: number; count: number; confidence: number}[]; quality_support?: number; quality_methods?: string[]; recognition_issue?: string; evidence_frames?: {text: string; path: string; time: number}[]; visual_review?: {status: string; text?: string; reason?: string; error?: string}; box: ROI; source_box?: ROI | null; body_box?: ROI | null; original_start?: number; original_end?: number; object_id?: string; dynamic_verified?: boolean; ignored?: boolean; visible_intervals?: [number,number][] };
export type Task = { stage: string; status: string; time?: number; total?: number; count?: number; message?: string; error?: string; objects?: {id:string;box:ROI}[] };
export type Project = { id: string; directory: string; recognition_mode: "standard" | "progressive" | "progressive_hq" | "dynamic"; dynamic?: {exclusions: ROI[]}; quality?: {layout: "auto" | "dialogue" | "all"; exclusions: ROI[]}; progressive: {display: "first" | "complete"}; recognition_results?: Record<string, {cues: Cue[]; scan: unknown}>; preview_path?: string; missing_video?: boolean; meta: { path: string; width: number; height: number; duration: number; fps: number; rotation?: number }; roi: ROI; regions: { start: number; end: number; roi: ROI }[]; language: string; cues: Cue[]; task: Task; scan: { status?: string; cursor?: number }; style: { mode: 'cover' | 'above' | 'delogo'; coverArea?: 'text' | 'region'; fontSize: number; padding: number; maxCps?: number; maxChars?: number; maxLines?: number; color: string; background: string }; translation: TranslationConfig; outputs: string[] };
export type WorkerEvent = { event: 'progress' | 'job' | 'fatal'; stage: string; status: string; message?: string; error?: string; time?: number; count?: number; total?: number; project?: Project; result?: { path?: string; roi?: ROI; found?: boolean; message?: string } };
export type Settings = { config: TranslationConfig; hasKey: boolean; secureStorage: boolean };
declare global {
  interface Window { studio: {
    request<T = Project>(method: string, params?: Record<string, unknown>): Promise<T>;
    chooseVideo(): Promise<string | null>; chooseProject(): Promise<string | null>; newDirectory(): Promise<string>;
    chooseOutput(extension: string, directory: string): Promise<string | null>;
    mediaUrl(filename: string): Promise<string>; settings(): Promise<Settings>; configure(config: TranslationConfig, key?: string): Promise<Settings>;
    getFilePath(file: File): string; reveal(filename: string): Promise<void>; subscribe(callback: (value: WorkerEvent) => void): () => void;
  } }
}
