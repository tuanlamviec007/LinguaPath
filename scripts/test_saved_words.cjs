const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=fs.readFileSync('static/js/saved-words.js','utf8');
class El{
 constructor(){this.attrs={};this.listeners={};this.value='';this.disabled=false;this.textContent='';this.classes=new Set();this.classList={toggle:(key,on)=>on?this.classes.add(key):this.classes.delete(key)};}
 getAttribute(k){return this.attrs[k];}setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
 emit(k,e){return Promise.all((this.listeners[k]||[]).map(fn=>fn(e)));}
}
function setup(){
 const timers=new Map();let timer=0;const requests=[];const count=new El();
 const forms=Array.from({length:2},()=>{const f=new El();f.attrs={'data-card-id':'7','data-term':'agenda',action:'/learn/words/7/save/'};f.children={};
 for(const key of ['action','csrfmiddlewaretoken','button','label','icon','status'])f.children[key]=new El();
 f.children.action.value='save';f.children.csrfmiddlewaretoken.value='test-csrf';f.children.label.textContent='Lưu từ';f.children.icon.textContent='☆';
 f.querySelector=s=>({'input[name="action"]':f.children.action,'input[name="csrfmiddlewaretoken"]':f.children.csrfmiddlewaretoken,'button[type="submit"]':f.children.button,'[data-save-label]':f.children.label,'[data-save-icon]':f.children.icon,'[data-save-status]':f.children.status})[s];return f;});
 const fetch=(url,options)=>new Promise((resolve,reject)=>{requests.push({url,options,resolve,reject});options.signal?.addEventListener('abort',()=>reject(new Error('timeout')));});
 const window={setTimeout:(fn,delay)=>{timers.set(++timer,{fn,delay});return timer;},clearTimeout:id=>timers.delete(id)};
 vm.runInNewContext(script,{document:{querySelectorAll:s=>s==='[data-save-word]'?forms:[count]},window,fetch,URLSearchParams,AbortController});
 return{forms,requests,count,timers,runTimeout(){for(const [id,t]of [...timers]){timers.delete(id);t.fn();}}};
}
const event=()=>({prevented:false,preventDefault(){this.prevented=true;}});
function resolve(x,n,data={},extras={}){x.requests[n].resolve({ok:true,redirected:false,json:async()=>({ok:true,saved:true,saved_count:1,card_id:7,...data}),...extras});}

test('saving synchronizes both flashcard faces only after confirmed response',async()=>{
 const x=setup();const e=event();const work=x.forms[0].emit('submit',e);assert.equal(e.prevented,true);
 assert.equal(x.requests.length,1);assert.equal(x.forms[0].children.action.value,'save');assert.ok(x.forms.every(f=>f.children.button.disabled));
 assert.equal(new URLSearchParams(x.requests[0].options.body).get('action'),'save');
 resolve(x,0);await work;
 for(const f of x.forms){assert.equal(f.children.action.value,'remove');assert.equal(f.children.button.attrs['aria-pressed'],'true');assert.equal(f.children.label.textContent,'Đã lưu');assert.equal(f.children.button.disabled,false);}
 assert.equal(x.count.textContent,'1');
 const removed=x.forms[1].emit('submit',event());assert.equal(new URLSearchParams(x.requests[1].options.body).get('action'),'remove');resolve(x,1,{saved:false,saved_count:0});await removed;
 assert.ok(x.forms.every(f=>f.children.action.value==='save'));assert.equal(x.count.textContent,'0');
});
test('concurrent clicks on two faces send a single request for that card',async()=>{
 const x=setup();const work=x.forms[0].emit('submit',event());await x.forms[1].emit('submit',event());assert.equal(x.requests.length,1);resolve(x,0);await work;
});
test('failed request keeps explicit action so retry cannot accidentally remove a saved word',async()=>{
 const x=setup();let work=x.forms[0].emit('submit',event());x.requests[0].reject(new Error('lost response'));await work;
 assert.equal(x.forms[0].children.action.value,'save');assert.equal(x.forms[0].children.button.disabled,false);assert.equal(x.forms[0].children.status.attrs['data-state'],'error');
 work=x.forms[0].emit('submit',event());assert.equal(new URLSearchParams(x.requests[1].options.body).get('action'),'save');resolve(x,1);await work;assert.equal(x.forms[0].children.action.value,'remove');
});
test('malformed or redirected responses never claim the word was saved',async()=>{
 for(const extras of [{redirected:true},{}]){const x=setup();const work=x.forms[0].emit('submit',event());resolve(x,0,extras.redirected?{}:{card_id:99},extras);await work;assert.equal(x.forms[0].children.action.value,'save');assert.equal(x.forms[0].children.status.attrs['data-state'],'error');}
});
test('timeout re-enables controls and retains previous saved state',async()=>{
 const x=setup();const work=x.forms[0].emit('submit',event());x.runTimeout();await work;assert.equal(x.forms[0].children.button.disabled,false);assert.equal(x.forms[0].children.action.value,'save');assert.equal(x.requests.length,1);
});
