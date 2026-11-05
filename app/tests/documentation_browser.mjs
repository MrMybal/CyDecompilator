// Real file:// verification, with the user's installed Chromium. No test server,
// browser download or Playwright dependency. All temporary files stay in runtime/.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const output = resolve(root, 'runtime/build/cydoc-browser'); mkdirSync(output, {recursive:true});
const browser = process.argv.find(arg=>arg.startsWith('--browser='))?.slice(10) || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
].find(existsSync);
assert(browser, 'Pass --browser=/path/to/an/installed/chromium');
const profile = resolve(output, `profile-${process.pid}`); mkdirSync(profile);
const child = spawn(browser, ['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update',
  '--disable-extensions','--window-size=1440,1000','about:blank'], {windowsHide:true,stdio:'ignore'});
let socket;
const sleep = ms=>new Promise(resolve=>setTimeout(resolve,ms));
const pending = new Map(); let sequence=0;
const failures = [], requests = [], checks = [];
function call(method, params={}) {
  return new Promise((resolve,reject)=>{
    const id=++sequence;
    const timer=setTimeout(()=>{pending.delete(id);reject(Error(`CDP timeout: ${method}`));},10000);
    pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));
  });
}
async function evaluate(expression) {
  const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  if(result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function wait(expression) {
  const until=Date.now()+8000;
  while(Date.now()<until){if(await evaluate(expression))return;await sleep(75);}
  throw Error(`Reader did not satisfy: ${expression}`);
}
async function key(key,code=key,modifiers=0) {
  const windowsVirtualKeyCode={Escape:27,Tab:9,Enter:13,ArrowDown:40,ArrowUp:38,k:75,'+':187,'0':48}[key] || 0;
  await call('Input.dispatchKeyEvent',{type:'keyDown',key,code,modifiers,windowsVirtualKeyCode});
  await call('Input.dispatchKeyEvent',{type:'keyUp',key,code,modifiers,windowsVirtualKeyCode});
}
async function navigate(hash) {
  await evaluate(`location.hash=${JSON.stringify(hash)}`);
  const page=hash.split('/')[2]?.split('?')[0];
  await wait(`document.querySelector('.side-nav [data-page=${JSON.stringify(page)}]')?.classList.contains('active')`);
  await sleep(80);
}
async function screenshot(name) {
  const {data}=await call('Page.captureScreenshot',{format:'png'});
  writeFileSync(resolve(output,`${name}.png`),Buffer.from(data,'base64'));
}

try {
  for(let i=0;i<100&&!existsSync(resolve(profile,'DevToolsActivePort'));i++)await sleep(100);
  const port=readFileSync(resolve(profile,'DevToolsActivePort'),'utf8').split('\n')[0];
  const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(targets.find(target=>target.type==='page').webSocketDebuggerUrl);
  socket.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id){const entry=pending.get(msg.id);if(entry){clearTimeout(entry.timer);pending.delete(msg.id);msg.error?entry.reject(Error(JSON.stringify(msg.error))):entry.resolve(msg.result);}}
    else if(msg.method==='Runtime.exceptionThrown')failures.push(msg.params.exceptionDetails);
    else if(msg.method==='Network.requestWillBeSent')requests.push(msg.params.request.url);
  };
  socket.onclose=()=>{for(const entry of pending.values()){clearTimeout(entry.timer);entry.reject(Error('Browser closed'));}pending.clear();};
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
  await Promise.all([call('Page.enable'),call('Runtime.enable'),call('Network.enable')]);
  // Block external resources and put the browser offline before reading the file export.
  await call('Network.setBlockedURLs',{urls:['http://*','https://*']});
  await call('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
  const base=pathToFileURL(resolve(root,'app/help/index.html')).href;
  await call('Page.navigate',{url:base+'#/en/overview/welcome-to-cydecompilator'});
  await wait(`document.querySelector('article')?.textContent.includes('CyDecompilator')`);
  assert.equal(await evaluate('location.hash'),'#/en/start');
  assert.equal(await evaluate(`document.querySelector('#app').dataset.theme`),'nord');
  await wait(`document.querySelector('article img')?.complete && document.querySelector('article img')?.naturalWidth>0`);
  assert(await evaluate(`document.querySelector('article svg')!==null`),'Static SVG workflow is missing');
  await screenshot('overview-en');checks.push('offline file URL, nord theme, screenshot and static SVG');

  await navigate('#/en/workspace/follow-the-code');
  await wait(`document.querySelector('#follow-the-code')!==null`);
  await evaluate(`const language=document.querySelector('.locale-control select');language.value='fr';language.dispatchEvent(new Event('change',{bubbles:true}));`);
  await wait(`location.hash==='#/fr/workspace/follow-the-code' && document.querySelector('article').lang==='fr'`);
  checks.push('direct section link and EN/FR switch retain common anchor');
  await evaluate(`location.hash='#/fr/workspace/suivre-le-code'`);
  await wait(`location.hash==='#/fr/workspace/follow-the-code'`);
  checks.push('historic French heading links redirect to the canonical section');

  await key('k','KeyK',2);
  await wait(`document.querySelector('dialog').open && document.activeElement.type==='search'`);
  await evaluate(`const search=document.querySelector('.search-form input');search.value='reconstruction_run';search.dispatchEvent(new Event('input',{bubbles:true}));`);
  await wait(`document.querySelectorAll('.search-result').length>0`);
  assert(await evaluate(`[...document.querySelectorAll('.search-result')].some(a=>a.textContent.includes('reconstruction'))`));
  // Chromium first clears a nonempty type=search input with Escape; the next
  // Escape closes its native dialog. Exercise that actual browser behavior.
  await key('Escape');
  if(await evaluate(`document.querySelector('dialog').open`)) await key('Escape');
  await wait(`!document.querySelector('dialog').open`);
  checks.push('Ctrl+K keyboard search, results and native Escape dismissal');

  await navigate('#/fr/start?media=workspace-screenshot&note=function-list');
  await wait(`document.querySelector('[data-cydoc-id="workspace-screenshot"].cy-media')!==null`);
  await sleep(300);
  writeFileSync(resolve(output,'media-dom.html'),await evaluate(`document.querySelector('[data-cydoc-id="workspace-screenshot"]').outerHTML`));
  await screenshot('media-fr');
  // Exact accessible controls are inspected rather than depending on pixel locations.
  const controls=await evaluate(`[...document.querySelectorAll('[data-cydoc-id="workspace-screenshot"] button')].map(b=>({text:b.textContent,aria:b.getAttribute('aria-label'),title:b.title}))`);
  writeFileSync(resolve(output,'controls.json'),JSON.stringify(controls,null,2));
  checks.push('direct image/annotation deep link in French');
  assert(await evaluate(`document.querySelector('.image-markup g').getAttribute('stroke')==='#ffe28b'`),'Annotation deep link was not selected');
  await evaluate(`document.querySelector('[data-action="expand"]').click()`);
  await wait(`document.querySelector('.media-expanded')!==null`);
  assert(await evaluate(`(()=>{const r=document.querySelector('.media-expanded').getBoundingClientRect();return !document.fullscreenElement && r.left>=0 && r.top>=0 && r.right<=innerWidth+1 && r.bottom<=innerHeight+1;})()`));
  await screenshot('enlarged-fr');
  await evaluate(`document.querySelector('.media-stage').focus()`);
  await key('+','Equal');
  assert.equal(await evaluate(`document.querySelector('.zoom-value').textContent`),'125%');
  await key('0','Digit0');
  assert.equal(await evaluate(`document.querySelector('.zoom-value').textContent`),'100%');
  await key('Escape');await wait(`document.querySelector('.media-expanded')===null`);
  checks.push('bounded in-window enlargement, keyboard zoom/reset and Escape');

  await navigate('#/en/engines');
  await evaluate(`scrollTo({top:600,behavior:'instant'})`);
  const scroll=await evaluate('scrollY');assert(scroll>0);
  await navigate('#/en/storage');
  await evaluate('history.back()');
  await wait(`location.hash==='#/en/engines' && Math.abs(scrollY-${scroll})<3`);
  checks.push('browser history restores reading position');

  await navigate('#/en/operation-api');
  assert(await evaluate(`document.querySelector('article').textContent.includes('95')`));
  await navigate('#/en/op-reconstruction-run/contract');
  assert(await evaluate(`document.querySelector('article').textContent.includes('inputSchema')`));
  await navigate('#/fr/source-policy');
  await navigate('#/en/source-generated-sources-app-documentation-py/L1');
  assert(await evaluate(`document.querySelector('#L1')!==null`));
  await navigate('#/fr/translation-report');
  checks.push('generated operation schemas, allowlisted sources/line link and translation report');
  await evaluate(`document.querySelector('[data-set-theme="paper"]').click()`);
  await call('Page.reload');
  await wait(`document.querySelector('#app').dataset.theme==='paper'`);
  await evaluate(`document.querySelector('[data-set-theme="nord"]').click()`);
  assert(await evaluate(`document.querySelector('.footer').textContent.includes('GPL-3.0-only')`));
  checks.push('saved theme survives reload and reader/application licenses remain distinct');

  await call('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await call('Emulation.setTouchEmulationEnabled',{enabled:true});
  await navigate('#/fr/start');
  await evaluate(`document.querySelector('[data-menu]').click()`);
  assert.equal(await evaluate(`document.querySelector('[data-menu]').getAttribute('aria-expanded')`),'true');
  await evaluate(`document.querySelector('[data-menu]').click()`);
  await screenshot('mobile-fr');
  await evaluate(`document.querySelector('[data-cydoc-id="workspace-screenshot"]').scrollIntoView({block:'center',behavior:'instant'})`);
  await wait(`document.querySelector('[data-cydoc-id="workspace-screenshot"].cy-media')!==null`);
  const point=await evaluate(`(()=>{const r=document.querySelector('.image-pan').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
  await call('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[point]});
  await call('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:point.x+30,y:point.y+20}]});
  await call('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  assert(await evaluate(`document.querySelector('.image-layer img').style.transform.includes('30px')`),'Touch drag did not pan the image');
  checks.push('narrow touch viewport, navigation menu and actual image touch drag');
  const external=requests.filter(url=>!url.startsWith('file:')&&!url.startsWith('data:')&&!url.startsWith('blob:'));
  assert.deepEqual(external,[],'Documentation attempted external network requests');
  assert.deepEqual(failures,[],'Browser JavaScript errors');
  const result={browser,checks,requests:requests.length,externalRequests:external,errors:failures};
  writeFileSync(resolve(output,'result.json'),JSON.stringify(result,null,2));
  writeFileSync(resolve(output,browser.toLowerCase().includes('msedge')?'edge-result.json':'chrome-result.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2));
} catch(error) {
  if(socket?.readyState===WebSocket.OPEN){
    writeFileSync(resolve(output,'failure.json'),JSON.stringify({error:String(error),failures,requests},null,2));
    try{await screenshot('failure');}catch{}
  }
  throw error;
} finally {
  if(socket?.readyState===WebSocket.OPEN){try{await call('Browser.close');}catch{} socket.close();}
  child.kill();
}
