// Packaged Mac UI regression; public fixture and explicitly marked mock translation.
import { _electron as electron } from 'playwright';
import binary from 'electron';
import path from 'node:path';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const root=process.cwd();
const output=path.join(root,'artifacts','recognition-desktop-'+Date.now());
fs.mkdirSync(output,{recursive:true});
const packaged=process.env.STUDIO_APP;
const application=await electron.launch({executablePath:packaged||binary,args:packaged?[]:['.'],cwd:root,
  env:{...process.env,STUDIO_TEST_MODE:'1',STUDIO_TEST_USER_DATA:path.join(output,'settings'),
       STUDIO_TEST_VIDEO:path.join(root,'artifacts/fixtures/硬字幕 测试视频.mp4'),STUDIO_TEST_PROJECT:path.join(output,'项目')},timeout:30000});
try {
  const page=await application.firstWindow();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const snapshot=()=>page.evaluate(()=>window.studio.request('snapshot'));
  async function wait(predicate) {
    const end=Date.now()+180000;
    while(Date.now()<end){const data=await snapshot();if(predicate(data))return data;await new Promise(r=>setTimeout(r,200));}
    throw new Error('Packaged recognition task timed out');
  }
  await page.getByRole('button',{name:'选择视频文件',exact:true}).click();
  await page.getByLabel('字幕识别模式').selectOption('dynamic');
  await wait(p=>p.recognition_mode==='dynamic');
  assert.equal(await page.getByLabel('全画面识别质量').inputValue(),'enhanced');
  await page.getByLabel('全画面识别质量').selectOption('legacy');await wait(p=>p.dynamic.profile==='legacy');
  await page.getByLabel('全画面识别质量').selectOption('enhanced');await wait(p=>p.dynamic.profile==='enhanced');
  await page.evaluate(()=>window.studio.request('scan',{start:0,end:6}));
  let data=await wait(p=>p.task.status==='complete'||p.task.status==='failed');
  assert.equal(data.task.status,'complete');assert(data.cues.some(c=>c.dynamic_verified&&!c.ignored));
  const ids=data.cues.map(c=>c.id);
  await page.getByRole('button',{name:'独立检查原片字幕覆盖',exact:true}).click();
  data=await wait(p=>p.task.stage==='audit'&&['complete','failed'].includes(p.task.status));
  assert.equal(data.task.status,'complete');assert(data.scan.coverage_report.independent_pass);
  assert.deepEqual(data.cues.map(c=>c.id),ids); // Audit never rewrites recognized/editable events.
  await page.getByLabel('字幕识别模式').selectOption('standard');await wait(p=>p.recognition_mode==='standard');
  await page.getByLabel('字幕识别模式').selectOption('dynamic');data=await wait(p=>p.recognition_mode==='dynamic');
  assert.deepEqual(data.cues.map(c=>c.id),ids);
  await page.screenshot({path:path.join(output,'public-fixture-ui.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(output,'acceptance.json'),JSON.stringify({passed:true,packaged:!!packaged,
    profile_switching:true,mode_results_preserved:true,source_audit:true,recognized_events:ids.length,
    translation_test:'Not performed here; real cloud/video test is recorded separately.'},null,2));
  console.log(JSON.stringify({passed:true,output}));
} finally {await application.close();}
