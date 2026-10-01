import {_electron as electron} from 'playwright';
import path from 'node:path';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
const root=process.cwd();
const executablePath=path.join(root,'release-progressive/SubtitleStudioProgressive-darwin-arm64/SubtitleStudioProgressive.app/Contents/MacOS/SubtitleStudioProgressive');
const runs=fs.readdirSync(path.join(root,'artifacts')).filter(name=>/^progressive-desktop-\d+$/.test(name) && fs.existsSync(path.join(root,'artifacts',name,'result.json'))).sort();
const latest=JSON.parse(fs.readFileSync(path.join(root,'artifacts',runs.at(-1),'result.json'),'utf8'));
let legacy=path.join(root,'artifacts/desktop-1790843664528/项目 with spaces');
if(!fs.existsSync(path.join(legacy,'project.sqlite'))) {
 const standardRuns=fs.readdirSync(path.join(root,'artifacts')).filter(name=>/^desktop-\d+$/.test(name) && fs.existsSync(path.join(root,'artifacts',name,'result.json'))).sort();
 if(!standardRuns.length)throw new Error('先运行 npm run test:desktop 创建标准项目');
 const standard=JSON.parse(fs.readFileSync(path.join(root,'artifacts',standardRuns.at(-1),'result.json'),'utf8'));
 legacy=path.join(root,'artifacts','legacy-compatibility-'+Date.now());
 fs.mkdirSync(legacy,{recursive:true});fs.copyFileSync(path.join(standard.directory,'project.sqlite'),path.join(legacy,'project.sqlite'));
 const script=`from worker.core import Project
import sys
from pathlib import Path
import shutil
p=Project(sys.argv[1])
for key in ('recognition_mode','recognition_results','progressive'):p.data.pop(key,None)
for cue in p.data['cues']:
 cue.pop('manual_time',None)
 original=Path(cue.get('screenshot',''))
 if original.is_file():
  target=p.directory/'evidence'/original.name
  shutil.copyfile(original,target)
  cue['screenshot']=str(target)
p.save();p.close()`;
 const prepared=spawnSync(path.join(root,'.venv/bin/python'),['-c',script,legacy],{cwd:root,encoding:'utf8'});
 if(prepared.status!==0)throw new Error(prepared.stderr);
}
const results=[];
for(const [directory,mode,count] of [[legacy,'standard',13],[latest.directory,'progressive',11]]) {
 const application=await electron.launch({executablePath,cwd:root,env:{...process.env,STUDIO_TEST_MODE:'1',STUDIO_TEST_PROJECT:directory},timeout:30000});
 try {
  const page=await application.firstWindow();
  await page.getByRole('button',{name:'打开项目',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('video')?.readyState>=2);
  const data=await page.evaluate(async()=>({project:await window.studio.request('snapshot'),dependencies:await window.studio.request('dependencies')}));
  assert.equal(data.project.recognition_mode,mode);assert.equal(data.project.cues.length,count);
  assert.equal(await page.getByRole('combobox',{name:'字幕识别模式',exact:true}).inputValue(),mode);
  await page.locator('video').evaluate(async video=>{video.currentTime=4;await video.play();});
  await page.waitForFunction(()=>document.querySelector('video')?.currentTime>4.3);
  await page.locator('video').evaluate(video=>video.pause());
  await page.screenshot({path:path.join(root,'artifacts',mode==='standard'?'progressive-package-legacy.png':'progressive-package.png'),fullPage:true});
  results.push({directory,mode,count,dependencies:data.dependencies});
 } finally {await application.close();}
}
fs.writeFileSync(path.join(root,'artifacts/progressive-package-smoke.json'),JSON.stringify({passed:true,executablePath,results},null,2));
console.log('Extension package opens legacy standard and progressive projects and plays their videos');
