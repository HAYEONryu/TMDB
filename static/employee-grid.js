import {EmployeeQueue,changes,normalized} from './employee-queue.js';
import {employeeSupportError} from './browser-environment.js';
import {withRequestTimeout} from './request-timeout.js';
import {option} from './api.js';
import {CallbackAction} from './callback-action.js';
import {installHistory} from './customer-history.js';
import {installPreRecall} from './pre-recall.js';
import {DeletionAction} from './deletion-action.js';
import {EmployeeAI} from './employee-ai.js';
import {customerLabels as labels,customerFields,choiceLabel} from './customer-columns.js';
import {choiceFilter} from './choice-filter.js';
const $=selector=>document.querySelector(selector),root=$('#employee'),userId=root.dataset.userId,view=root.dataset.view;
const schema=JSON.parse($('#customer-schema').textContent);
const editable=new Set(['call_result','visit_at','contract_status','notes','callback_due_at','housing_status','residence','route','memo']),dates=new Set(['visit_at','callback_due_at','assigned_at']);
const multiline=new Set(['notes','memo']),textFields=new Set(['notes','memo','route','residence']);
const text=(tag,value)=>{const el=document.createElement(tag);el.textContent=value;return el;},notice=message=>{$('#employee-message').textContent=message;};
const localDate=value=>value?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value)).replace(' ','T'):'';
const fullDate=value=>{if(!value)return '';const local=localDate(value),weekday=new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',weekday:'short'}).format(new Date(value));return `${local.slice(0,10)} (${weekday}) ${local.slice(11)}`;};
const display=(field,value)=>dates.has(field)?fullDate(value):field==='phone_normalized'&&value?String(value).replace(/^(010)(\d{4})(\d{4})$/,'$1-$2-$3'):choiceLabel(schema,field,value);
let state={site:'',page:1,size:50,q:'',sort:view==='today'?'priority':'-created_at',filters:{}},loadedState,lastPage=1,loading=true,navigating=false,activeEditor=null,comparison,callbacks,deletions,ai,queueReady=false,readOnly=false,accessRevoked=false;
async function request(url,body){
  if(environmentProblem&&body!==undefined)throw new Error('현재 조회 전용입니다. 상담 편집·저장은 HTTPS와 지원되는 브라우저에서 이용해 주세요.');
  return withRequestTimeout(async signal=>{
  const csrf=document.cookie.split('; ').find(v=>v.startsWith('csrftoken='))?.split('=').slice(1).join('=');
  const response=await fetch(url,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',signal,headers:{'X-TM-Queue-User':userId,...(body===undefined?{}:{'Content-Type':'application/json','X-CSRFToken':csrf||''})},...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data=await response.json().catch(()=>({}));
  if(!response.ok){const error=new Error(data.error?.message||`요청 실패 (${response.status})`);error.code=data.error?.code;error.status=response.status;error.data=data;
    if(response.status===401||response.status===403){accessRevoked=true;readOnly=false;queue.pause(error.message+' 다시 로그인해 주세요. 암호화된 대기값은 보관합니다.');}throw error;}
  return data;
  });
}
const queue=new EmployeeQueue(userId,request);
const environmentProblem=employeeSupportError();
const statusLabels={dirty:'미저장',saving:'저장 중',offline:'오프라인 대기',retry:'저장 실패·재시도 대기',failed:'저장 실패',conflict:'충돌',blocked:'전송 불가',review:'수동 확인 필요',checking:'복구 확인 중',clearing:'보관 정리 중'};
const params=()=>new URLSearchParams({site_id:state.site,view,q:state.q,filters:JSON.stringify(state.filters)});
function error(error){notice(error.message);}
function commitEditor(){activeEditor?.finish();}
function validate(field,value,row){
  normalized(field,value);
  if(schema[field]&&!Object.hasOwn(schema[field],value??'')&&value!==(row[field]??''))throw new Error('선택값을 확인해 주세요.');
  if(field==='notes'&&Array.from(value||'').length>Math.max(10000,Array.from(queue.rows.get(row.id)?.notes||'').length))throw new Error('비고는 최대 10,000자입니다. 기존의 긴 비고는 현재 길이까지 보존할 수 있습니다.');
  if(field==='housing_status'&&Array.from(value||'').length>200)throw new Error('주택보유상황은 최대 200자입니다.');
  if(['route','residence'].includes(field)&&Array.from(value||'').length>200)throw new Error(labels[field]+'는 최대 200자입니다.');
  if(field==='memo'&&Array.from(value||'').length>10000)throw new Error('비고는 최대 10,000자입니다.');
}
function editor(cell,onRendered,success,cancel){
  const field=cell.getField(),row=cell.getRow().getData(),original=cell.getValue();
  const input=document.createElement(schema[field]?'select':multiline.has(field)?'textarea':'input');input.setAttribute('aria-label',labels[field]);
  if(schema[field]){
    input.replaceChildren(...Object.entries(schema[field]).map(([value,label])=>option(value,label)));
    if(!Object.hasOwn(schema[field],original??'')){const previous=option(original??'',display(field,original));previous.disabled=true;input.prepend(previous);}
  }
  else if(dates.has(field)){input.type='datetime-local';input.min='0001-01-01T00:00';input.max='9999-12-31T23:59';}
  input.value=dates.has(field)?localDate(original):original??'';
  let done=false,touched=false,valid=true;
  const stage=()=>{
    touched=true;const value=dates.has(field)?input.value||null:input.value;
    try{validate(field,value,row);queue.markInvalid(row.id,field,'');valid=true;input.setCustomValidity('');queue.stage(row,field,value);}
    catch(e){valid=false;input.setCustomValidity(e.message);queue.markInvalid(row.id,field,e.message);notice(e.message);}return value;
  };
  const finish=()=>{if(done)return;if(touched&&!valid){input.reportValidity();return false;}done=true;activeEditor=null;success(touched?stage():original);return true;};
  input.addEventListener('input',stage);input.addEventListener('change',stage);
  input.addEventListener('blur',()=>{if(!finish())setTimeout(()=>input.focus(),0);});
  input.addEventListener('keydown',event=>{
    // Native date segments need arrows and Tab; Tabulator otherwise navigates rows/cells.
    if(dates.has(field)&&(event.key.startsWith('Arrow')||event.key==='Tab'))event.stopPropagation();
    if(event.key==='Escape'){event.preventDefault();done=true;activeEditor=null;queue.markInvalid(row.id,field,'');if(touched)queue.stage(row,field,original);cancel();}
    if(event.key==='Enter'&&!multiline.has(field)){event.preventDefault();finish();}
  });
  onRendered(()=>{activeEditor={finish,input};input.focus();});return input;
}
function column(field){
  return {title:labels[field],field,minWidth:field==='notes'?320:dates.has(field)?190:145,headerSort:false,
    formatter:cell=>{const value=cell.getValue();if(field==='assigned_at'){const span=text('span',value?localDate(value).slice(5,10).replace('-','/'):'');if(value)span.title=display(field,value)+' (한국 시각)';return span;}return text('span',display(field,value));},
    titleFormatter:()=>{const wrap=text('span',labels[field]),button=text('button','▾');button.type='button';button.className='column-filter';button.setAttribute('aria-label',labels[field]+' 필터');button.onclick=e=>{e.stopPropagation();guarded(()=>openFilter(field)).catch(error);};wrap.append(button);return wrap;},
    ...(editable.has(field)?{editable:cell=>!loading&&!navigating&&!callbacks?.busy&&!deletions?.busy&&!ai?.busy&&!callbacks?.pending.value&&queue.canEdit(cell.getRow().getData()),editor,variableHeight:multiline.has(field)}:{})};
}
const openHistory=installHistory(request);
function actions(cell){
  const row=queue.rows.get(cell.getRow().getData().id)||cell.getRow().getData(),wrap=document.createElement('span'),history=text('button','상담·재콜 이력'),complete=text('button','재콜 완료');
  history.className=complete.className='btn btn-sm btn-outline-secondary me-2';history.onclick=()=>{commitEditor();openHistory(row).catch(error);};
  complete.disabled=!row.callback_id||queue.paused||!queue.canEdit(row)||callbacks?.busy||deletions?.busy||ai?.busy||!!callbacks?.pending.value;complete.onclick=()=>{commitEditor();callbacks.run(row.id);};
  const requested=!!row.pending_deletion_request_id||deletions?.isConfirmed(row),button=text('button',deletions?.busyId===row.id?'요청 중':requested?'요청완료':'삭제 요청');button.className='btn btn-sm btn-outline-danger';
  button.disabled=!!requested||queue.paused||!queue.canEdit(row)||deletions?.busy||!!deletions?.pending.value||callbacks?.busy||ai?.busy||!!callbacks?.pending.value;button.onclick=()=>{commitEditor();deletions.run(row.id);};wrap.append(history,complete,button);
  for(const [feature,label] of [['CLEANUP','AI 상담 정리'],['SUMMARY','상담 요약'],['NEXT_QUESTIONS','다음 질문 제안']]){const control=text('button',label);control.className='btn btn-sm btn-outline-primary ms-2';control.disabled=!ai?.canGenerate()||!queue.canEdit(row)||callbacks?.busy||deletions?.busy||!!callbacks?.pending.value||!!deletions?.pending.value;control.onclick=()=>{commitEditor();ai.run(row.id,feature);};wrap.append(control);}
  const previous=text('button','AI 결과');previous.className='btn btn-sm btn-outline-secondary ms-2';previous.disabled=queue.paused||ai?.busy;previous.onclick=()=>{commitEditor();ai.history(row.id);};wrap.append(previous);return wrap;
}
const table=new Tabulator('#employee-grid',{index:'id',height:'min(60vh, 640px)',layout:'fitData',data:[],placeholder:'표시할 고객정보가 없습니다.',selectableRows:false,clipboard:false,
  rowFormatter:row=>{const e=queue.entry(row.getData().id);row.getElement().classList.toggle('pending-row',!!e);row.getElement().classList.toggle('failed-row',!!e&&['failed','conflict','blocked','review','retry'].includes(e.state));},
  columns:[...customerFields().map(column),{title:'작업',field:'_actions',headerSort:false,minWidth:950,formatter:actions},{title:'저장상태',field:'_status',minWidth:175,headerSort:false,formatter:cell=>text('span',environmentProblem?'조회 전용':statusLabels[queue.entry(cell.getRow().getData().id)?.state]||'저장됨')}]});
const ready=new Promise(resolve=>table.on('tableBuilt',resolve));
function renderStatus(){
  const entries=queue.all();$('#queue-status').textContent=readOnly?'조회 전용':queue.paused?'저장 중단':!queueReady?'저장 대기열 확인 중':queue.invalid.size?`입력 오류 · 미저장${entries.length?' '+entries.length+'행':''}`:entries.length?`저장 대기 ${entries.length}행`:'모든 변경 저장됨';
  $('#storage-warning').textContent=[queue.storageError,queue.recoveryErrors?`복구하지 못한 암호화 기록 ${queue.recoveryErrors}건이 있습니다. 기록을 지우지 않았습니다.`:'',queue.otherTabs?`다른 탭에서 보관 중인 대기값 ${queue.otherTabs}건은 해당 탭에서 확인하세요.`:''].filter(Boolean).join(' ');
  if(queue.paused){notice(readOnly?`조회 전용 · ${queue.pauseMessage} 현장 선택과 담당 고객 조회는 가능합니다.`:queue.pauseMessage);$('#employee-private').hidden=!readOnly;$('#callback-pending').hidden=true;$('#deletion-pending').hidden=true;if(!readOnly)document.querySelectorAll('dialog[open]').forEach(d=>d.close());}
  $('#ai-toolbar').hidden=queue.paused;if(queue.paused)ai?.hidePrivate();ai?.syncApply();
  $('#save-now').disabled=queue.paused||!entries.length;$('#pending-panel').hidden=queue.paused||!entries.length;
  $('#pending-rows').replaceChildren(...entries.map(e=>{
    const base=queue.rows.get(e.customer_id),caption=e.state!=='blocked'&&base?`${base.site_name} · ${base.customer_name}`:(e.site_id===state.site?'현재 현장':'다른 현장');
    const wrap=text('div',`${caption} · ${statusLabels[e.state]}${e.error?' · '+e.error:''}`);wrap.className='pending-item';wrap.dataset.key=e.key;
    const button=text('button',e.state==='blocked'?'대기 정보 확인':'비교·확인');button.className='btn btn-sm btn-outline-secondary ms-2';button.disabled=e.state==='saving';button.onclick=()=>openConflict(e).catch(error);wrap.append(button);return wrap;
  }));
  for(const row of table.getRows()){
    const data=row.getData(),entry=queue.entry(data.id),base=queue.rows.get(data.id),values=entry?.state==='blocked'?{}:{...base,...(entry?changes(entry):{})};
    if(entry?.state==='blocked'){row.delete().catch(()=>{});continue;}
    for(const field of editable){const cell=row.getCell(field);if(!cell){if(base)data[field]=values[field];continue;}if(cell.getElement().classList.contains('tabulator-editing'))continue;if(base&&cell.getValue()!==values[field])cell.setValue(values[field]);}
    const status=entry?eState(entry):'saved',statusCell=row.getCell('_status');if(statusCell)statusCell.setValue(status);else data._status=status;
    const action=row.getCell('_actions');if(action)action.setValue(JSON.stringify([base?.callback_id,base?.callback_version,base?.pending_deletion_request_id,callbacks?.busy,!!callbacks?.pending.value,deletions?.busy,deletions?.busyId,!!deletions?.pending.value,deletions?.isConfirmed(base||data),ai?.busy,ai?.canGenerate(),queue.paused,entry?.state]));
    row.getElement().classList.toggle('pending-row',!!entry);row.getElement().classList.toggle('failed-row',!!entry&&['failed','conflict','blocked','review','retry'].includes(entry.state));
  }
}
const eState=e=>[e.state,e.version,Object.keys(e.pending).length,e.error].join(':');
queue.addEventListener('change',renderStatus);
async function load(){
  loading=true;notice('');
  try{
    const query=params();query.set('page',state.page);query.set('page_size',state.size);query.set('sort',state.sort);
    const data=await request('/api/customers?'+query);if(data.last_page<state.page){state.page=data.last_page;return await load();}
    queue.setRows(data.data);lastPage=data.last_page;
    await table.setData(data.data.map(row=>({...row,...(queue.entry(row.id)?changes(queue.entry(row.id)):{} )})));
    $('#page-info').textContent=`검색 ${data.total.toLocaleString()}건 · ${state.page} / ${lastPage}페이지`;
    $('#previous').disabled=state.page<=1;$('#next').disabled=state.page>=lastPage;
    $('#active-filters').replaceChildren(...Object.keys(state.filters).map(field=>{const button=text('button',labels[field]+' 조건 해제 ×');button.className='btn btn-sm btn-outline-primary';button.onclick=()=>guarded(async()=>{delete state.filters[field];state.page=1;await load();}).catch(error);return button;}));
    loadedState=structuredClone(state);renderStatus();
  }catch(e){if(loadedState){state=structuredClone(loadedState);$('#site').value=state.site;$('#sort').value=state.sort;$('#page-size').value=String(state.size);}throw e;}
  finally{loading=false;}
}
function choice(dialog,actions){
  return new Promise(resolve=>{let done=false;const finish=value=>{if(done)return;done=true;dialog.close();resolve(value);};for(const [id,value] of Object.entries(actions))$('#'+id).onclick=()=>finish(value);dialog.oncancel=event=>{event.preventDefault();finish('cancel');};dialog.showModal();});
}
async function guarded(action,logout=false){
  commitEditor();if(navigating||callbacks?.busy||deletions?.busy||ai?.busy)return false;navigating=true;
  try{
    while(queue.entries.size||queue.invalid.size||callbacks?.pending.value||deletions?.pending.value||ai?.pending.value){
      if(callbacks?.pending.value)await callbacks.run();
      if(deletions?.pending.value)await deletions.run();
      if(ai?.pending.value)await ai.run();
      if(!callbacks?.pending.value&&!deletions?.pending.value&&!ai?.pending.value&&await queue.flush(true))break;
      $('#leave-message').textContent=queue.paused?queue.pauseMessage:'오프라인·입력 오류·저장 충돌이 있습니다. 저장 상태를 확인해 주세요.';
      $('#leave-cancel').textContent=logout?'로그아웃 취소':'이동 취소';$('#leave-discard').textContent=logout?'대기값 버리고 로그아웃':'대기값 버리고 이동';
      const decision=await choice($('#leave-dialog'),{'leave-cancel':'cancel','leave-discard':'discard','leave-retry':'retry'});
      if(decision==='cancel')return false;
      if(decision==='discard'){
        if(!confirm('이 탭의 저장 대기값을 모두 버리시겠습니까? 이미 서버에 반영된 변경은 취소되지 않습니다.'))continue;
        callbacks?.clear();deletions?.clear();ai?.clear();await queue.discardAll();if(queue.entries.size){notice('로컬 기록을 폐기하지 못했습니다. 이동을 취소합니다.');return false;}break;
      }
    }
    if($('#ai-dialog').open)$('#ai-dialog').close();await action();return true;
  }finally{navigating=false;}
}
async function openConflict(entry){
  comparison={entry,version:null};await queue.compare(entry);if(queue.paused)return;drawConflict();$('#employee-conflict').showModal();
}
function drawConflict(){
  const {entry}=comparison;comparison.version=entry.server?.version;$('#conflict-message').textContent=entry.error||'저장 전 서버 값과 내 대기값을 확인하세요.';
  if(entry.state!=='blocked'&&entry.server)$('#conflict-message').textContent+=` · 현재 고객: ${display('customer_name',entry.server.customer_name)} · ${display('phone_normalized',entry.server.phone_normalized)}`;
  $('#employee-compare').replaceChildren();
  if(entry.state!=='blocked'&&entry.server)for(const [field,value] of Object.entries(changes(entry))){const tr=document.createElement('tr');tr.append(text('th',labels[field]),text('td',display(field,entry.server[field])),text('td',display(field,value)));$('#employee-compare').append(tr);}
  $('#employee-reapply').disabled=entry.state==='blocked'||!entry.server;
}
$('#employee-reapply').onclick=async()=>{const button=$('#employee-reapply');button.disabled=true;try{if(await queue.reapply(comparison.entry,comparison.version)){$('#employee-conflict').close();await load();}else drawConflict();}catch(e){error(e);}};
$('#employee-discard').onclick=async()=>{if(!confirm('내 대기값을 폐기하시겠습니까? 이미 저장된 변경은 취소되지 않습니다.'))return;await queue.discard(comparison.entry);$('#employee-conflict').close();await load().catch(error);};
for(const button of document.querySelectorAll('[data-close]'))button.onclick=()=>button.closest('dialog').close();
$('#save-now').onclick=async()=>{commitEditor();const ok=await queue.flush(true);notice(ok?'저장했습니다.':'저장하지 못한 행을 확인해 주세요.');};
$('#reload-rows').onclick=()=>guarded(load).catch(error);
$('#site').onchange=event=>{const site=event.target.value;event.target.value=state.site;guarded(async()=>{state.site=site;state.page=1;$('#site').value=site;await load();}).catch(error);};
$('#sort').onchange=event=>{const sort=event.target.value;event.target.value=state.sort;guarded(async()=>{state.sort=sort;state.page=1;$('#sort').value=sort;await load();}).catch(error);};
$('#page-size').onchange=event=>{const size=Number(event.target.value);event.target.value=String(state.size);guarded(async()=>{state.size=size;state.page=1;$('#page-size').value=String(size);await load();}).catch(error);};
$('#search-form').onsubmit=event=>{event.preventDefault();guarded(async()=>{state.q=$('#search').value;state.page=1;await load();}).catch(error);};
$('#clear-filters').onclick=()=>guarded(async()=>{state.filters={};state.page=1;await load();}).catch(error);
$('#previous').onclick=()=>guarded(async()=>{state.page--;await load();}).catch(error);$('#next').onclick=()=>guarded(async()=>{state.page++;await load();}).catch(error);
document.addEventListener('click',event=>{const link=event.target.closest('a[href]');if(!link||link.target||event.ctrlKey||event.metaKey)return;if(new URL(link.href).origin!==location.origin)return;event.preventDefault();guarded(()=>{location.href=link.href;}).catch(error);},true);
document.addEventListener('submit',event=>{const form=event.target;if(form.action?.endsWith('/auth/logout')){event.preventDefault();event.stopImmediatePropagation();guarded(()=>{HTMLFormElement.prototype.submit.call(form);},true).catch(error);}},true);
for(const name of ['copy','cut','contextmenu'])$('#employee-grid').addEventListener(name,event=>event.preventDefault());
$('#employee-grid').addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&['c','x'].includes(event.key.toLowerCase()))event.preventDefault();});
window.addEventListener('beforeunload',event=>{if(queue.entries.size||queue.invalid.size||callbacks?.pending.value||deletions?.pending.value||ai?.pending.value){event.preventDefault();event.returnValue='';}});
window.addEventListener('offline',()=>{for(const entry of queue.all())if(['dirty','retry'].includes(entry.state))entry.state='offline';renderStatus();});
async function resume(){try{const me=await request('/api/me');if(me.id!==userId||me.role!=='EMPLOYEE'||me.must_change_password){accessRevoked=true;readOnly=false;queue.pause('로그인 정보가 변경되었습니다. 다시 로그인해 주세요.');return;}if(environmentProblem){if(!accessRevoked){readOnly=true;renderStatus();}return;}await queue.resume();}catch(e){error(e);}}
window.addEventListener('online',resume);document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')resume();});window.addEventListener('focus',resume);
window.addEventListener('tm-auth-context',event=>{const data=event.detail;if(data.user!==userId||data.role!=='EMPLOYEE'||data.initial){accessRevoked=true;readOnly=false;queue.pause('다른 탭에서 로그인 정보가 변경되었습니다. 대기값 전송을 중단했습니다.');}});
async function openFilter(field){
  const dialog=$('#filter-dialog'),area=$('#filter-content');$('#filter-title').textContent=labels[field]+' 필터';$('#filter-error').textContent='';area.replaceChildren();let condition;
  if(schema[field]){
    condition=await choiceFilter({area,field,schema,current:state.filters[field],request,params,display});
  }else if(dates.has(field)){
    for(const [key,title] of [['from','시작일'],['to','종료일']]){const label=text('label',title),input=document.createElement('input');input.type='date';input.id='filter-'+key;input.value=state.filters[field]?.[key]||'';label.append(input);area.append(label);}
    condition=()=>{const values={};for(const key of ['from','to'])if($('#filter-'+key).value)values[key]=$('#filter-'+key).value;return Object.keys(values).length?values:undefined;};
  }else if(textFields.has(field)){
    const label=text('label','포함할 내용'),input=document.createElement('input');input.id='filter-contains';input.maxLength=10000;input.value=state.filters[field]?.contains||'';label.append(input);area.append(label);condition=()=>input.value?{contains:input.value}:undefined;
  }else{
    const current=state.filters[field];let exclude=current?.exclude??!current,selected=new Set(current?.values??current??[]),page=1,search='',generation=0;
    const label=text('label','후보값 검색'),input=document.createElement('input'),searchButton=text('button','후보 검색'),all=text('button','전체 선택'),none=text('button','전체 해제'),list=document.createElement('div'),nav=document.createElement('div'),info=text('span',''),previous=text('button','이전 후보'),next=text('button','다음 후보');
    input.type='search';input.maxLength=200;label.append(input);list.id='filter-options';nav.className='d-flex gap-2 align-items-center';nav.append(previous,info,next);area.append(label,searchButton,all,none,list,nav);
    for(const button of [searchButton,all,none,previous,next])button.className='btn btn-sm btn-outline-secondary m-1';
    const draw=async()=>{const token=++generation,query=params();query.set('field',field);query.set('option_q',search);query.set('option_page',page);
      try{const data=await request('/api/customers/filter-options?'+query);if(token!==generation)return;list.replaceChildren(...data.values.map(value=>{const key=value??'',label=document.createElement('label'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=exclude?!selected.has(key):selected.has(key);checkbox.onchange=()=>{if(checkbox.checked!==exclude)selected.add(key);else selected.delete(key);};label.append(checkbox,document.createTextNode(' '+display(field,value)));return label;}));info.textContent=`후보 ${data.total}개 · ${page}페이지`;previous.disabled=page<=1;next.disabled=!data.has_next;}catch(e){$('#filter-error').textContent=e.message;}};
    all.onclick=()=>{exclude=true;selected.clear();list.querySelectorAll('input').forEach(c=>{c.checked=true;});};none.onclick=()=>{exclude=false;selected.clear();list.querySelectorAll('input').forEach(c=>{c.checked=false;});};searchButton.onclick=()=>{search=input.value;page=1;draw();};previous.onclick=()=>{page--;draw();};next.onclick=()=>{page++;draw();};
    condition=()=>exclude&&!selected.size?undefined:{values:[...selected],exclude};await draw();
  }
  const apply=async value=>{if(value?.values?.length>1000){$('#filter-error').textContent='한 열은 최대 1,000개 값을 선택·제외할 수 있습니다.';return;}const previous=state.filters[field];if(value===undefined)delete state.filters[field];else state.filters[field]=value;state.page=1;try{await load();dialog.close();}catch(e){if(previous===undefined)delete state.filters[field];else state.filters[field]=previous;$('#filter-error').textContent=e.message;}};
  $('#filter-reset').onclick=()=>apply(undefined);$('#filter-apply').onclick=()=>apply(condition());dialog.showModal();
}
await ready;
callbacks=new CallbackAction({userId,request,flush:async id=>{commitEditor();return queue.flush(true,id);},getRow:id=>queue.rows.get(id),refresh:async row=>{if(row)queue.setRows([row]);await load();},notice,changed:renderStatus});callbacks.update();
deletions=new DeletionAction({userId,request,flush:async id=>{commitEditor();return queue.flush(true,id);},getRow:id=>queue.rows.get(id),refresh:load,notice,changed:renderStatus});deletions.update();
ai=new EmployeeAI({userId,request,queue,flush:async id=>{commitEditor();return queue.flush(true,id);},notice,changed:renderStatus,labels,display,validate});
try{
  if(environmentProblem){
    document.querySelector('.editing-guide').textContent='현재 조회 전용입니다. 현장 선택·검색·담당 고객 조회는 가능합니다. 상담 편집·저장은 HTTPS와 지원되는 브라우저에서 이용해 주세요.';
    queue.pause(environmentProblem.message);
    const me=await request('/api/me');
    if(accessRevoked||me.id!==userId||me.role!=='EMPLOYEE'||me.must_change_password)throw new Error('로그인 정보가 변경되었습니다. 다시 로그인해 주세요.');
    readOnly=true;renderStatus();table.redraw(true);
  }else{
  const context=await request('/api/employee/context'),receivedAt=Date.now();await queue.start(context);queueReady=!queue.paused;renderStatus();if(queue.paused)throw new Error(queue.pauseMessage);installPreRecall({serverTime:context.server_time,receivedAt,commit:commitEditor,flush:()=>queue.flush(true),notice});
  }
  const sites=await request('/api/sites');$('#site').replaceChildren(...sites.items.map(s=>option(s.id,s.name)));state.site=new URL(location.href).searchParams.get('site_id')||sites.default_site_id||'';$('#site').value=state.site;
  await load();await ai.refreshAvailability();queue.tick();
}catch(e){error(e);loading=false;}
