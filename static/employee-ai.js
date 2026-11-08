import {PendingOperation} from './pending-operation.js';
const $=id=>document.getElementById(id),features={CLEANUP:'AI 상담 정리',SUMMARY:'상담 요약',NEXT_QUESTIONS:'다음 질문 제안'},active=new Set(['RESERVED','RUNNING','UNKNOWN']);
const el=(tag,value)=>{const node=document.createElement(tag);if(value!==undefined)node.textContent=value;return node;};
export class EmployeeAI {
  constructor({userId,request,queue,flush,notice,changed,labels,display,validate}){
    Object.assign(this,{userId,request,queue,flush,notice,changed,labels,display,validate});this.busy=false;this.availability=null;this.result=null;this.sequence=0;
    this.pending=new PendingOperation('employee-ai',userId,/^\/api\/ai\/customer-tasks$/,request);this.storageKey=`tm:ai:task:v1:${userId}`;
    try{const data=JSON.parse(sessionStorage.getItem(this.storageKey));if(data&&/^[0-9a-f-]{36}$/.test(data.task_id)&&features[data.feature])this.value=data;}catch{}
    $('ai-retry').onclick=()=>this.run();$('ai-discard').onclick=()=>{if(confirm('AI 요청의 대기 정보만 폐기하시겠습니까? 이미 접수된 작업과 사용 횟수는 취소되지 않습니다.')){this.pending.clear();this.update();}};
    $('ai-task-open').onclick=()=>this.viewTask();$('ai-apply').onclick=()=>this.apply();$('ai-dialog').addEventListener('close',()=>{this.sequence++;this.stop();});
    document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'){this.poll();this.refreshAvailability();}else this.stop();});
    window.addEventListener('online',()=>{this.poll();this.refreshAvailability();});window.addEventListener('focus',()=>{this.poll();this.refreshAvailability();});this.update();
  }
  track(data){this.value={task_id:data.task_id||data.id,customer_id:data.customer_id,assignment_id:data.assignment_id,feature:data.feature,status:data.status,result_id:data.result_id||null};try{sessionStorage.setItem(this.storageKey,JSON.stringify(this.value));}catch{}}
  async refreshAvailability(){
    if(this.queue.paused)return;if(this.availabilityLoading)return this.availabilityLoading;
    this.availabilityLoading=(async()=>{try{const data=await this.request('/api/ai/availability');if(!this.queue.paused)this.availability=data;}catch(error){this.notice(error.message);}this.update();})();
    try{await this.availabilityLoading;}finally{this.availabilityLoading=null;}
  }
  canGenerate(){return !!this.availability?.generation_available&&!this.busy&&!this.pending.value&&!this.queue.paused&&!active.has(this.value?.status);}
  update(){
    const data=this.availability,server=data?.server_limit;$('ai-usage').textContent=data?`AI 하루 합산 · 성공 ${data.successful_count??0}회 · 예약 ${data.reserved_count??0}회 · 남은 ${data.remaining_count??0}회 / ${data.daily_limit??40}회${server?` · 서버 공용 남은 ${server.remaining_count}회 / ${server.daily_limit}회 (대기·진행 포함)` :''}`: 'AI 사용 가능 여부 확인 중';
    $('ai-availability').textContent=data?data.message:'';$('ai-task-open').hidden=!this.value;$('ai-pending').hidden=!this.pending.value||this.queue.paused;
    for(const id of ['ai-retry','ai-discard'])$(id).disabled=this.busy;this.syncApply();this.changed();
  }
  stop(){clearTimeout(this.timer);this.timer=null;}
  hidePrivate(){this.stop();this.sequence++;this.result=null;$('ai-content').replaceChildren();$('ai-history').replaceChildren();if($('ai-dialog').open)$('ai-dialog').close();$('ai-pending').hidden=true;}
  accessError(error){if(!['ASSIGNMENT_CHANGED','CUSTOMER_DELETED','SITE_DELETED','FORBIDDEN'].includes(error.code))return false;if(this.value)this.track({...this.value,status:'UNAVAILABLE'});this.hidePrivate();this.notice(error.message);return true;}
  clear(){this.pending.clear();this.update();}
  show(mode){this.sequence++;this.mode=mode;this.result=null;$('ai-content').replaceChildren();$('ai-history').replaceChildren();$('ai-apply').hidden=true;$('ai-result-message').textContent='';if(!$('ai-dialog').open)$('ai-dialog').showModal();this.stop();}
  async run(id,feature){
    if(this.busy||this.queue.paused)return false;this.busy=true;this.update();
    try{
      let value;
      if(id){
        if(this.pending.value)throw new Error('먼저 이전 AI 요청의 접수 결과를 확인해 주세요.');
        if(!await this.flush(id))throw new Error('해당 행을 저장하지 못했습니다. AI 요청은 접수하지 않았습니다.');
        const row=this.queue.rows.get(id);if(!row)throw new Error('현재 고객정보를 다시 확인해 주세요.');
        value={endpoint:'/api/ai/customer-tasks',body:{feature,customer_id:id,assignment_id:row.assignment_id,expected_version:row.version,idempotency_key:crypto.randomUUID()}};
      }
      const data=await this.pending.execute(value);if(this.queue.paused)return false;this.track(data);this.show('task');this.busy=false;this.update();await this.poll();return true;
    }catch(error){this.notice(error.message);return false;}
    finally{this.busy=false;this.update();await this.refreshAvailability();}
  }
  viewTask(){if(!this.value||this.queue.paused)return;this.show('task');this.poll();}
  async poll(){
    this.stop();if(this.polling||this.mode!=='task'||!$('ai-dialog').open||document.visibilityState!=='visible'||!navigator.onLine||this.queue.paused||!this.value)return;
    const sequence=this.sequence;this.polling=true;
    try{
      const data=await this.request(`/api/ai/tasks/${this.value.task_id}`);this.track(data);
      if(sequence!==this.sequence||!$('ai-dialog').open||this.queue.paused)return;
      const messages={RESERVED:'AI 작업을 접수했습니다.',RUNNING:'AI 작업을 처리하고 있습니다.',UNKNOWN:'전송 결과가 미확인 상태입니다. 자동으로 다시 생성하지 않습니다. 최대 10분 동안 확인합니다.',FAILED:'AI 작업이 실패했습니다. 횟수 예약은 반환되며 발생 비용은 별도로 기록됩니다.',CANCELLED:'권한 변경 또는 원본 삭제로 작업이 취소되었습니다.'};
      $('ai-result-message').textContent=data.message||messages[data.status]||'';
      if(data.status==='SUCCEEDED'&&data.result_id)await this.loadResult(data.result_id,sequence);
      if(!active.has(data.status))await this.refreshAvailability();
    }catch(error){if(!this.accessError(error)&&!this.queue.paused)$('ai-result-message').textContent=error.message;}
    finally{this.polling=false;if(sequence===this.sequence&&active.has(this.value?.status)&&$('ai-dialog').open&&document.visibilityState==='visible'&&!this.queue.paused)this.timer=setTimeout(()=>this.poll(),3000);}
  }
  async history(id){
    if(this.busy||this.queue.paused)return;this.busy=true;this.update();this.show('history');const sequence=this.sequence;
    try{
      const row=this.queue.rows.get(id);if(!row)throw new Error('현재 고객정보를 다시 확인해 주세요.');
      const data=await this.request('/api/ai/customer-results?'+new URLSearchParams({customer_id:id,assignment_id:row.assignment_id}));
      if(sequence!==this.sequence||this.queue.paused)return;$('ai-result-message').textContent=data.items.length?'조회할 결과를 선택하세요.':'저장된 AI 결과가 없습니다.';
      $('ai-history').replaceChildren(...data.items.map(item=>{const button=el('button',`${features[item.feature]} · ${new Date(item.created_at).toLocaleString('ko-KR')}${item.is_test?' · 테스트 전용':''}`);button.className='btn btn-outline-secondary';button.onclick=()=>{this.sequence++;this.mode='result';this.loadResult(item.result_id,this.sequence).catch(error=>this.notice(error.message));};return button;}));
    }catch(error){if(!this.queue.paused)$('ai-result-message').textContent=error.message;}
    finally{this.busy=false;this.update();}
  }
  async loadResult(id,sequence=this.sequence){
    let data;try{data=await this.request(`/api/ai/results/${id}`);}catch(error){if(!this.accessError(error))throw error;return;}if(sequence!==this.sequence||this.queue.paused||!$('ai-dialog').open)return;this.result=data;this.drawResult();
  }
  drawResult(){
    const data=this.result,body=$('ai-content');body.replaceChildren();$('ai-apply').hidden=true;
    $('ai-result-message').textContent=!data.available?data.message||'제공할 수 없는 결과입니다.':data.stale?'오래된 결과입니다. 최신 값과 비교해 일반 편집으로 반영하세요.': 'AI 결과는 자동 저장되지 않습니다.';
    if(!data.available)return;
    if(data.is_test){const warning=el('p','테스트 전용 가짜 응답 · 운영 상담 분석 결과가 아닙니다.');warning.className='alert alert-warning';body.append(warning);}
    body.append(el('h3',features[data.feature]+(data.customer_name?' · '+data.customer_name:'')),el('p',`생성 ${new Date(data.generated_at).toLocaleString('ko-KR')} · 고객 버전 ${data.source_customer_version} · 기준일 ${data.korean_date}`));
    const payload=data.payload;
    for(const message of payload.limitations||[])body.append(el('p',message));
    if(data.schema_version!=='employee-v1'){body.append(el('p','이전 형식의 결과는 선택 적용할 수 없습니다.'));return;}
    if(data.feature==='CLEANUP'){
      const row=this.queue.rows.get(data.customer_id),scroll=el('div'),table=el('table'),head=el('thead'),tr=el('tr'),tbody=el('tbody');scroll.className='ai-compare-scroll';table.className='table ai-compare';
      for(const label of ['선택','항목','현재 저장값','제안·근거'])tr.append(el('th',label));head.append(tr);
      for(const field of ['notes','call_result','visit_at','callback_due_at','housing_status','contract_status']){const item=payload.suggestions[field];
        const line=el('tr'),select=el('td'),checkbox=el('input');checkbox.type='checkbox';checkbox.dataset.aiField=field;checkbox.setAttribute('aria-label',this.labels[field]+' 제안 선택');checkbox.checked=false;checkbox.onchange=()=>this.syncApply();
        checkbox.disabled=item.status!=='SUGGESTION';select.append(checkbox);const content=el('td');content.append(el('p',item.status==='SUGGESTION'?this.display(field,item.value):'추천 없음 · 기존 값 유지'),el('p',item.reason||''));
        if(item.evidence)content.append(el('blockquote',item.evidence));if(item.source_ids?.length)content.append(el('small',`저장된 상담 근거 ${item.source_ids.length}건`));
        line.append(select,el('th',this.labels[field]),el('td',this.display(field,row?.[field])),content);tbody.append(line);
      }
      table.append(head,tbody);scroll.append(table);body.append(scroll);$('ai-apply').hidden=false;
    }else if(data.feature==='SUMMARY'){
      for(const [field,label] of [['key_points','상담 핵심'],['concerns','관심·우려'],['promises','약속한 후속 조치'],['checks','이번 확인 사항']]){
        body.append(el('h4',label));if(!payload[field].length)body.append(el('p','근거가 부족합니다.'));
        for(const item of payload[field])this.addEvidence(body,item.text,item);
      }
    }else for(const item of payload.questions)this.addEvidence(body,item.question+' · 목적: '+item.purpose,item);
    this.syncApply();
  }
  addEvidence(parent,caption,item){const box=el('section');box.append(el('p',caption),el('blockquote',item.evidence),el('small',`저장된 상담 근거 ${item.source_ids.length}건`));parent.append(box);}
  safeToApply(){const data=this.result,row=data&&this.queue.rows.get(data.customer_id);return !!data?.available&&data.feature==='CLEANUP'&&data.schema_version==='employee-v1'&&!data.stale&&!this.queue.paused&&!!row&&row.version===data.source_customer_version&&row.assignment_id===data.assignment_id&&!this.queue.entry(row.id)&&!this.queue.invalidRow(row.id);}
  syncApply(){
    const safe=this.safeToApply()&&!this.busy;
    for(const checkbox of document.querySelectorAll('[data-ai-field]'))checkbox.disabled=!safe||this.result?.payload.suggestions[checkbox.dataset.aiField].status!=='SUGGESTION';
    $('ai-apply').disabled=!safe||!document.querySelector('[data-ai-field]:checked');
  }
  async apply(){
    if(!this.safeToApply()||this.busy)return;const selected=[...document.querySelectorAll('[data-ai-field]:checked')].map(input=>input.dataset.aiField);if(!selected.length)return;
    this.busy=true;this.update();
    try{
      const latest=await this.request(`/api/ai/results/${this.result.id}`);this.result=latest;
      if(!this.safeToApply())throw new Error('결과가 오래되었거나 미저장 변경이 있습니다. 최신 값과 비교해 주세요.');
      if(selected.includes('notes')&&!confirm('위의 현재 비고와 제안문을 비교하셨나요? 선택한 비고를 AI 제안으로 교체해 저장 대기열에 반영합니다.'))return;
      const row=this.queue.rows.get(latest.customer_id),values={};for(const field of selected){const item=latest.payload.suggestions[field];if(item?.status!=='SUGGESTION'||item.value===null)throw new Error('적용할 수 없는 제안입니다.');this.validate(field,item.value,row);values[field]=item.value;}
      if(!this.queue.stageAI(row,values,latest.id))throw new Error('저장 대기값을 먼저 확인해 주세요.');
      const message=this.queue.entry(row.id)?'선택 항목을 저장 대기열에 반영했습니다. 지금 저장하거나 자동 저장 결과를 확인하세요.':'선택한 값이 기존 값과 같아 저장할 변경이 없습니다.';$('ai-result-message').textContent=message;this.notice(message);
    }catch(error){if(!this.accessError(error)){this.notice(error.message);$('ai-result-message').textContent=error.message;}}
    finally{this.busy=false;this.update();}
  }
}
