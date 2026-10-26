const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync('static/js/quiz.js','utf8');
class Element {
 constructor(){this.hidden=false;this.disabled=false;this.attrs={};this.listeners={};this.style={};this.value='';this.classes=new Set();this.classList={add:v=>this.classes.add(v),toggle:(v,on)=>on?this.classes.add(v):this.classes.delete(v)};}
 addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
 setAttribute(k,v){this.attrs[k]=v;}
 getAttribute(k){return this.attrs[k];}
 removeAttribute(k){delete this.attrs[k];}
 focus(){this.focused=true;}
 emit(k,event={}){if(!event.target)event.target=this;for(const fn of this.listeners[k]||[])fn(event);}
}
function submitEvent(){return {prevented:false,preventDefault(){this.prevented=true;}};}
function setup({draft=false,initialAnswers=[],dirty=false,conflict=false,text=false}={}){
 const form=new Element(), win=new Element(), timers=new Map(),requests=[];let timerId=0;
 win.setTimeout=(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;};win.clearTimeout=id=>timers.delete(id);win.location={reload(){win.reloaded=true;}};
 const questions=Array.from({length:3},(_,i)=>{
  const q=new Element();q.answered=Boolean(initialAnswers[i]);
  if(text){q.text=new Element();q.text.value=initialAnswers[i]||'';}
  else{q.radio=new Element();q.radio.value=initialAnswers[i]||'A';}
  q.querySelector=s=>{
   if(s==='input[data-quiz-text-answer]')return q.text||null;
   if(s==='input[type="radio"]:checked')return q.answered?q.radio||null:null;
   if(s==='input[type="radio"]')return q.radio||null;
   return null;
  };return q;
 });
 const steps=questions.map((_,i)=>{const e=new Element();e.attrs['data-quiz-goto']=String(i);return e;});
 const selectors=['prev','next','submit','nav','position','answered','progress','feedback','savebar','save-status','save','reload','revision'];
 const els=Object.fromEntries(selectors.map(k=>[k,new Element()]));els.progress.fill=new Element();els.progress.querySelector=()=>els.progress.fill;
 const csrf=new Element();csrf.value='test-csrf';
 form.querySelector=s=>s==='input[name="csrfmiddlewaretoken"]'?csrf:els[s.slice('[data-quiz-'.length,-1)]||null;
 form.querySelectorAll=s=>s==='[data-quiz-question]'?questions:s==='[data-quiz-goto]'?steps:[];
 form.attrs={'data-quiz-draft-revision':'0','data-quiz-draft-dirty':String(dirty),'data-quiz-draft-conflict':String(conflict)};
 if(draft)form.attrs['data-quiz-draft-url']='/quiz/1/draft/';
 form.nativeSubmits=0;form.requestSubmit=()=>{const e=submitEvent();form.emit('submit',e);if(!e.prevented)form.nativeSubmits++;};
 const fetch=(url,options)=>new Promise((resolve,reject)=>{requests.push({url,options,resolve,reject});options.signal?.addEventListener('abort',()=>reject(new Error('aborted')));});
 vm.runInNewContext(script,{document:{querySelector:()=>form},window:win,URLSearchParams,AbortController,fetch});
 const runTimers=delay=>{for(const [id,t]of [...timers])if(t.delay===delay){timers.delete(id);t.fn();}};
 return {form,win,questions,steps,requests,timers,runTimers,...els};
}
const tick=()=>new Promise(setImmediate);
async function respond(x,n,{status=200,revision=n+1,count=1,state='saved'}={}){x.requests[n].resolve({ok:status===200,status,redirected:false,json:async()=>({ok:status===200,status:state,revision,saved_count:count,last_saved_at:'2026-10-22T09:00:00Z'})});await tick();}
function select(x,n,value='A'){x.questions[n].answered=true;x.questions[n].radio.value=value;x.form.emit('change',{target:x.questions[n].radio});}
function type(x,n,value,{composing=false}={}){const input=x.questions[n].text;input.value=value;x.form.emit('input',{target:input,isComposing:composing});}
function enter(x,n,extra={}){const event={...submitEvent(),target:x.questions[n].text,key:'Enter',...extra};x.form.emit('keydown',event);return event;}

test('progressive navigation preserves choices and reports answered progress',()=>{
 const x=setup();assert.equal(x.questions[0].hidden,false);assert.equal(x.questions[1].hidden,true);
 select(x,0);assert.equal(x.progress.attrs['aria-valuenow'],'1');assert.equal(x.answered.textContent,'1/3 câu đã trả lời');
 x.next.emit('click');assert.equal(x.questions[0].hidden,true);assert.equal(x.questions[1].hidden,false);assert.equal(x.questions[0].answered,true);
 x.steps[2].emit('click');assert.equal(x.submit.hidden,false);assert.equal(x.next.hidden,true);assert.equal(x.steps[2].attrs['aria-current'],'step');
});
test('unanswered submit opens and focuses missing question without locking form',()=>{
 const x=setup();select(x,0);x.steps[2].emit('click');const e=submitEvent();x.form.emit('submit',e);
 assert.equal(e.prevented,true);assert.equal(x.questions[1].hidden,false);assert.equal(x.questions[1].radio.focused,true);assert.match(x.feedback.textContent,/2 câu chưa trả lời/);assert.equal(x.submit.disabled,false);
});
test('completed submission blocks duplicates and suppresses leave warning',()=>{
 const x=setup();x.questions.forEach(q=>q.answered=true);let e=submitEvent();x.form.emit('submit',e);assert.equal(e.prevented,false);assert.equal(x.submit.disabled,true);
 e=submitEvent();x.form.emit('submit',e);assert.equal(e.prevented,true);
 e=submitEvent();x.win.emit('beforeunload',e);assert.equal(e.prevented,false);
});
test('bfcache page requires current server revision before another submission',()=>{
 const x=setup();x.questions.forEach(q=>q.answered=true);x.form.emit('submit',submitEvent());x.win.emit('pageshow',{persisted:true});
 const e=submitEvent();x.form.emit('submit',e);assert.equal(e.prevented,true);assert.equal(x.reload.hidden,false);assert.match(x['save-status'].textContent,/bản nháp mới nhất/);
});
test('resuming saved answers opens the first remaining question without leave warning',()=>{
 const x=setup({draft:true,initialAnswers:['A','B']});
 assert.equal(x.questions[2].hidden,false);assert.equal(x.questions[0].hidden,true);assert.equal(x.progress.attrs['aria-valuenow'],'2');
 const e=submitEvent();x.win.emit('beforeunload',e);assert.equal(e.prevented,false);assert.equal(x.requests.length,0);
});
test('debounced draft saves full selected snapshot and revision without grading',async()=>{
 const x=setup({draft:true});select(x,0,'B');select(x,1,'C');assert.equal(x.requests.length,0);x.runTimers(600);await tick();assert.equal(x.requests.length,1);
 const p=new URLSearchParams(x.requests[0].options.body);assert.equal(p.get('answer_1'),'B');assert.equal(p.get('answer_2'),'C');assert.equal(p.has('answer_3'),false);assert.equal(p.get('revision'),'0');
 await respond(x,0,{count:2});assert.equal(x.revision.value,'1');assert.equal(x['save-status'].attrs['data-state'],'saved');const e=submitEvent();x.win.emit('beforeunload',e);assert.equal(e.prevented,false);
});
test('acknowledging an older save preserves and later saves newer choices',async()=>{
 const x=setup({draft:true});select(x,0,'A');x.runTimers(600);await tick();select(x,1,'B');x.runTimers(600);await tick();assert.equal(x.requests.length,1);
 await respond(x,0);let e=submitEvent();x.win.emit('beforeunload',e);assert.equal(e.prevented,true);x.runTimers(600);await tick();assert.equal(x.requests.length,2);
 const p=new URLSearchParams(x.requests[1].options.body);assert.equal(p.get('answer_2'),'B');assert.equal(p.get('revision'),'1');
 await respond(x,1,{count:2});e=submitEvent();x.win.emit('beforeunload',e);assert.equal(e.prevented,false);
});
test('unchanged server draft acknowledgment is successful without revision bump',async()=>{
 const x=setup({draft:true,initialAnswers:['A']});select(x,0,'B');select(x,0,'A');x.runTimers(600);await tick();await respond(x,0,{revision:0});
 assert.equal(x['save-status'].attrs['data-state'],'saved');assert.equal(x.revision.value,'0');const e=submitEvent();x.win.emit('beforeunload',e);assert.equal(e.prevented,false);
});
test('submit waits for pending save then submits latest current choices once',async()=>{
 const x=setup({draft:true});select(x,0,'A');x.runTimers(600);await tick();select(x,1,'B');select(x,2,'C');const e=submitEvent();x.form.emit('submit',e);assert.equal(e.prevented,true);assert.equal(x.form.nativeSubmits,0);
 await respond(x,0);assert.equal(x.form.nativeSubmits,1);assert.equal(x.revision.value,'1');assert.equal(x.questions[2].radio.value,'C');assert.equal(x.submit.disabled,true);
});
test('revision conflict preserves choices and blocks silent overwrite and submit',async()=>{
 const x=setup({draft:true});select(x,0,'D');x.runTimers(600);await tick();await respond(x,0,{status:409,state:'conflict',revision:3});
 assert.equal(x.questions[0].radio.value,'D');assert.equal(x.save.disabled,true);assert.equal(x.reload.hidden,false);x.questions.forEach(q=>q.answered=true);const e=submitEvent();x.form.emit('submit',e);assert.equal(e.prevented,true);x.runTimers(600);await tick();assert.equal(x.requests.length,1);
});
test('timeout leaves unsaved choices intact and manual retry available',async()=>{
 const x=setup({draft:true});select(x,0,'C');x.runTimers(600);await tick();x.runTimers(15000);await tick();
 assert.equal(x['save-status'].attrs['data-state'],'error');assert.equal(x.questions[0].radio.value,'C');assert.equal(x.save.disabled,false);assert.equal(x.requests.length,1);const e=submitEvent();x.win.emit('beforeunload',e);assert.equal(e.prevented,true);
 x.save.emit('click');await tick();assert.equal(x.requests.length,2);await respond(x,1,{revision:1});assert.equal(x['save-status'].attrs['data-state'],'saved');
});

test('typed drafts resume at the first blank and navigation focuses its input',()=>{
 const x=setup({draft:true,text:true,initialAnswers:['agenda','','ticket']});
 assert.equal(x.questions[1].hidden,false);assert.equal(x.progress.attrs['aria-valuenow'],'2');assert.equal(x.requests.length,0);
 const leave=submitEvent();x.win.emit('beforeunload',leave);assert.equal(leave.prevented,false);
 x.prev.emit('click');assert.equal(x.questions[0].text.focused,true);assert.equal(x.questions[0].text.value,'agenda');
});

test('typed autosave preserves raw spelling and ignores duplicate change or final input events',async()=>{
 const x=setup({draft:true,text:true});type(x,0,'  Meet   A Deadline  ');type(x,1,'applicant’s résumé');
 x.form.emit('change',{target:x.questions[0].text});x.runTimers(600);await tick();
 assert.equal(x.requests.length,1);const payload=new URLSearchParams(x.requests[0].options.body);
 assert.equal(payload.get('answer_1'),'  Meet   A Deadline  ');assert.equal(payload.get('answer_2'),'applicant’s résumé');assert.equal(payload.has('answer_3'),false);
 await respond(x,0,{count:2});type(x,1,'applicant’s résumé');x.runTimers(600);await tick();
 assert.equal(x.requests.length,1);assert.equal(x.questions[0].text.value,'  Meet   A Deadline  ');
 const leave=submitEvent();x.win.emit('beforeunload',leave);assert.equal(leave.prevented,false);
});

test('clearing a typed answer removes it from the full draft and whitespace cannot complete a question',async()=>{
 const x=setup({draft:true,text:true,initialAnswers:['agenda']});type(x,0,'   ');
 assert.equal(x.progress.attrs['aria-valuenow'],'0');x.runTimers(600);await tick();
 const payload=new URLSearchParams(x.requests[0].options.body);assert.equal(payload.has('answer_1'),false);
 await respond(x,0,{count:0});const event=submitEvent();x.form.emit('submit',event);
 assert.equal(event.prevented,true);assert.equal(x.questions[0].text.focused,true);assert.match(x.feedback.textContent,/3 câu chưa trả lời/);
 assert.equal(x.questions[0].text.value,'   ');
});

test('older draft acknowledgment cannot overwrite newer typed text or a cleared field',async()=>{
 const x=setup({draft:true,text:true});type(x,0,'agenda');type(x,1,'printer');x.runTimers(600);await tick();
 type(x,0,'  annual report ');type(x,1,'');x.runTimers(600);await tick();assert.equal(x.requests.length,1);
 await respond(x,0,{count:2});assert.equal(x.questions[0].text.value,'  annual report ');assert.equal(x.questions[1].text.value,'');
 x.runTimers(600);await tick();const payload=new URLSearchParams(x.requests[1].options.body);
 assert.equal(payload.get('answer_1'),'  annual report ');assert.equal(payload.has('answer_2'),false);assert.equal(payload.get('revision'),'1');
 await respond(x,1,{count:1});const leave=submitEvent();x.win.emit('beforeunload',leave);assert.equal(leave.prevented,false);
});

test('typed draft conflicts preserve answers and stop further saves and submission',async()=>{
 const x=setup({draft:true,text:true});type(x,0,'deadline');x.runTimers(600);await tick();
 await respond(x,0,{status:409,state:'conflict',revision:5});
 type(x,1,'schedule');type(x,2,'printer');x.runTimers(600);x.save.emit('click');await tick();
 assert.equal(x.requests.length,1);assert.equal(x.questions[0].text.value,'deadline');assert.equal(x.reload.hidden,false);
 const event=submitEvent();x.form.emit('submit',event);assert.equal(event.prevented,true);assert.equal(x.submit.disabled,true);
});

test('IME composition never autosaves partial text or lets Enter navigate or submit',async()=>{
 const x=setup({draft:true,text:true});const input=x.questions[0].text;
 x.form.emit('compositionstart',{target:input});type(x,0,'lị',{composing:true});x.runTimers(600);x.save.emit('click');await tick();
 assert.equal(x.requests.length,0);assert.equal(enter(x,0,{isComposing:true,keyCode:229}).prevented,false);assert.equal(x.questions[0].hidden,false);
 const submit=submitEvent();x.form.emit('submit',submit);assert.equal(submit.prevented,true);assert.equal(x.form.nativeSubmits,0);
 x.next.emit('click');assert.equal(x.questions[0].hidden,false);
 const leave=submitEvent();x.win.emit('beforeunload',leave);assert.equal(leave.prevented,true);
 input.value='lịch';x.form.emit('compositionend',{target:input});type(x,0,'lịch');x.runTimers(600);await tick();
 assert.equal(x.requests.length,1);assert.equal(new URLSearchParams(x.requests[0].options.body).get('answer_1'),'lịch');
 await respond(x,0);type(x,0,'lịch');x.runTimers(600);await tick();assert.equal(x.requests.length,1);
 assert.equal(enter(x,0).prevented,true);assert.equal(x.questions[1].hidden,false);
});

test('Enter moves between typed questions and final Enter follows normal single-submit validation',()=>{
 const x=setup({text:true});type(x,0,'agenda');assert.equal(enter(x,0).prevented,true);
 assert.equal(x.questions[1].hidden,false);assert.equal(x.questions[1].text.focused,true);assert.equal(x.form.nativeSubmits,0);
 type(x,1,'bank');enter(x,1);assert.equal(x.questions[2].hidden,false);type(x,2,'ticket');enter(x,2);
 assert.equal(x.form.nativeSubmits,1);assert.equal(x.submit.disabled,true);enter(x,2);assert.equal(x.form.nativeSubmits,1);
});

test('save finishing during a new composition does not send its partial input',async()=>{
 const x=setup({draft:true,text:true});type(x,0,'agenda');x.runTimers(600);await tick();
 x.form.emit('compositionstart',{target:x.questions[1].text});type(x,1,'pr',{composing:true});
 await respond(x,0);x.runTimers(600);await tick();assert.equal(x.requests.length,1);
 x.questions[1].text.value='printer';x.form.emit('compositionend',{target:x.questions[1].text});x.runTimers(600);await tick();
 assert.equal(x.requests.length,2);assert.equal(new URLSearchParams(x.requests[1].options.body).get('answer_2'),'printer');
});

test('composition started while submit waits for a save requires a deliberate submit after committing',async()=>{
 const x=setup({draft:true,text:true});type(x,0,'agenda');type(x,1,'bank');type(x,2,'ticket');x.runTimers(600);await tick();
 const submit=submitEvent();x.form.emit('submit',submit);assert.equal(submit.prevented,true);assert.equal(x.form.nativeSubmits,0);
 x.form.emit('compositionstart',{target:x.questions[2].text});type(x,2,'tick',{composing:true});await respond(x,0,{count:3});
 assert.equal(x.form.nativeSubmits,0);assert.equal(x.submit.disabled,false);
 x.questions[2].text.value='tickets';x.form.emit('compositionend',{target:x.questions[2].text});x.runTimers(600);await tick();
 assert.equal(new URLSearchParams(x.requests[1].options.body).get('answer_3'),'tickets');await respond(x,1,{count:3});
 assert.equal(x.form.nativeSubmits,0);x.form.requestSubmit();assert.equal(x.form.nativeSubmits,1);
});
