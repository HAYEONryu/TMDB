import test from 'node:test';
import assert from 'node:assert/strict';
import {EmployeeQueue,normalized} from '../static/employee-queue.js';
import {installPreRecall} from '../static/pre-recall.js';
Object.defineProperty(globalThis,'navigator',{value:{onLine:true,locks:{request:async(_key,options,fn)=>(fn||options)({})}},configurable:true});
globalThis.document={visibilityState:'visible'};
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
const row=(id='customer')=>({id,site_id:'site',assignment_id:'assignment-'+id,version:1,notes:'',housing_status:'',call_result:'INTERESTED',visit_at:null,callback_due_at:null,contract_status:'UNKNOWN'});
function fixture(){
  let now=1000;const records=new Map(),sends=[],store={db:true,put:async entry=>records.set(entry.key,structuredClone(entry)),remove:async key=>records.delete(key)};
  const q=new EmployeeQueue('employee',async(url,body)=>{
    if(url.endsWith('queue-check'))return {results:body.entries.map(e=>({key:e.key,code:'READY',server_row:{...q.rows.get(e.customer_id),version:e.expected_version}}))};
    sends.push(structuredClone(body));return {results:body.rows.map(r=>({ok:true,customer_id:r.customer_id,mutation_id:r.mutation_id,version:r.expected_version+1,row:{...q.rows.get(r.customer_id),...r.changes,version:r.expected_version+1}}))};
  },{store,now:()=>now});
  const r=row();q.setRows([r]);return {q,r,records,sends,setNow:n=>{now=n;}};
}

test('AI selection stages one atomic row with provenance and keeps other row deadline',async()=>{
  const {q,r,sends,setNow,records}=fixture(),other=row('other');q.setRows([other]);q.stage(other,'notes','manual');setNow(5000);
  assert.equal(q.stageAI(r,{notes:'AI proposal'},'result-id'),true);await q.disk;assert.equal(records.get(q.entry(r.id).key).ai_source_id,'result-id');
  assert.equal(await q.flush(true,r.id),true);assert.equal(sends[0].rows[0].source_ai_result_id,'result-id');assert.equal(q.entry(other.id).pending_since,1000);
  assert.equal(q.stageAI(q.rows.get(r.id),{notes:'another AI'},'new-result'),true);q.stage(q.rows.get(r.id),'notes','manual override');await q.flush(true,r.id);
  assert.equal(Object.hasOwn(sends[1].rows[0],'source_ai_result_id'),false);
});

test('lost AI save retries exact source ID and body while later manual input stays separate',async()=>{
  const {q,r,sends}=fixture(),request=q.request;let first;let lost=false;
  q.request=async(url,body)=>{if(url.endsWith('batch-update')&&!lost){lost=true;first=structuredClone(body);throw new Error('lost');}return request(url,body);};
  q.stageAI(r,{notes:'AI selected'},'ai-result');await q.flush(true);q.stage(r,'housing_status','가상 월세');await q.flush(true);
  assert.deepEqual(sends[0],first);assert.equal(sends[0].rows[0].source_ai_result_id,'ai-result');assert.equal(Object.hasOwn(sends[1].rows[0],'source_ai_result_id'),false);
});

test('AI stage refuses dirty rows and stale versions without changing their pending data',()=>{
  const {q,r}=fixture();q.stage(r,'notes','manual pending');assert.equal(q.stageAI(r,{notes:'AI'},'id'),false);assert.equal(q.entry(r.id).pending.notes,'manual pending');
  const clean=fixture();assert.equal(clean.q.stageAI({...clean.r,version:99},{notes:'AI'},'id'),false);assert.equal(clean.q.entries.size,0);
});

test('deadline follows first unsent change, coalesces last input, unchanged/reverted sends nothing',async()=>{
  const {q,r,sends,setNow}=fixture();q.stage(r,'notes','');assert.equal(q.entries.size,0);
  q.stage(r,'notes','first');setNow(61000);q.stage(r,'notes','last');assert.equal(q.entry(r.id).pending_since,1000);
  setNow(90999);await q.flush();assert.equal(sends.length,0);setNow(91000);await q.flush();assert.equal(sends.length,1);assert.deepEqual(sends[0].rows[0].changes,{notes:'last'});assert.equal(q.entries.size,0);
  q.stage(q.rows.get(r.id),'notes','other');q.stage(q.rows.get(r.id),'notes','last');await q.disk;await q.flush(true);assert.equal(sends.length,1);assert.equal(q.entries.size,0);
});

test('inflight snapshot and later input stay separate, acknowledgement advances pending base',async()=>{
  const {q,r,sends}=fixture(),hold=deferred(),entered=deferred(),request=q.request;
  q.request=async(url,body)=>{if(url.endsWith('batch-update')&&sends.length===0){entered.resolve();await hold.promise;}return request(url,body);};
  q.stage(r,'notes','first');const sending=q.flush(); // Not due yet.
  await sending;const first=q.flush(true);await entered.promise;
  const mid=q.entry(r.id).inflight.mutation_id;q.stage(r,'notes','later');assert.equal(q.entry(r.id).inflight.changes.notes,'first');assert.equal(q.entry(r.id).pending.notes,'later');
  hold.resolve();await first;assert.equal(sends.length,2);assert.equal(sends[0].rows[0].mutation_id,mid);assert.equal(sends[1].rows[0].expected_version,2);assert.notEqual(sends[1].rows[0].mutation_id,mid);assert.equal(q.rows.get(r.id).notes,'later');
});

test('null inflight field is effective base; reverting before acknowledgement queues real reversal',async()=>{
  const {q,r}=fixture(),hold=deferred(),entered=deferred(),request=q.request;
  q.request=async(url,body)=>{if(url.endsWith('batch-update')){entered.resolve();await hold.promise;}return request(url,body);};
  q.stage(r,'call_result',null);const sending=q.flush(true);await entered.promise;
  q.stage(r,'call_result','INTERESTED');assert.deepEqual(q.entry(r.id).pending,{call_result:'INTERESTED'});hold.resolve();await sending;assert.equal(q.rows.get(r.id).call_result,'INTERESTED');
});

test('lost response retry preserves mutation body and later pending input',async()=>{
  const {q,r,sends}=fixture(),request=q.request;let failed=false;let captured;
  q.request=async(url,body)=>{if(url.endsWith('batch-update')&&!failed){captured=structuredClone(body);failed=true;throw new Error('response lost');}return request(url,body);};
  q.stage(r,'notes','snapshot');await q.flush(true);assert.equal(q.entry(r.id).state,'retry');q.stage(r,'housing_status','가상 월세');await q.flush(true);
  assert.deepEqual(sends[0],captured);assert.deepEqual(sends[1].rows[0].changes,{housing_status:'가상 월세'});assert.equal(sends[1].rows[0].expected_version,2);
});

test('failed authority check never sends and never replaces assignment ID',async()=>{
  const {q,r,sends}=fixture();q.stage(r,'notes','old assignment');q.request=async()=>({results:[{key:q.entry(r.id).key,code:'ASSIGNMENT_CHANGED'}]});
  assert.equal(await q.flush(true),false);assert.equal(sends.length,0);assert.equal(q.entry(r.id).state,'blocked');assert.equal(q.entry(r.id).assignment_id,r.assignment_id);
});

test('unavailable queue-check prevents write; auth error stops automatic retries',async()=>{
  const {q,r,sends}=fixture();q.stage(r,'notes','held');let calls=0;q.request=async()=>{calls++;throw Object.assign(new Error('expired'),{status:401,code:'UNAUTHENTICATED'});};
  await q.flush(true);await q.flush(true);assert.equal(calls,1);assert.equal(sends.length,0);assert.equal(q.paused,true);assert.equal(q.entry(r.id).inflight,null);
});

test('7-day old queue requires manual review; cannot silently rebase a newer server version',async()=>{
  const {q,r,sends,setNow}=fixture();q.stage(r,'notes','old');setNow(8*86400000);await q.flush(true);assert.equal(q.entry(r.id).state,'review');assert.equal(sends.length,0);
  q.request=async()=>({results:[{key:q.entry(r.id).key,code:'VERSION_CONFLICT',server_row:{...r,notes:'new server',version:3}}]});
  assert.equal(await q.reapply(q.entry(r.id),2),false);assert.equal(q.entry(r.id).version,1);assert.equal(q.entry(r.id).server.version,3);
});

test('batches stop at 100 rows and a rejected row does not remove successful rows or itself',async()=>{
  const {q,sends}=fixture();const rows=Array.from({length:101},(_,i)=>row('c'+i));q.setRows(rows);for(const r of rows)q.stage(r,'notes','fake '+r.id);
  const request=q.request;q.request=async(url,body)=>{const data=await request(url,body);if(url.endsWith('batch-update'))data.results=data.results.map(r=>r.customer_id==='c2'?{...r,ok:false,error:{code:'VALIDATION_ERROR',message:'bad row'}}:r);return data;};
  await q.flush(true);assert.deepEqual(sends.map(s=>s.rows.length),[100,1]);assert.equal(q.entries.size,1);assert.equal(q.entry('c2').state,'failed');assert.ok(q.entry('c2').inflight);
});

test('local removal failure retains queue and warns; new input during cleanup survives',async()=>{
  const {q,r,records}=fixture();q.stage(r,'notes','first');await q.disk;q.entry(r.id).stored=true;
  const remove=q.store.remove;q.store.remove=async()=>{throw new Error('storage denied');};await q.discard(q.entry(r.id));assert.equal(q.entries.size,1);assert.equal(q.entry(r.id).state,'failed');assert.equal(records.size,1);
  q.store.remove=remove;await q.discard(q.entry(r.id));assert.equal(q.entries.size,0);
  const entered=deferred(),hold=deferred();q.store.remove=async key=>{entered.resolve();await hold.promise;return remove(key);};
  q.stage(r,'notes','again');q.stage(r,'notes','');await entered.promise;q.stage(r,'notes','latest');hold.resolve();await q.disk;assert.equal(q.entries.size,1);assert.equal(q.entry(r.id).pending.notes,'latest');assert.equal(records.size,1);
});

test('a concurrent server recheck cannot recreate a discarded local record',async()=>{
  const {q,r,records}=fixture();q.stage(r,'notes','discard this');await q.disk;
  const entry=q.entry(r.id),entered=deferred(),release=deferred(),lateWrite=deferred();
  const remove=q.store.remove;q.store.remove=async key=>{entered.resolve();await release.promise;return remove(key);};
  const persist=q.persist.bind(q);q.persist=(e,removing=false)=>{const result=persist(e,removing);if(!removing)lateWrite.resolve();return result;};
  const clearing=q.discardAll();await entered.promise;
  const rechecking=q.reconcile([entry]);await lateWrite.promise;release.resolve();
  await Promise.all([clearing,rechecking]);await q.disk;
  assert.equal(q.entries.size,0);assert.equal(records.size,0);
});

test('normalization preserves notes whitespace, trims housing, interprets KST, rejects impossible dates',()=>{
  assert.equal(normalized('notes',' a\r\nb '),' a\nb ');assert.equal(normalized('housing_status',' 가상 자가 '),'가상 자가');assert.equal(normalized('visit_at','2026-11-04T09:30'),'2026-11-04T00:30:00.000Z');assert.throws(()=>normalized('visit_at','bad date'));
});

test('transient backoff is bounded at 2,5,15,30,60 seconds including jitter',()=>{
  const {q,r,setNow}=fixture();q.stage(r,'notes','temporary');const entry=q.entry(r.id);setNow(100000);const random=Math.random;Math.random=()=>1;
  try{for(const delay of [2000,5000,15000,30000,60000,60000,60000]){q.fail([entry],new Error('temporary'));assert.equal(entry.retry_at,100000+delay);}}finally{Math.random=random;}
});

test('row action flush preserves another row and its first-dirty timer',async()=>{
  const {q,r,sends,setNow}=fixture(),other=row('other');q.setRows([other]);q.stage(r,'notes','target');setNow(5000);q.stage(other,'notes','later');
  assert.equal(await q.flush(true,r.id),true);assert.equal(sends.length,1);assert.equal(sends[0].rows.length,1);assert.equal(q.entry(other.id).pending_since,5000);assert.equal(q.entries.size,1);
});

test('an older list response cannot replace the baseline acknowledged by row action',async()=>{
  const {q,r}=fixture();q.stage(r,'notes','acknowledged');await q.flush(true,r.id);q.setRows([r]);assert.equal(q.rows.get(r.id).version,2);assert.equal(q.rows.get(r.id).notes,'acknowledged');
  q.stage(r,'housing_status','가상 자가');assert.equal(q.entry(r.id).version,2);
});

test('22:59:30 KST commits editor and flushes once; online retry works before cutoff',async context=>{
  const previous=document;globalThis.document=new EventTarget();document.visibilityState='visible';globalThis.window=new EventTarget();
  let now=Date.parse('2026-11-04T13:59:29Z'),commits=0,flushes=0;
  context.mock.timers.enable({apis:['setInterval']});const stop=installPreRecall({serverTime:new Date(now).toISOString(),now:()=>now,commit:()=>commits++,flush:async()=>{flushes++;return true;},notice:()=>{}});
  now+=1000;context.mock.timers.tick(1000);await Promise.resolve();assert.equal(flushes,1);context.mock.timers.tick(10000);assert.equal(commits,1);
  window.dispatchEvent(new Event('online'));await Promise.resolve();assert.equal(flushes,2);now=Date.parse('2026-11-04T14:00:00Z');window.dispatchEvent(new Event('online'));assert.equal(flushes,2);stop();context.mock.timers.reset();globalThis.document=previous;
});

test('queue recovery delay does not shift the server clock used before recall',async context=>{
  const previous=document;globalThis.document=new EventTarget();document.visibilityState='visible';globalThis.window=new EventTarget();context.mock.timers.enable({apis:['setInterval']});
  const receivedAt=Date.parse('2026-11-04T13:59:00Z');let flushes=0;
  const stop=installPreRecall({serverTime:new Date(receivedAt).toISOString(),receivedAt,now:()=>receivedAt+31000,commit:()=>{},flush:async()=>{flushes++;return true;},notice:()=>{}});
  await Promise.resolve();assert.equal(flushes,1);stop();context.mock.timers.reset();globalThis.document=previous;
});
