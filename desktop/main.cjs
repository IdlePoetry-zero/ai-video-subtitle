const { app, BrowserWindow, ipcMain, dialog, protocol, safeStorage, shell } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const crypto = require('node:crypto');
const { Readable } = require('node:stream');

// The extension app can coexist with the preserved standard application.
const windowsApp = process.platform === 'win32';
app.setName(windowsApp ? 'SubtitleStudioWindows' : 'SubtitleStudioProgressive');
const qualityApp = process.execPath.includes('SubtitleStudioQuality.app') || process.env.STUDIO_QUALITY_APP === '1';
const dynamicApp = process.execPath.includes('SubtitleStudioDynamic.app') || process.env.STUDIO_DYNAMIC_APP === '1';
const appearanceApp = process.execPath.includes('SubtitleStudioAppearance.app') || process.env.STUDIO_APPEARANCE_APP === '1';
const recognitionApp = process.execPath.includes('SubtitleStudioRecognition.app') || process.env.STUDIO_RECOGNITION_APP === '1';
const isolatedApp = windowsApp || qualityApp || dynamicApp || appearanceApp || recognitionApp;
app.setPath('userData', process.env.STUDIO_TEST_MODE === '1' && process.env.STUDIO_TEST_USER_DATA || path.join(app.getPath('appData'), windowsApp ? 'SubtitleStudioWindows' : recognitionApp ? 'SubtitleStudioRecognition' : appearanceApp ? 'SubtitleStudioAppearance' : dynamicApp ? 'SubtitleStudioDynamic' : qualityApp ? 'SubtitleStudioQuality' : 'SubtitleStudioProgressive'));

protocol.registerSchemesAsPrivileged([{ scheme: 'studio-media', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } }]);
const root = path.resolve(__dirname, '..');
const methods = new Set(['create', 'open', 'snapshot', 'dependencies', 'update', 'edit', 'undo', 'check', 'frame', 'srt', 'merge', 'split', 'split_object', 'cancel', 'scan', 'audit', 'translate', 'review', 'export', 'preview', 'recommend', 'proxy', 'relocate']);
const pending = new Map();
const assets = new Map();
const directories = new Set();
const files = new Set();
let worker, window, count = 0, shutdown = false;
let smokeDependencies;
let settings = { provider: 'mock', baseUrl: 'http://localhost:11434', model: '', glossary: '' };
let apiKey = process.env.SUBTITLE_API_KEY || process.env.OPENAI_API_KEY || '';
const runtimeDirectory = isolatedApp ? path.join(app.getPath('userData'), 'runtime') : path.join(root, 'runtime');
const settingsFile = isolatedApp ? path.join(app.getPath('userData'), 'settings.json') : path.join(root, 'runtime', 'settings.json');
const projectDirectory = isolatedApp ? path.join(app.getPath('userData'), 'projects') : path.join(root, 'projects');

function registerProject(project) {
  if (project?.directory) directories.add(path.resolve(project.directory));
  if (project?.meta?.path) files.add(path.resolve(project.meta.path));
}
function allowed(filename) {
  const full = path.resolve(filename);
  if (files.has(full)) return true;
  return [...directories].some(directory => full.startsWith(directory + path.sep));
}
function mediaUrl(filename) {
  if (!allowed(filename) || !fs.existsSync(filename)) throw new Error('媒体文件不存在或不属于当前项目。');
  const id = crypto.createHash('sha256').update(filename).digest('hex');
  assets.set(id, filename);
  return 'studio-media://asset/' + id;
}
function rpc(method, params = {}) {
  if (!worker || worker.exitCode !== null) return Promise.reject(new Error('处理组件已退出，请重新启动应用。'));
  const id = ++count;
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error('操作响应超时，请检查处理组件。')); }, 120000);
    pending.set(id, { resolve, reject, timeout });
    worker.stdin.write(JSON.stringify({ id, method, params }) + '\n', error => {
      if (error) { clearTimeout(timeout); pending.delete(id); reject(new Error('无法连接处理组件。')); }
    });
  });
}
function startWorker() {
  const frozenWorker = windowsApp && app.isPackaged && path.join(process.resourcesPath, 'runtime', 'subtitle-worker', 'subtitle-worker.exe');
  const python = frozenWorker || process.env.STUDIO_PYTHON || path.join(root, windowsApp ? '.venv/Scripts/python.exe' : '.venv/bin/python');
  if (!fs.existsSync(python)) throw new Error('缺少 Python 环境，请先运行 npm run setup。');
  worker = spawn(python, frozenWorker ? [] : [path.join(root, 'worker/server.py')], { cwd: frozenWorker ? process.resourcesPath : root,
    env: { ...process.env, PYTHONUTF8: '1', ...(frozenWorker ? { STUDIO_RESOURCE_ROOT: process.resourcesPath } : {}) }, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  const logs = fs.createWriteStream(path.join(runtimeDirectory, 'worker.log'), { flags: 'a' });
  worker.stderr.pipe(logs);
  readline.createInterface({ input: worker.stdout }).on('line', line => {
    let value;
    try { value = JSON.parse(line); } catch { return; }
    if (value.event) {
      if (value.project) registerProject(value.project);
      if (window && !window.isDestroyed()) window.webContents.send('studio:event', value);
    } else {
      const item = pending.get(value.id);
      if (!item) return;
      clearTimeout(item.timeout);
      pending.delete(value.id);
      value.error ? item.reject(new Error(value.error)) : item.resolve(value.result);
    }
  });
  worker.on('exit', () => {
    for (const item of pending.values()) { clearTimeout(item.timeout); item.reject(new Error('处理组件已退出，请重新启动应用。')); }
    pending.clear();
    if (!shutdown && window && !window.isDestroyed()) window.webContents.send('studio:event', { event: 'fatal', error: '处理组件已退出，请重新启动应用。' });
    logs.end();
  });
  worker.on('error', error => { if (window && !window.isDestroyed()) window.webContents.send('studio:event', { event: 'fatal', error: error.message }); });
}
function loadSettings() {
  try {
    let source = isolatedApp && !windowsApp && !fs.existsSync(settingsFile) ? path.join(root, 'runtime', 'settings.json') : settingsFile;
    if (dynamicApp && !fs.existsSync(settingsFile)) {
      const previous = path.join(app.getPath('appData'), 'SubtitleStudioQuality', 'settings.json');
      if (fs.existsSync(previous)) source = previous;
    }
    if (appearanceApp && !fs.existsSync(settingsFile)) {
      for (const name of ['SubtitleStudioDynamic', 'SubtitleStudioQuality']) {
        const previous = path.join(app.getPath('appData'), name, 'settings.json');
        if (fs.existsSync(previous)) { source = previous; break; }
      }
    }
    const stored = JSON.parse(fs.readFileSync(source, 'utf8'));
    settings = { ...settings, ...stored.config };
    if (stored.encryptedKey && safeStorage.isEncryptionAvailable()) apiKey = safeStorage.decryptString(Buffer.from(stored.encryptedKey, 'base64'));
    if (source !== settingsFile) fs.writeFileSync(settingsFile, JSON.stringify(stored), { mode: 0o600 });
  } catch { /* First launch. */ }
}
function assertSender(event) {
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) throw new Error('请求来源无效。');
}

app.whenReady().then(async () => {
  fs.mkdirSync(runtimeDirectory, { recursive: true });
  fs.mkdirSync(path.dirname(settingsFile), { recursive: true });
  loadSettings();
  startWorker();
  protocol.handle('studio-media', request => {
    const id = new URL(request.url).pathname.slice(1);
    const filename = assets.get(id);
    if (!filename || !allowed(filename)) return new Response('Not found', { status: 404 });
    // Explicit byte-range responses are required for reliable MP4 seeking.
    const size = fs.statSync(filename).size;
    let start = 0, end = size - 1, status = 200;
    const range = request.headers.get('range');
    if (range) {
      const match = /^bytes=(\d*)-(\d*)$/.exec(range);
      if (!match) return new Response(null, { status: 416, headers: { 'Content-Range': `bytes */${size}` } });
      if (!match[1]) start = Math.max(0, size - Number(match[2]));
      else { start = Number(match[1]); if (match[2]) end = Math.min(end, Number(match[2])); }
      if (start > end || start >= size) return new Response(null, { status: 416, headers: { 'Content-Range': `bytes */${size}` } });
      status = 206;
    }
    const type = { '.mp4': 'video/mp4', '.mov': 'video/quicktime', '.mkv': 'video/x-matroska', '.webm': 'video/webm', '.avi': 'video/x-msvideo', '.jpg': 'image/jpeg', '.png': 'image/png' }[path.extname(filename).toLowerCase()] || 'application/octet-stream';
    const headers = { 'Content-Type': type, 'Content-Length': String(end - start + 1), 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store' };
    if (status === 206) headers['Content-Range'] = `bytes ${start}-${end}/${size}`;
    return new Response(request.method === 'HEAD' ? null : Readable.toWeb(fs.createReadStream(filename, { start, end })), { status, headers });
  });
  ipcMain.handle('studio:request', async (event, method, params = {}) => {
    assertSender(event);
    if (!methods.has(method)) throw new Error('不支持该操作。');
    if (method === 'translate' || method === 'review') params = { ...params, apiKey };
    if (method === 'create') directories.add(path.resolve(params.directory));
    const result = await rpc(method, params);
    if (method === 'dependencies') smokeDependencies = result;
    registerProject(result);
    if (method === 'create') return rpc('update', { changes: { translation: settings } });
    return result;
  });
  ipcMain.handle('studio:video', async event => {
    assertSender(event);
    if (process.env.STUDIO_TEST_MODE === '1' && process.env.STUDIO_TEST_VIDEO) return process.env.STUDIO_TEST_VIDEO;
    const chosen = await dialog.showOpenDialog(window, { title: '选择含外文硬字幕的视频', properties: ['openFile'], filters: [{ name: '视频', extensions: ['mp4', 'mkv', 'mov', 'avi', 'webm', 'm4v'] }] });
    return chosen.canceled ? null : chosen.filePaths[0];
  });
  ipcMain.handle('studio:project', async event => {
    assertSender(event);
    if (process.env.STUDIO_TEST_MODE === '1' && process.env.STUDIO_TEST_PROJECT) return process.env.STUDIO_TEST_PROJECT;
    const chosen = await dialog.showOpenDialog(window, { title: '选择项目目录', properties: ['openDirectory'] });
    return chosen.canceled ? null : chosen.filePaths[0];
  });
  ipcMain.handle('studio:new-directory', async event => {
    assertSender(event);
    if (process.env.STUDIO_TEST_MODE === '1' && process.env.STUDIO_TEST_PROJECT) {
      directories.add(path.resolve(process.env.STUDIO_TEST_PROJECT));
      return process.env.STUDIO_TEST_PROJECT;
    }
    const directory = path.join(projectDirectory, new Date().toISOString().replace(/[:.]/g, '-') + '-' + crypto.randomBytes(3).toString('hex'));
    directories.add(directory);
    return directory;
  });
  ipcMain.handle('studio:output', async (event, extension, directory) => {
    assertSender(event);
    if (!['mp4', 'srt'].includes(extension) || !directories.has(path.resolve(directory))) throw new Error('输出参数无效。');
    if (process.env.STUDIO_TEST_MODE === '1') return path.join(directory, 'ui-export-' + Date.now() + '.' + extension);
    const chosen = await dialog.showSaveDialog(window, { title: '导出中文字幕', defaultPath: path.join(directory, '中文字幕.' + extension), filters: [{ name: extension.toUpperCase(), extensions: [extension] }] });
    if (!chosen.canceled) files.add(path.resolve(chosen.filePath));
    return chosen.canceled ? null : chosen.filePath;
  });
  ipcMain.handle('studio:media', (event, filename) => { assertSender(event); return mediaUrl(filename); });
  ipcMain.handle('studio:settings', event => { assertSender(event); return { config: settings, hasKey: Boolean(apiKey), secureStorage: safeStorage.isEncryptionAvailable() }; });
  ipcMain.handle('studio:configure', async (event, config, newKey) => {
    assertSender(event);
    if (!['mock', 'api', 'ollama'].includes(config.provider)) throw new Error('服务类型无效。');
    settings = { provider: config.provider, baseUrl: String(config.baseUrl), model: String(config.model), glossary: String(config.glossary) };
    if (typeof newKey === 'string' && newKey) apiKey = newKey;
    if (newKey === '__clear__') apiKey = '';
    const encryptedKey = apiKey && safeStorage.isEncryptionAvailable() ? safeStorage.encryptString(apiKey).toString('base64') : null;
    fs.writeFileSync(settingsFile + '.partial', JSON.stringify({ config: settings, encryptedKey }), { mode: 0o600 });
    fs.renameSync(settingsFile + '.partial', settingsFile);
    return { config: settings, hasKey: Boolean(apiKey), secureStorage: safeStorage.isEncryptionAvailable() };
  });
  ipcMain.handle('studio:file-path', (event, filename) => { assertSender(event); return filename; });
  ipcMain.handle('studio:reveal', (event, filename) => { assertSender(event); if (!allowed(filename)) throw new Error('文件不属于当前项目。'); shell.showItemInFolder(filename); });
  window = new BrowserWindow({ width: 1440, height: 960, minWidth: 1000, minHeight: 700, title: '字幕工作室', backgroundColor: '#101820',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', event => event.preventDefault());
  if (process.env.STUDIO_DEV_URL) await window.loadURL(process.env.STUDIO_DEV_URL);
  else await window.loadFile(path.join(root, 'dist/index.html'));
  if (windowsApp && process.env.STUDIO_TEST_MODE === '1' && process.env.STUDIO_WINDOWS_SMOKE) {
    // CI startup probe exercises the shipped renderer and its normal RPC bootstrap.
    const resultPath = process.env.STUDIO_WINDOWS_SMOKE;
    const deadline = Date.now() + 60000;
    while (!smokeDependencies && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 100));
    if (!smokeDependencies) throw new Error('Windows renderer bootstrap did not reach local OCR.');
    const image = await window.webContents.capturePage();
    fs.mkdirSync(path.dirname(resultPath), { recursive: true });
    fs.writeFileSync(resultPath + '.png', image.toPNG());
    fs.writeFileSync(resultPath, JSON.stringify({ passed: true, packaged: app.isPackaged,
      platform: process.platform, userData: app.getPath('userData'), dependencies: smokeDependencies }, null, 2));
    app.quit();
  }
  window.on('closed', () => { window = null; });
}).catch(error => { dialog.showErrorBox('无法启动字幕工作室', error.message); app.quit(); });

app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => { shutdown = true; if (worker && worker.exitCode === null) {
  if (windowsApp) spawn('taskkill', ['/pid', String(worker.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
  else { worker.kill('SIGTERM'); setTimeout(() => { if (worker.exitCode === null) worker.kill('SIGKILL'); }, 5000).unref(); }
} });
