// CDP recorder for a private, job-owned Chromium/Electron renderer. Node.js >=22.
'use strict';
const fs=require('fs'), path=require('path'), crypto=require('crypto');
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const output=process.argv[3], folder=path.dirname(output);
const result={driver:input.driver,complete:false,steps:[],states:[],requests:[],console:[],unknowns:[]};
const pending=new Map(), activeRequests=new Map();
let ws, sequence=0, recording=true, currentStep=-1, imageBytes=0;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
function persist() { fs.writeFileSync(output+'.tmp',JSON.stringify(result));fs.renameSync(output+'.tmp',output); }
function url(value) {
  const parsed=new URL(value);
  if(!['http:','https:','file:','about:'].includes(parsed.protocol)) throw Error('Unsupported navigation URL');
  return value;
}
function rpc(method,params={}) {
  return new Promise((resolve,reject)=>{
    const id=++sequence, timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP command timed out: '+method));},10000);
    pending.set(id,{resolve: value=>{clearTimeout(timer);resolve(value);},reject: e=>{clearTimeout(timer);reject(e);}});
    ws.send(JSON.stringify({id,method,params}));
  });
}
async function evaluate(expression) {
  const value=await rpc('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
  if(value.exceptionDetails) throw Error(value.exceptionDetails.text || 'Page evaluation failed');
  return value.result?.value;
}
function event(message) {
  const p=message.params || {};
  if(message.method==='Network.requestWillBeSent' && recording) {
    if(result.requests.length>=2000) { if(!result.unknowns.includes('network-request-limit')) result.unknowns.push('network-request-limit');return; }
    const previous=activeRequests.get(p.requestId);
    if(previous && p.redirectResponse) { previous.status=p.redirectResponse.status;previous.redirected=true;previous.finished=true; }
    const frames=(p.initiator?.stack?.callFrames || []).slice(0,16).map(f=>({functionName:f.functionName,url:f.url,line:f.lineNumber+1,column:f.columnNumber+1}));
    const row={index:result.requests.length,step:currentStep,requestId:p.requestId,url:String(p.request?.url || '').slice(0,4096),
      method:p.request?.method,type:p.type,status:null,mimeType:null,finished:false,failed:false,initiator:frames};
    result.requests.push(row);activeRequests.set(p.requestId,row);
  }
  const row=activeRequests.get(p.requestId);
  if(row && message.method==='Network.responseReceived') {
    row.status=p.response.status;row.mimeType=p.response.mimeType;
    row.fromDiskCache=!!p.response.fromDiskCache;row.fromServiceWorker=!!p.response.fromServiceWorker;
  }
  if(row && message.method==='Network.loadingFinished') {row.finished=true;row.encodedDataLength=p.encodedDataLength;}
  if(row && message.method==='Network.loadingFailed') {row.finished=true;row.failed=true;row.error=p.errorText;}
  if(message.method==='Runtime.consoleAPICalled') {
    if(result.console.length<500)result.console.push({type:p.type,
      text:(p.args || []).map(a=>a.type==='string'?a.value:a.type==='number'||a.type==='boolean'?String(a.value):a.description || a.type).join(' ').slice(0,4000)});
    else if(!result.unknowns.includes('console-entry-limit'))result.unknowns.push('console-entry-limit');
  }
}
async function element(selector) {
  const data=await evaluate(`(()=>{const rows=[...document.querySelectorAll(${JSON.stringify(selector)})];
    if(rows.length!==1)return {count:rows.length};const e=rows[0];e.scrollIntoView({block:'center'});
    const r=e.getBoundingClientRect();return {count:1,x:r.x+r.width/2,y:r.y+r.height/2,width:r.width,height:r.height,
      disabled:!!e.disabled,password:e.type==='password'};})()`);
  if(!data || data.count!==1) throw Error('Selector must match exactly one element');
  if(data.disabled || data.width<=0 || data.height<=0) throw Error('Element is disabled or hidden');
  return data;
}
async function click(selector) {
  const e=await element(selector);
  const covered=await evaluate(`(()=>{const top=document.elementFromPoint(${e.x},${e.y});const e=document.querySelector(${JSON.stringify(selector)});return !!top && (top===e || e.contains(top));})()`);
  if(!covered) throw Error('Element is covered by another element');
  await rpc('Input.dispatchMouseEvent',{type:'mousePressed',x:e.x,y:e.y,button:'left',clickCount:1});
  await rpc('Input.dispatchMouseEvent',{type:'mouseReleased',x:e.x,y:e.y,button:'left',clickCount:1});
}
async function state(index,label) {
  const snapshot=await evaluate(`(()=>({title:document.title,url:location.href,
    text:(document.body?.innerText || '').slice(0,100000),
    elements:[...document.querySelectorAll('button,input,select,textarea,a,[role],[id]')].slice(0,1000).map(e=>({
      tag:e.tagName,id:e.id,role:e.getAttribute('role') || '',name:e.getAttribute('aria-label') || '',
      text:(e.innerText || '').slice(0,500),value:e.type==='password'?'[redacted]':String(e.value || '').slice(0,500),
      disabled:!!e.disabled,checked:!!e.checked})),
    elementCount:document.querySelectorAll('button,input,select,textarea,a,[role],[id]').length}))()`);
  if(snapshot.elementCount>1000) result.unknowns.push('dom-element-limit');
  if(snapshot.text.length>=100000)result.unknowns.push('dom-text-limit');
  const row={step:index,label,state:snapshot,stateSha256:hash(JSON.stringify(snapshot)),image:null};
  try {
    const shot=await rpc('Page.captureScreenshot',{format:'png',captureBeyondViewport:false,fromSurface:true});
    const pixels=Buffer.from(shot.data,'base64');
    if(pixels.length>16*1024*1024 || imageBytes+pixels.length>128*1024*1024) throw Error('Screenshot limit');
    imageBytes+=pixels.length;
    const name='screen-'+String(index+1).padStart(3,'0')+'.png';
    fs.writeFileSync(path.join(folder,name),pixels);row.image={name,sha256:hash(pixels),bytes:pixels.length};
  } catch(error) {row.imageError=String(error.message).slice(0,1000);result.unknowns.push('screenshot-unavailable');}
  result.states.push(row);persist();
}
async function run() {
  if(typeof WebSocket==='undefined') throw Error('Node.js 22 or newer is required');
  const endpoint=new URL(input.endpoint);
  if(endpoint.protocol!=='http:' || endpoint.hostname!=='127.0.0.1') throw Error('CDP endpoint must be loopback');
  let targets=[];const targetDeadline=Date.now()+10000;
  while(targets.length!==1) {
    const response=await fetch(input.endpoint+'/json/list',{signal:AbortSignal.timeout(5000)});
    targets=(await response.json()).filter(t=>t.type==='page' && (!input.targetUrl || t.url===input.targetUrl));
    if(targets.length>1 || Date.now()>targetDeadline)throw Error('Choose exactly one renderer target URL');
    if(!targets.length)await sleep(100);
  }
  const socketUrl=new URL(targets[0].webSocketDebuggerUrl);
  if(!['127.0.0.1','localhost'].includes(socketUrl.hostname) || socketUrl.port!==endpoint.port) throw Error('Invalid renderer endpoint');
  ws=new WebSocket(socketUrl);
  await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('CDP connect timeout')),5000);
    ws.addEventListener('open',()=>{clearTimeout(timer);resolve();},{once:true});
    ws.addEventListener('error',()=>{clearTimeout(timer);reject(Error('CDP connection failed'));},{once:true});});
  ws.addEventListener('message',e=>{
    if(String(e.data).length>32*1024*1024)return;
    const message=JSON.parse(e.data);
    if(message.id && pending.has(message.id)) {const p=pending.get(message.id);pending.delete(message.id);
      if(message.error)p.reject(Error(message.error.message));else p.resolve(message.result || {});
    } else event(message);
  });
  ws.addEventListener('close',()=>{for(const p of pending.values())p.reject(Error('Renderer disconnected'));pending.clear();});
  if(input.network)await rpc('Network.enable');await rpc('Page.enable');await rpc('Runtime.enable');
  await rpc('Network.setCacheDisabled',{cacheDisabled:true});
  if(input.driver==='chromium') await rpc('Emulation.setDeviceMetricsOverride',{width:1280,height:800,deviceScaleFactor:1,mobile:false});
  if(input.url) {const navigation=await rpc('Page.navigate',{url:url(input.url)});if(navigation.errorText)throw Error(navigation.errorText);}
  const readyDeadline=Date.now()+10000;
  while(await evaluate('document.readyState')!=='complete') {if(Date.now()>readyDeadline)throw Error('Page readiness timeout');await sleep(50);}
  await sleep(input.settleMs);await state(-1,'initial');
  for(let i=0;i<input.steps.length;i++) {
    currentStep=i;
    const step=input.steps[i], row={index:i,action:step.action,selector:step.selector || '',status:'running'};
    result.steps.push(row);persist();
    try {
      if(step.action==='wait') await sleep(step.ms);
      else if(step.action==='click') await click(step.selector);
      else if(step.action==='fill') {
        const e=await element(step.selector);if(e.password)throw Error('Password fields are not supported by recorded fill');
        await click(step.selector);
        await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(step.selector)});
          const proto=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
          const setter=Object.getOwnPropertyDescriptor(proto,'value')?.set;if(!setter)throw Error('Element is not editable');
          setter.call(e,'');e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
        await rpc('Input.insertText',{text:step.text});
      } else if(step.action==='press') {
        await element(step.selector);await evaluate(`document.querySelector(${JSON.stringify(step.selector)}).focus()`);
        const keys={Enter:13,Tab:9,Escape:27,ArrowDown:40,ArrowUp:38,Space:32};
        const fields={key:step.key==='Space'?' ':step.key,code:step.key,windowsVirtualKeyCode:keys[step.key]};
        const text=step.key==='Enter'?'\r':step.key==='Space'?' ':null;
        await rpc('Input.dispatchKeyEvent',{type:'keyDown',...fields,...(text===null?{}:{text,unmodifiedText:text})});
        await rpc('Input.dispatchKeyEvent',{type:'keyUp',...fields});
      } else if(step.action==='navigate') {const navigation=await rpc('Page.navigate',{url:url(step.url)});if(navigation.errorText)throw Error(navigation.errorText);}
      else if(step.action==='assertText' || step.action==='waitFor') {
        const deadline=Date.now()+step.timeoutMs;
        while(true) {
          const matched=await evaluate(`(()=>{const rows=[...document.querySelectorAll(${JSON.stringify(step.selector)})];
            return rows.length===1 && ${step.action==='assertText'?'String(rows[0].innerText || rows[0].textContent || "").includes('+JSON.stringify(step.text)+')':'true'};})()`);
          if(matched)break;if(Date.now()>deadline)throw Error('Element or text assertion timed out');await sleep(50);
        }
      }
      await sleep(input.settleMs);await state(i,step.label || step.action);row.status='passed';persist();
    } catch(error) {row.status='failed';row.error=String(error.message).slice(0,1000);await state(i,'failure').catch(()=>{});throw error;}
  }
  if(result.requests.some(r=>!r.finished))result.unknowns.push('network-requests-unfinished');
  result.complete=!result.unknowns.length;
}
run().catch(error=>{result.error=String(error.message).slice(0,2000);result.complete=false;}).finally(()=>{
  recording=false;persist();if(ws)ws.close();setTimeout(()=>process.exit(result.error?1:0),100);
});
