import { _electron as electron } from 'playwright';
import binary from 'electron';
import path from 'node:path';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const root = process.cwd();
const output = path.join(root, 'artifacts', 'desktop-' + Date.now());
const directory = path.join(output, '项目 with spaces');
fs.mkdirSync(output, { recursive: true });
const application = await electron.launch({ executablePath: binary, args: ['.'], cwd: root,
  env: { ...process.env, STUDIO_TEST_MODE: '1', STUDIO_TEST_VIDEO: path.join(root, 'artifacts/fixtures/硬字幕 测试视频.mp4'), STUDIO_TEST_PROJECT: directory }, timeout: 30000 });
const errors = [];
let page;
try {
  page = await application.firstWindow();
  async function waitState(predicate, timeout = 120000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const value = await page.evaluate(() => window.studio.request('snapshot'));
      if (predicate(value)) return value;
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    throw new Error('Timed out waiting for worker state');
  }
  page.on('pageerror', error => errors.push(error.message));
  await page.getByRole('button', { name: '选择视频文件', exact: true }).click();
  await page.getByRole('button', { name: '保存区域', exact: true }).waitFor();
  await page.waitForFunction(() => document.querySelector('video')?.readyState >= 1);
  // Real pointer manipulation of the existing crop rectangle.
  const mask = await page.locator('.roi-mask').boundingBox();
  await page.mouse.move(mask.x + 20, mask.y + 20);
  await page.mouse.down(); await page.mouse.move(mask.x + 22, mask.y + 20); await page.mouse.up();
  await page.getByRole('button', { name: '保存区域', exact: true }).click();
  // Configure both adapters through the real settings UI, then restore explicit mock.
  for (const provider of ['api', 'ollama', 'mock']) {
    await page.getByRole('button', { name: '翻译设置', exact: true }).click();
    await page.getByRole('combobox', { name: '服务类型', exact: true }).selectOption(provider);
    if (provider !== 'mock') {
      await page.getByRole('textbox', { name: '服务地址', exact: true }).fill(provider === 'api' ? 'http://localhost:1234/v1' : 'http://localhost:11434');
      await page.getByRole('textbox', { name: '模型名称', exact: true }).fill('settings-contract-only');
    }
    await page.getByRole('textbox', { name: '术语表', exact: true }).fill('Studio = 工作室');
    await page.getByRole('button', { name: '保存设置', exact: true }).click();
    await waitState(value => value.translation.provider === provider);
    assert.equal((await page.evaluate(() => window.studio.settings())).config.provider, provider);
  }
  await page.screenshot({ path: path.join(output, '01-import.png'), fullPage: true });
  await page.getByRole('button', { name: '识别全片 / 继续', exact: true }).click();
  await waitState(value => value.scan.cursor > 2);
  await page.getByRole('button', { name: '取消任务', exact: true }).click();
  await page.getByRole('button', { name: '识别全片 / 继续', exact: true }).waitFor({ timeout: 30000 });
  let state = await page.evaluate(() => window.studio.request('snapshot'));
  assert.equal(state.scan.status, 'cancelled');
  assert(state.scan.cursor > 0 && state.scan.cursor < 60);
  console.log('Cancelled and saved at', state.scan.cursor);
  await page.getByRole('button', { name: '打开项目', exact: true }).click();
  await page.getByRole('button', { name: '识别全片 / 继续', exact: true }).click();
  await waitState(value => value.scan.status === 'complete');
  await page.getByRole('button', { name: '翻译字幕', exact: true }).waitFor();
  state = await page.evaluate(() => window.studio.request('snapshot'));
  assert.equal(state.cues.length, 13);
  fs.writeFileSync(path.join(output, 'recognized.json'), JSON.stringify(state, null, 2));
  await page.getByRole('button', { name: '翻译字幕', exact: true }).click();
  await waitState(value => value.cues.every(cue => cue.translation_status === 'mock'));
  await page.getByRole('button', { name: '保存修改', exact: true }).waitFor();
  await page.locator('.subtitle-row').first().click();
  await page.getByRole('textbox', { name: '识别原文', exact: true }).fill('Welcome to the subtitle studio!');
  await page.getByRole('textbox', { name: '中文译文', exact: true }).fill('欢迎来到字幕工作室。');
  await page.getByRole('spinbutton', { name: '字幕开始时间', exact: true }).fill('2.05');
  await page.getByRole('spinbutton', { name: '字幕结束时间', exact: true }).fill('5.12');
  // No save-button click: verify debounced edits reach SQLite before reopening.
  await waitState(value => value.cues[0].manual_translation === true && value.cues[0].start === 2.05 && value.cues[0].end === 5.12);
  assert.equal((await page.evaluate(() => window.studio.request('snapshot'))).cues[0].translation, '欢迎来到字幕工作室。');
  await page.getByRole('button', { name: '重译这一条', exact: true }).click();
  await page.getByRole('button', { name: '识别全片 / 继续', exact: true }).waitFor();
  assert.equal((await page.evaluate(() => window.studio.request('snapshot'))).cues[0].translation, '欢迎来到字幕工作室。');
  await page.getByRole('button', { name: '打开项目', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('textarea[aria-label="中文译文"]')?.value === '欢迎来到字幕工作室。');
  state = await page.evaluate(() => window.studio.request('snapshot'));
  assert.equal(state.cues[0].source, 'Welcome to the subtitle studio!');
  assert.equal(state.cues[0].start, 2.05); assert.equal(state.cues[0].end, 5.12);
  await page.screenshot({ path: path.join(output, '02-editor.png'), fullPage: true });
  await page.getByRole('button', { name: '生成效果预览', exact: true }).click();
  let completed = await waitState(value => value.task.status !== 'running');
  assert.equal(completed.task.status, 'complete', completed.task.error);
  await page.getByRole('heading', { name: '真实渲染效果', exact: true }).waitFor({ timeout: 10000 });
  await page.waitForFunction(() => document.querySelector('video')?.readyState >= 2);
  await page.locator('video').evaluate(async video => { video.currentTime = 2; await video.play(); });
  await page.waitForFunction(() => document.querySelector('video')?.currentTime > 2.3);
  await page.locator('video').evaluate(video => video.pause());
  await page.screenshot({ path: path.join(output, '03-preview.png'), fullPage: true });
  await page.getByRole('button', { name: '导出 SRT', exact: true }).click();
  await waitState(value => value.outputs.some(file => file.endsWith('.srt')));
  await page.getByRole('button', { name: '导出中文视频 ↗', exact: true }).click();
  completed = await waitState(value => value.task.status !== 'running', 180000);
  assert.equal(completed.task.status, 'complete', completed.task.error);
  assert(completed.outputs.some(file => file.includes('ui-export') && file.endsWith('.mp4')));
  await page.getByRole('button', { name: '翻译字幕', exact: true }).waitFor();
  const renderedPath = completed.outputs.find(file => file.includes('ui-export') && file.endsWith('.mp4'));
  const renderedUrl = await page.evaluate(file => window.studio.mediaUrl(file), renderedPath);
  await page.waitForFunction(url => { const video = document.querySelector('video'); return video?.src === url && video.readyState >= 2; }, renderedUrl);
  await page.locator('video').evaluate(async video => { video.currentTime = 32; await video.play(); });
  await page.waitForFunction(() => document.querySelector('video')?.currentTime > 32.3);
  await page.locator('video').evaluate(video => video.pause());
  await page.screenshot({ path: path.join(output, '04-export-playing.png'), fullPage: true });
  await page.getByRole('button', { name: '合并下一条', exact: true }).click();
  await waitState(value => value.cues.length === 12);
  await page.getByRole('button', { name: '撤销编辑', exact: true }).click();
  await waitState(value => value.cues.length === 13);
  await page.getByRole('button', { name: '拆分字幕', exact: true }).click();
  await waitState(value => value.cues.length === 14);
  await page.getByRole('button', { name: '撤销编辑', exact: true }).click();
  await waitState(value => value.cues.length === 13);
  state = await page.evaluate(() => window.studio.request('snapshot'));
  assert.equal(state.cues[0].translation, '欢迎来到字幕工作室。');
  assert.equal(state.task.status, 'complete');
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify({ passed: true, directory, outputs: state.outputs, rendererErrors: errors, checks: ['真实导入与区域拖动', '真实 OCR 取消与恢复', '13 条字幕', '明确标注 mock', 'API 与 Ollama 设置界面保存', '原文、译文、时间自动保存重开', '人工译文不被重译覆盖', '相同渲染链路预览实际播放', 'SRT 与 MP4 导出实际播放'] }, null, 2));
  console.log('Desktop verification passed:', output);
} catch (error) {
  if (page) {
    const media = await page.locator('video').evaluate(video => ({ src: video.src, currentTime: video.currentTime, duration: video.duration, paused: video.paused, readyState: video.readyState, error: video.error?.message, buffered: Array.from({ length: video.buffered.length }, (_, i) => [video.buffered.start(i), video.buffered.end(i)]) })).catch(() => null);
    fs.writeFileSync(path.join(output, 'media-failure.json'), JSON.stringify(media, null, 2));
  }
  if (page) await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  fs.writeFileSync(path.join(output, 'failure.txt'), String(error.stack));
  console.error('Desktop verification failed:', output, error);
  process.exitCode = 1;
} finally {
  await application.close();
}
