import { _electron as electron } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const root = process.cwd();
const executablePath = path.join(root, 'release/SubtitleStudio-darwin-arm64/SubtitleStudio.app/Contents/MacOS/SubtitleStudio');
const run = process.argv[2] || fs.readdirSync(path.join(root,'artifacts')).filter(name => /^desktop-\d+$/.test(name) && fs.existsSync(path.join(root,'artifacts',name,'result.json'))).sort().at(-1);
const directory = JSON.parse(fs.readFileSync(path.join(root,'artifacts',run,'result.json'),'utf8')).directory;
const application = await electron.launch({ executablePath, cwd:root,
  env: {...process.env, STUDIO_TEST_MODE:'1', STUDIO_TEST_PROJECT:directory}, timeout:30000 });
try {
  const page = await application.firstWindow();
  await page.getByRole('button', { name:'打开项目', exact:true }).click();
  await page.waitForFunction(() => document.querySelector('video')?.readyState >= 2);
  const result = await page.evaluate(async () => ({project:await window.studio.request('snapshot'), dependencies:await window.studio.request('dependencies')}));
  assert.equal(result.project.cues.length,13);
  assert.equal(result.project.cues[0].translation,'欢迎来到字幕工作室。');
  assert(result.dependencies.ocr.languages.length > 0);
  await page.locator('video').evaluate(async video => { video.currentTime=3; await video.play(); });
  await page.waitForFunction(() => document.querySelector('video')?.currentTime > 3.3);
  await page.locator('video').evaluate(video => video.pause());
  await page.screenshot({path:path.join(root,'artifacts/packaged-app.png'),fullPage:true});
  fs.writeFileSync(path.join(root,'artifacts/package-smoke.json'),JSON.stringify({passed:true,executablePath,project:directory,cues:result.project.cues.length,dependencies:result.dependencies},null,2));
  console.log('Packaged application opens saved project and plays video');
} finally { await application.close(); }
