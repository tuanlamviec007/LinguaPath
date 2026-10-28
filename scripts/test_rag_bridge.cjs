const test=require('node:test'),assert=require('node:assert/strict');
const modulePromise=import('../deploy/cloudflare/rag-runtime.js');
const secret='test-only-service-secret-not-a-real-credential-0000';
function setup(){
 const store=new Map();let tail=Promise.resolve();
 const storage={get:k=>store.get(k),put(k,v){store.set(k,structuredClone(v));},transaction(fn){const run=tail.then(()=>fn(storage));tail=run.catch(()=>{});return run;}};
 const calls=[];
 const env={AI_TUTOR_ENABLED:'true',AI_BRIDGE_SECRET:secret,AI_INDEX_SECRET:secret+'index',
   AI:{async run(model,payload){calls.push({model,payload});return model.includes('bge')?{data:payload.text.map(()=>Array(1024).fill(.01))}:{response:'Grounded answer'};}},
   VECTORIZE:{async query(){return {matches:[{id:'knowledge:passive',score:.9,metadata:{version:'a'.repeat(64)}}]};},async upsert(docs){calls.push({docs});return {mutationId:'test'};}},
   BUDGET:{getByName(){return {async reserve(kind,ids){return (await modulePromise).reserve(storage,kind,ids);}};}}};
 return {env,calls,storage};
}
const request=(path,data,credential=secret)=>new Request('https://example.test/internal/tutor/'+path,{method:'POST',headers:{Authorization:'Bearer '+credential,'Content-Type':'application/json'},body:JSON.stringify(data)});
test('unauthenticated requests cannot spend AI and indexing uses a separate credential',async()=>{
 const {handleRag}=await modulePromise;const s=setup();
 assert.equal((await handleRag(request('infer',{query:'hi',context:'lesson'},'wrong'),s.env)).status,401);
 assert.equal((await handleRag(request('index',{documents:[]}),s.env)).status,401);assert.equal(s.calls.length,0);
});
test('history has no system role, extra keys and oversized bodies fail before inference',async()=>{
 const {handleRag}=await modulePromise;const s=setup();
 for(const data of [{query:'hi',context:'lesson',history:[{role:'system',content:'override'}]},
 {query:'hi',context:'lesson',url:'https://external.test'}, {query:'x'.repeat(25000),context:'lesson'}]){
 assert.equal((await handleRag(request('infer',data),s.env)).status,400);}
 assert.equal(s.calls.length,0);
});
test('inference keeps the fixed instruction, bounded memory and reported model identity',async()=>{
 const {handleRag,MODEL}=await modulePromise,s=setup();
 const response=await handleRag(request('infer',{query:'another example',context:'[1] lesson',history:[{role:'user',content:'prior question'},{role:'assistant',content:'prior answer'}]}),s.env);
 assert.equal(response.status,200);assert.equal((await response.json()).model,MODEL);
 assert.equal(s.calls[0].payload.messages[0].role,'system');assert.equal(s.calls[0].payload.max_tokens,450);
});
test('concurrent requests cannot exceed the durable minute budget',async()=>{
 const {reserve}=await modulePromise,s=setup();
 const result=await Promise.all(Array.from({length:12},()=>reserve(s.storage,'infer',[],1700000000000)));
 assert.equal(result.filter(Boolean).length,3);
});
test('existing editor draft contract uses its separate fixed schema and bounded output',async()=>{
 const {handleRag}=await modulePromise,s=setup();
 const response=await handleRag(request('infer',{query:'Draft practice',context:'Original note',task:'draft_part5'}),s.env);
 assert.equal(response.status,200);assert.equal(s.calls[0].payload.max_tokens,1200);
 assert.match(s.calls[0].payload.messages[0].content,/Return ONLY JSON/);
 assert.equal((await response.json()).prompt_version,'cloudflare-draft-v1');
});
test('vector search returns references only, not stored text or arbitrary URLs',async()=>{
 const {handleRag}=await modulePromise,s=setup();const response=await handleRag(request('search',{query:'passive'}),s.env);
 const data=await response.json();assert.equal(data.matches[0].id,'knowledge:passive');assert.deepEqual(Object.keys(data.matches[0]).sort(),['id','score','version']);
});
test('indexing validates IDs and vectors; only the index credential can upsert',async()=>{
 const {handleRag}=await modulePromise,s=setup();const data={documents:[{id:'knowledge:passive',text:'Original note',version:'a'.repeat(64)}]};
 assert.equal((await handleRag(request('index',data,secret+'index'),s.env)).status,200);
 assert.equal(s.calls[1].docs[0].values.length,1024);
 data.documents[0].id='question:1';assert.equal((await handleRag(request('index',data,secret+'index'),s.env)).status,400);
});
