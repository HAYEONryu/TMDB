import {newRequestId} from './request-id.js';
import {employeeSupportError,lockSupportError} from './browser-environment.js';
import {QueueStore} from './employee-store.js';

export const fields=['customer_name','call_result','visit_at','contract_status','notes','callback_due_at','housing_status','residence','route','memo'];
const blocked=new Set(['ASSIGNMENT_CHANGED','CUSTOMER_DELETED','SITE_DELETED','FORBIDDEN']);
const auth=new Set(['UNAUTHENTICATED','ACCOUNT_DISABLED','SESSION_INVALID','PASSWORD_CHANGE_REQUIRED','QUEUE_CONTEXT_MISMATCH','PASSWORD_CHANGE_NEEDED']);
const day=86400000;
export function normalized(field,value){
  if(['visit_at','callback_due_at'].includes(field)){
    if(!value)return null;
    const input=/Z$|[+-]\d\d:\d\d$/.test(value)?value:value+'+09:00',date=new Date(input);
    if(!Number.isFinite(date.getTime())||date.getUTCFullYear()<1||date.getUTCFullYear()>9999)throw new Error('유효한 날짜와 시간을 입력해 주세요.');
    return date.toISOString();
  }
  if(field==='call_result')return value||null;
  if(field==='contract_status')return value||'UNKNOWN';
  if(['customer_name','housing_status','residence','route'].includes(field))return (value||'').trim();
  return (value||'').replace(/\r\n?/g,'\n');
}
export const changes=entry=>({...entry.inflight?.changes,...entry.pending});
const has=entry=>!!entry.inflight||Object.keys(entry.pending).length>0;
export class EmployeeQueue extends EventTarget {
  constructor(userId,request,{store=null,now=()=>Date.now(),target=90000}={}){
    super();this.userId=userId;this.request=request;this.store=store;this.now=now;this.target=target;this.entries=new Map();this.rows=new Map();this.releases=new Map();this.invalid=new Map();this.disk=Promise.resolve();this.paused=false;this.otherTabs=0;this.recoveryErrors=0;this.generation=0;
  }
  emit(){this.dispatchEvent(new Event('change'));}
  all(){return [...this.entries.values()];}
  entry(id){return this.all().find(item=>item.customer_id===id);}
  async claim(key){
    const problem=lockSupportError();if(problem)throw problem;
    return new Promise((resolve,reject)=>{navigator.locks.request('tm-entry:'+key,{ifAvailable:true},async lock=>{
      if(!lock){resolve(false);return;}
      await new Promise(release=>{this.releases.set(key,release);resolve(true);});
    }).catch(reject);});
  }
  async start(context){
    const problem=employeeSupportError();
    if(problem){context.key=null;this.storageError=problem.message;this.pause(problem.message);return false;}
    this.target=context.target_ms;
    try{
      this.store=this.store||new QueueStore(this.userId,context.key);context.key=null;await this.store.open();
      for(const record of await this.store.list()){
        if(!await this.claim(record.key)){this.otherTabs++;continue;}
        try{const entry=await this.store.read(record);entry.stored=true;entry.state='checking';this.entries.set(entry.key,entry);}
        catch{this.recoveryErrors++;this.releases.get(record.key)?.();this.releases.delete(record.key);}
      }
    }catch(error){
      this.storageError=error.message;
      if(!this.store?.db||error.name==='SecurityError'){
        this.storageError='브라우저 보관소를 열 수 없습니다. 사이트 저장 권한과 브라우저 설정을 확인해 주세요.';
        this.store?.close();this.pause(this.storageError);return false;
      }
    }
    await this.reconcile(this.all());this.emit();this.timer=setInterval(()=>this.tick(),1000);
  }
  persist(entry,remove=false){
    const snapshot=structuredClone(entry),generation=++this.generation;
    const operation=this.disk.then(async()=>{
      // An online recheck may finish while removal is queued. A discarded lane
      // must not be written back after its record and in-memory entry are gone.
      if(!remove&&this.entries.get(snapshot.key)!==entry)return true;
      try{if(!this.store?.db)throw new Error('브라우저 보관소를 사용할 수 없습니다.');await (remove?this.store.remove(snapshot.key):this.store.put(snapshot));entry.stored=!remove;if(generation===this.generation)this.storageError=null;return true;}
      catch(error){this.storageError='로컬 임시 보관 실패: '+error.message;entry.unsafe=true;return remove&&!entry.stored;}
    });
    this.disk=operation.then(()=>{});return operation;
  }
  async clear(entry){
    const revision=entry.editSeq||0;entry.state='clearing';const removed=await this.persist(entry,true);
    if((entry.editSeq||0)!==revision){this.emit();return false;}
    if(!removed){entry.state='failed';entry.error='로컬 대기 기록을 지우지 못했습니다. 보관소를 복구한 뒤 다시 확인해 주세요.';this.entries.set(entry.key,entry);}
    else{this.entries.delete(entry.key);this.releases.get(entry.key)?.();this.releases.delete(entry.key);}this.emit();return removed;
  }
  setRows(rows){for(const row of rows){if(this.rows.get(row.id)?.version>row.version)continue;const entry=this.entry(row.id);if(entry&&(row.version!==entry.version||row.assignment_id!==entry.assignment_id)){entry.state=row.assignment_id!==entry.assignment_id?'blocked':'conflict';entry.server=entry.state==='blocked'?null:row;entry.error='복구 확인 이후 서버 정보가 변경되었습니다.';this.persist(entry);}else this.rows.set(row.id,structuredClone(row));}}
  canEdit(row){const e=this.entry(row.id);return !this.paused&&(!e||!['blocked','conflict','review','checking','failed'].includes(e.state))&&(!e||e.assignment_id===row.assignment_id);}
  stage(row,field,value){
    if(!fields.includes(field)||!this.canEdit(row))return false;
    const baseline=this.rows.get(row.id)||row;let entry=this.entry(row.id);
    const actual=normalized(field,value),expected=normalized(field,entry?.inflight&&Object.hasOwn(entry.inflight.changes,field)?entry.inflight.changes[field]:baseline[field]);
    if(!entry&&actual===expected)return true;
    if(!entry){
      const key=[this.userId,row.site_id,row.id,row.assignment_id,newRequestId()].join(':');
      entry={key,user_id:this.userId,site_id:baseline.site_id,customer_id:row.id,assignment_id:baseline.assignment_id,version:baseline.version,pending:{},inflight:null,first_dirty_at:this.now(),pending_since:this.now(),created_at:this.now(),state:'dirty',error:'',retry_at:0,attempt:0};
      this.entries.set(key,entry);this.claim(key).catch(error=>{this.storageError=error.message;this.emit();});
    }
    entry.editSeq=(entry.editSeq||0)+1;
    if(entry.ai_fields){delete entry.ai_fields[field];if(!Object.keys(entry.ai_fields).length)entry.ai_source_id=null;}
    if(actual===expected)delete entry.pending[field];else entry.pending[field]=actual;
    if(Object.keys(entry.pending).length&&!entry.pending_since)entry.pending_since=this.now();
    if(!has(entry)){this.clear(entry);return true;}
    if(entry.state!=='saving'){entry.state=navigator.onLine?'dirty':'offline';entry.error='';}
    this.persist(entry).then(()=>{if(entry.unsafe&&!this.saving)this.flush(true);});this.emit();return true;
  }
  stageAI(row,values,resultId){
    const baseline=this.rows.get(row.id);if(this.paused||!baseline||this.entry(row.id)||this.invalidRow(row.id)||baseline.version!==row.version||baseline.assignment_id!==row.assignment_id)return false;
    const pending={};for(const [field,value] of Object.entries(values)){if(!fields.includes(field))return false;const actual=normalized(field,value);if(actual!==normalized(field,baseline[field]))pending[field]=actual;}
    if(!Object.keys(pending).length)return true;
    const key=[this.userId,row.site_id,row.id,row.assignment_id,newRequestId()].join(':'),entry={key,user_id:this.userId,site_id:baseline.site_id,customer_id:row.id,assignment_id:baseline.assignment_id,version:baseline.version,pending,inflight:null,first_dirty_at:this.now(),pending_since:this.now(),created_at:this.now(),state:navigator.onLine?'dirty':'offline',error:'',retry_at:0,attempt:0,ai_source_id:resultId,ai_fields:Object.fromEntries(Object.keys(pending).map(field=>[field,true]))};
    this.entries.set(key,entry);this.claim(key).catch(error=>{this.storageError=error.message;this.emit();});
    this.persist(entry).then(()=>{if(entry.unsafe&&!this.saving)this.flush(true);});this.emit();return true;
  }
  markInvalid(id,field,message){const key=id+':'+field;if(message)this.invalid.set(key,message);else this.invalid.delete(key);this.emit();}
  invalidRow(id){return [...this.invalid.keys()].some(key=>key.startsWith(id+':'));}
  pause(message){this.paused=true;this.pauseMessage=message;this.emit();}
  query(entry){return {key:entry.key,site_id:entry.site_id,customer_id:entry.customer_id,assignment_id:entry.assignment_id,expected_version:entry.version,...(entry.inflight?{inflight:entry.inflight}:{})};}
  async ack(entry,result,latest){
    if(result.ok){
      const row=result.row;this.rows.set(entry.customer_id,structuredClone(row));entry.version=result.version;entry.inflight=null;entry.attempt=0;entry.retry_at=0;entry.error='';
      for(const [field,value] of Object.entries(entry.pending))if(normalized(field,value)===normalized(field,row[field]))delete entry.pending[field];
      if(!has(entry)){if(latest)this.rows.set(entry.customer_id,latest);await this.clear(entry);return;}
      if(latest&&latest.version!==result.version){entry.state='conflict';entry.server=latest;entry.error='서버에 다른 변경이 있습니다.';}
      else entry.state='dirty';
    }else{
      const code=result.error?.code;entry.error=result.error?.message||'저장 실패';
      entry.state=blocked.has(code)?'blocked':['VERSION_CONFLICT','AI_RESULT_STALE'].includes(code)?'conflict':'failed';entry.server=blocked.has(code)?null:result.server_row||latest;
      if(auth.has(code))this.pause(entry.error);
    }
    await this.persist(entry);this.emit();
  }
  async reconcile(entries){
    if(!entries.length||this.paused)return;
    for(let start=0;start<entries.length;start+=100){
      const batch=entries.slice(start,start+100);for(const entry of batch)entry.checked=false;
      try{
        const result=await this.request('/api/employee/queue-check',{entries:batch.map(e=>this.query(e))});
        for(const item of result.results){
          const entry=this.entries.get(item.key);if(!entry)continue;entry.checked=true;
          if(blocked.has(item.code)){entry.state='blocked';entry.error='회수·재분배·삭제로 전송할 수 없습니다.';entry.server=null;}
          else if(item.code==='RECEIPT'){await this.ack(entry,item.receipt,item.server_row);continue;}
          else if(item.code!=='READY'){entry.state='conflict';entry.error='서버 값이 바뀌었습니다. 비교 후 선택해 주세요.';entry.server=item.server_row;}
          else{
            this.rows.set(entry.customer_id,item.server_row);entry.server=item.server_row;
            if(this.now()-entry.created_at>=7*day){entry.state='review';entry.error='7일이 지난 대기값입니다. 자동 재전송하지 않습니다.';}
            else if(entries.filter(e=>e.customer_id===entry.customer_id).length>1){entry.state='conflict';entry.error='같은 고객의 복구 대기값이 여러 개입니다. 각각 검토해 주세요.';}
            else if(!['failed','review','conflict'].includes(entry.state))entry.state='dirty';
          }
          await this.persist(entry);
        }
      }catch(error){this.fail(batch,error);}
    }
    this.emit();
  }
  fail(entries,error){
    if(error.status===401||auth.has(error.code))this.pause(error.message);
    for(const entry of entries){
      if(!this.entries.has(entry.key))continue;
      const transient=!error.status||error.status===429||error.status>=500;
      entry.state=transient?(navigator.onLine?'retry':'offline'):'failed';entry.error=error.message;
      if(transient){const delay=[2000,5000,15000,30000,60000][Math.min(entry.attempt||0,4)];entry.attempt=(entry.attempt||0)+1;entry.retry_at=this.now()+delay*(0.9+Math.random()*0.1);}
      this.persist(entry);
    }
    this.emit();
  }
  async rowLocks(entries,action){
    const keys=[...new Set(entries.map(e=>'tm-send:'+this.userId+':'+e.customer_id+':'+e.assignment_id))].sort();
    const next=index=>index===keys.length?action():navigator.locks.request(keys[index],()=>next(index+1));return next(0);
  }
  async flush(force=false,onlyId=null){
    const complete=()=>onlyId?!this.entry(onlyId)&&!this.invalidRow(onlyId):!this.entries.size&&!this.invalid.size;
    if(this.saving){await this.saving;if(force&&this.all().some(e=>(!onlyId||e.customer_id===onlyId)&&['dirty','retry','offline'].includes(e.state)))return this.flush(force,onlyId);return complete();}
    if(this.paused||!navigator.onLine){if(!navigator.onLine)for(const e of this.all())if(['dirty','retry','saving'].includes(e.state))e.state='offline';this.emit();return false;}
    const eligible=()=>this.all().filter(e=>(!onlyId||e.customer_id===onlyId)&&['dirty','retry','offline'].includes(e.state)&&!this.invalidRow(e.customer_id)&&(force||((e.retry_at||0)<=this.now()&&(e.inflight||this.now()-e.pending_since>=this.target||e.unsafe))));
    if(!eligible().length)return complete();
    const problem=lockSupportError();if(problem){this.pause(problem.message);return false;}
    this.saving=(async()=>{
      // One customer per batch; distinct abandoned lanes require explicit review.
      for(const batch of this.batches(eligible()))await this.rowLocks(batch,async()=>{
        await this.reconcile(batch);
        const send=batch.filter(e=>e.checked&&this.entries.has(e.key)&&['dirty','retry','offline'].includes(e.state)&&!this.paused&&!this.invalidRow(e.customer_id));
        if(!send.length)return;
        for(const e of send){
          if(!e.inflight){e.inflight={customer_id:e.customer_id,assignment_id:e.assignment_id,mutation_id:newRequestId(),expected_version:e.version,changes:structuredClone(e.pending),...(e.ai_source_id&&Object.keys(e.ai_fields||{}).some(field=>Object.hasOwn(e.pending,field))?{source_ai_result_id:e.ai_source_id}:{})};e.pending={};e.pending_since=null;e.ai_source_id=null;e.ai_fields={};}
          e.state='saving';await this.persist(e);
        }
        this.emit();
        try{
          const response=await this.request('/api/employee/batch-update',{rows:send.map(e=>e.inflight)});
          for(const e of send){const result=response.results.find(r=>r.mutation_id===e.inflight?.mutation_id);if(result)await this.ack(e,result);else this.fail([e],new Error('서버의 저장 확인이 누락되었습니다.'));}
        }catch(error){this.fail(send,error);}
      });
    })();
    try{await this.saving;}finally{this.saving=null;this.emit();}
    if(force&&eligible().some(e=>e.state==='dirty'))return this.flush(force,onlyId);
    return complete();
  }
  batches(entries){const result=[];for(let i=0;i<entries.length;i+=100)result.push(entries.slice(i,i+100));return result;}
  tick(){if(!this.paused&&document.visibilityState==='visible'&&navigator.onLine)this.flush().catch(error=>this.fail(this.all(),error));}
  async resume(){if(this.paused)return;await this.reconcile(this.all());this.tick();}
  async compare(entry){await this.reconcile([entry]);return entry.server;}
  async reapply(entry,seenVersion){
    await this.reconcile([entry]);if(entry.state==='blocked'||!entry.server||this.paused)return false;
    if(entry.server.version!==seenVersion){entry.error='서버 값이 다시 바뀌었습니다. 새 비교 내용을 확인해 주세요.';this.emit();return false;}
    const values=changes(entry);entry.version=seenVersion;entry.inflight=null;entry.pending={};entry.ai_source_id=null;entry.ai_fields={};this.rows.set(entry.customer_id,structuredClone(entry.server));
    for(const [f,v] of Object.entries(values))if(normalized(f,v)!==normalized(f,entry.server[f]))entry.pending[f]=v;
    entry.created_at=this.now();entry.first_dirty_at=this.now();entry.pending_since=this.now();entry.state='dirty';entry.retry_at=0;entry.error='';entry.attempt=0;
    if(!has(entry))await this.clear(entry);else{await this.persist(entry);await this.flush(true);}return !this.entries.has(entry.key);
  }
  async discard(entry){if(this.saving)await this.saving;await this.clear(entry);}
  async discardAll(){if(this.saving)await this.saving;for(const e of this.all())await this.clear(e);this.invalid.clear();}
  stop(){clearInterval(this.timer);for(const release of this.releases.values())release();this.releases.clear();this.store?.close();}
}
