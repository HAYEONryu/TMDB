import {sortTitle,syncSortHeaders} from './server-sort.js';
import {confirmAction} from './shared-ui.js';
import {listenAdminUpdates} from './admin-updates.js';
import {ActivityRecorder} from './activity-recorder.js';
import {EmployeeQueue,changes,normalized} from './employee-queue.js';
import {employeeSupportError} from './browser-environment.js';
import {withRequestTimeout} from './request-timeout.js';
import {option} from './api.js';
import {CallbackAction} from './callback-action.js';
import {installHistory} from './customer-history.js';
import {installPreRecall} from './pre-recall.js';
import {DeletionAction} from './deletion-action.js';
import {EmployeeAI} from './employee-ai.js';
import {customerLabels,customerFields,choiceLabel} from './customer-columns.js';
import {openGridFilter} from './grid-filter.js';
import {createQueryUI,createQueryScheduler} from './customer-query.js';
import {syncEmployeeSiteLinks} from './employee-navigation.js';
import {setupDateInput,dateInputTimestamp} from './date-input.js';
const $=selector=>document.querySelector(selector),root=$('#employee'),userId=root.dataset.userId,view=root.dataset.view;
const schema=JSON.parse($('#customer-schema').textContent);
const labels = { ...customerLabels, last_tm_date: '최종 TM 날짜', residence: '거주지', memo: '메모', visit_at: '방문예약날짜' };
const employeeGridFields = ['customer_name', 'phone_normalized', 'call_result', 'residence',
  'notes', 'callback_due_at', 'memo', 'visit_at'];
const editable=new Set(['customer_name','call_result','visit_at','contract_status','notes','callback_due_at','housing_status','residence','route','memo']),dates=new Set(['visit_at','callback_due_at','assigned_at']);
const multiline=new Set(['notes','memo']);
const gridWidths={customer_name:140,phone_normalized:154,call_result:166,residence:180,notes:340,memo:260,callback_due_at:210,visit_at:174};
const text=(tag,value)=>{const el=document.createElement(tag);el.textContent=value;return el;},notice=message=>{$('#employee-message').textContent=message;};
const localDate=value=>value?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value)).replace(' ','T'):'';
const display=(field,value)=>dates.has(field)?(value?(field==='visit_at'?localDate(value).replace('T',' '):localDate(value).slice(0,10)):'-'):field==='phone_normalized'&&value?String(value).replace(/^(010)(\d{4})(\d{4})$/,'$1-$2-$3'):choiceLabel(schema,field,value);
let state={site:'',page:1,size:50,q:new URL(location.href).searchParams.get('q')||'',sort:new URL(location.href).searchParams.get('sort')||(view==='today'?'priority':'-created_at'),category:new URL(location.href).searchParams.get('dashboard_category')||'',filters:{}},defaultSite='',loadedState,lastPage=1,loading=true,navigating=false,activeEditor=null,comparison,callbacks,deletions,ai,queueReady=false,readOnly=false,accessRevoked=false;
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
const recorder=new ActivityRecorder({userId,changed:()=>refreshActivityDate().catch(()=>notice('기록은 저장되었습니다. 최종 TM 날짜는 목록을 다시 조회해 확인하세요.'))});
async function refreshActivityDate(){
  const row=queue.rows.get(recorder.row?.id);if(!row)return;
  const data=await request('/api/employee/queue-check',{entries:[{key:'activity-date',site_id:row.site_id,customer_id:row.id,assignment_id:row.assignment_id,expected_version:row.version}]});
  const fresh=data.results[0]?.server_row;
  if(fresh){queue.setRows([fresh]);renderStatus();}
  else notice('기록은 저장되었습니다. 현재 담당 상태를 다시 조회해 주세요.');
}
const statusLabels={dirty:'미저장',saving:'저장 중',offline:'오프라인 대기',retry:'저장 결과 확인 대기',failed:'저장하지 못함',conflict:'충돌',blocked:'전송 불가',review:'수동 확인 필요',checking:'복구 확인 중',clearing:'보관 정리 중'};
const params=()=>new URLSearchParams({site_id:state.site,view,q:state.q,filters:JSON.stringify(state.filters),...(state.category?{dashboard_category:state.category}:{})});
function error(error){notice(error.message);}
function commitEditor(){activeEditor?.finish();}
function validate(field,value,row){
  normalized(field,value);
  if(field==='customer_name'&&Array.from((value||'').trim()).length>100)throw new Error('고객명은 최대 100자입니다.');
  if(schema[field]&&!Object.hasOwn(schema[field],value??'')&&value!==(row[field]??''))throw new Error('선택값을 확인해 주세요.');
  if(field==='notes'&&Array.from(value||'').length>Math.max(10000,Array.from(queue.rows.get(row.id)?.notes||'').length))throw new Error('상담내용은 최대 10,000자입니다. 기존의 긴 상담내용은 현재 길이까지 보존할 수 있습니다.');
  if(field==='housing_status'&&Array.from(value||'').length>200)throw new Error('주택보유상황은 최대 200자입니다.');
  if(['route','residence'].includes(field)&&Array.from(value||'').length>200)throw new Error(labels[field]+'는 최대 200자입니다.');
  if(field==='memo'&&Array.from(value||'').length>10000)throw new Error('메모는 최대 10,000자입니다.');
}
function editor(cell,onRendered,success,cancel){
  const field=cell.getField(),row=cell.getRow().getData(),original=cell.getValue();
  const input=document.createElement(schema[field]?'select':multiline.has(field)?'textarea':'input');input.setAttribute('aria-label',labels[field]);
  if(schema[field]){
    input.replaceChildren(...Object.entries(schema[field]).map(([value,label])=>option(value,label)));
    if(!Object.hasOwn(schema[field],original??'')){const previous=option(original??'',display(field,original));previous.disabled=true;input.prepend(previous);}
  }
  else if(dates.has(field))setupDateInput(input,{allowTime:field==='visit_at'});
  input.value=dates.has(field)?(field==='visit_at'?localDate(original).replace('T',' '):localDate(original).slice(0,10)):original??'';
  let done=false,touched=false,valid=true,validationMessage='';
  const stage=()=>{
    if(done)return original;
    touched=true;let value;
    try{value=dates.has(field)?dateInputTimestamp(input.value,{allowTime:field==='visit_at'}):input.value;validate(field,value,row);queue.markInvalid(row.id,field,'');valid=true;input.setCustomValidity('');if($('#employee-message').textContent===validationMessage)notice('');validationMessage='';queue.stage(row,field,value);}
    catch(e){valid=false;validationMessage=e.message;input.setCustomValidity(e.message);queue.markInvalid(row.id,field,e.message);if(!dates.has(field))notice(e.message);}return value;
  };
  const finish=()=>{if(done)return true;const value=touched?stage():original;if(!valid){notice(validationMessage);input.reportValidity();return false;}done=true;activeEditor=null;success(value);return true;};
  input.addEventListener('input',stage);input.addEventListener('change',stage);
  input.addEventListener('blur',()=>{if(!finish())setTimeout(()=>input.focus(),0);});
  input.addEventListener('keydown',event=>{
    // Keep cursor movement and Tab inside the text editor until it commits.
    if(dates.has(field)&&(event.key.startsWith('Arrow')||event.key==='Tab'))event.stopPropagation();
    if(event.key==='Escape'){event.preventDefault();done=true;activeEditor=null;queue.markInvalid(row.id,field,'');if(touched)queue.stage(row,field,original);cancel();}
    if(event.key==='Enter'&&!multiline.has(field)){event.preventDefault();finish();}
  });
  onRendered(()=>{activeEditor={finish,input};input.focus();});return input;
}
function column(field){
  return {title:labels[field],field,minWidth:gridWidths[field],width:gridWidths[field],headerSort:false,
    titleFormatter:sortTitle(field,labels[field],()=>state,changeSort),
    formatter:cell=>text('span',display(field,cell.getValue())),
    ...(editable.has(field)?{editable:cell=>!loading&&!navigating&&!callbacks?.busy&&!deletions?.busy&&!ai?.busy&&!callbacks?.pending.value&&queue.canEdit(cell.getRow().getData()),editor,variableHeight:multiline.has(field)}:{})};
}
const openHistory=installHistory(request);
const deletionHelp='삭제 요청: 관리자에게 고객 삭제를 요청합니다. 관리자 승인 후 휴지통으로 이동합니다.';
const actionHelp=[
  '이력: 상담 변경 내역과 재콜 처리 기록을 확인합니다.',
  'AI 도움\n· 항목 정리: 상담을 정리하고 수정할 값을 제안합니다.\n· 핵심 요약: 상담의 핵심 내용을 보여줍니다.\n· 다음 질문: 다음 통화에서 물어볼 질문을 제안합니다.\n· 기존 결과: 이전에 생성한 AI 결과를 확인합니다.\n결과를 확인한 뒤 선택한 항목만 반영할 수 있습니다.',
  '재콜 완료: 재콜일정의 ‘완료’를 체크합니다.\n날짜를 지우면 완료가 아닌 일정 취소로 처리됩니다.'
].join('\n\n');
function actionTooltip(event,_column,onRendered){
  const tooltip=text('div',actionHelp);tooltip.className='actions-header-tooltip';
  onRendered(()=>requestAnimationFrame(()=>{
    if(!tooltip.isConnected)return;
    // Tabulator fits tooltips to the full document; keep this longer help
    // inside the visible window, including when the grid is near its bottom.
    Object.assign(tooltip.style,{position:'fixed',height:'auto',right:'auto'});
    const {width,height}=tooltip.getBoundingClientRect(),gap=12;
    tooltip.style.left=Math.max(gap,Math.min(event.clientX+gap,innerWidth-width-gap))+'px';
    const below=event.clientY+gap;
    tooltip.style.top=Math.max(gap,below+height<=innerHeight-gap?below:event.clientY-height-gap)+'px';
  }));
  return tooltip;
}
const actionBlocked=row=>queue.paused||!queue.canEdit(row)||callbacks?.busy||deletions?.busy||ai?.busy||!!callbacks?.pending.value||!!deletions?.pending.value;
function callbackCell(cell){
  const row=queue.rows.get(cell.getRow().getData().id)||cell.getRow().getData(),wrap=document.createElement('span');
  wrap.className='callback-cell';wrap.append(text('span',display('callback_due_at',cell.getValue())));
  if(row.callback_id){
    const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.setAttribute('aria-label','재콜 완료');check.disabled=!!actionBlocked(row);label.className='callback-complete';label.title='실제로 재콜을 마쳤을 때 체크하세요. 이 행의 변경을 먼저 저장하고 재콜을 완료합니다.';
    label.append(check,document.createTextNode(' 완료'));
    // A label press otherwise focuses Tabulator's editable parent cell before
    // its click fires, replacing the checkbox with the date editor.
    label.onmousedown=event=>{event.preventDefault();event.stopPropagation();};
    for(const name of ['dblclick','pointerdown','touchstart'])label.addEventListener(name,event=>event.stopPropagation());
    check.onkeydown=event=>event.stopPropagation();
    // Run before native label activation can blur another editor. Committing
    // that editor redraws this cell and would discard the pending label click.
    label.onclick=async event=>{event.preventDefault();event.stopPropagation();if(check.disabled)return;check.checked=true;check.disabled=true;commitEditor();await callbacks.run(row.id);renderStatus();};wrap.append(label);
  }
  return wrap;
}
function deletionCell(cell){
  const row=queue.rows.get(cell.getRow().getData().id)||cell.getRow().getData();
  const requested=!!row.pending_deletion_request_id||deletions?.isConfirmed(row),button=text('button',deletions?.busyId===row.id?'요청 중':requested?'요청완료':'삭제 요청');button.className='btn btn-sm btn-outline-danger';
  button.disabled=!!requested||actionBlocked(row);button.title='관리자에게 삭제 승인을 요청합니다.';button.onclick=()=>{commitEditor();deletions.run(row.id);};return button;
}
function notesCell(cell){
  const data = cell.getRow().getData();
  const row = queue.rows.get(data.id) || data;
  const content = document.createElement('div');
  content.className = 'employee-note-content';
  const summary = document.createElement('div');
  summary.className = 'd-flex align-items-center gap-2 py-2';
  const preview = text('div', display('notes', cell.getValue()));
  preview.className = 'employee-note-preview text-truncate flex-grow-1';
  const actions = document.createElement('div');
  actions.className = 'employee-note-actions d-flex flex-wrap align-items-center gap-1';
  for (const event of ['mousedown', 'pointerdown', 'touchstart', 'dblclick', 'click', 'keydown']) {
    actions.addEventListener(event, e => e.stopPropagation());
  }

  const history = text('button', '이력');
  history.type = 'button';
  history.className = 'btn btn-sm btn-outline-secondary';
  history.setAttribute('aria-label', '상담·재콜 이력');
  history.title = '저장된 상담 변경과 재콜 이력을 조회합니다.';
  history.onclick = () => { commitEditor(); openHistory(queue.rows.get(row.id) || row).catch(error); };
  const control = text('button', 'AI 도움');
  control.type = 'button';
  control.className = 'btn btn-sm btn-outline-primary employee-note-ai';
  control.title = '기능 설명·사용 준비·기존 AI 결과를 확인합니다.';
  control.onclick = () => { commitEditor(); ai.open(row.id); };
  const activity = recorder.button(row);
  activity.classList.add('employee-note-activity');
  const state = text('span', '');
  state.className = 'employee-note-status small flex-shrink-0';
  summary.append(preview, state);
  actions.append(history, control, activity);
  content.append(summary, actions);
  updateNoteActions(content, row, queue.entry(row.id));
  return content;
}
function updateNoteActions(content, row, entry){
  content.querySelector('.employee-note-ai').disabled = !!(queue.paused || ai?.busy || callbacks?.busy || deletions?.busy);
  content.querySelector('.employee-note-activity').disabled = !!(environmentProblem || actionBlocked(row));
  const state = content.querySelector('.employee-note-status');
  state.textContent = environmentProblem ? '조회 전용' : statusLabels[entry?.state] || '';
  state.hidden = !state.textContent;
}
function rowStyle(row){
  const data=queue.rows.get(row.getData().id)||row.getData(),entry=queue.entry(data.id),element=row.getElement();
  element.classList.toggle('pending-row',!!entry);
  element.classList.toggle('failed-row',!!entry&&['failed','conflict','blocked','review','retry'].includes(entry.state));
  element.classList.toggle('deletion-requested-row',!!data.pending_deletion_request_id||!!deletions?.isConfirmed(data));
}
const table=new Tabulator('#employee-grid',{index:'id',height:'min(60vh, 640px)',layout:'fitData',data:[],placeholder:' ',selectableRows:false,clipboard:false,
  rowFormatter:rowStyle,
  columns:[{title:'No.',field:'_number',frozen:true,width:56,minWidth:56,hozAlign:'center',headerSort:false},
    {title:labels.last_tm_date,field:'last_tm_date',frozen:true,width:140,headerSort:false,editor:false,
    titleFormatter:sortTitle('last_tm_date',labels.last_tm_date,()=>state,changeSort),
    headerTooltip:'현재 배정에서 내가 마지막으로 기록한 통화 또는 저장한 통화결과의 한국 날짜입니다. 부재도 포함합니다.',
    formatter:cell=>{const value=queue.rows.get(cell.getRow().getData().id)?.last_tm_date||cell.getValue();cell.getElement().classList.toggle('missing-tm-date',!value);return text('span',value||'-');}},
    ...employeeGridFields.flatMap(field=>[
    {...column(field),...(field==='callback_due_at'?{formatter:callbackCell}:{}),
      ...(field==='notes'?{formatter:notesCell,headerTooltip:actionTooltip}:{})},
    ...(field==='call_result'?[{title:'삭제요청',field:'_deletion',headerSort:false,width:120,minWidth:120,headerTooltip:deletionHelp,titleFormatter:sortTitle('deletion_request_status','삭제요청',()=>state,changeSort),formatter:deletionCell}]:[])
  ])]});
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
    const button=text('button',e.state==='blocked'?'저장 대기 변경 확인':'비교·확인');button.className='btn btn-sm btn-outline-secondary ms-2';button.disabled=e.state==='saving';button.onclick=()=>openConflict(e).catch(error);wrap.append(button);return wrap;
  }));
  for(const row of table.getRows()){
    const data=row.getData(),entry=queue.entry(data.id),base=queue.rows.get(data.id),values=entry?.state==='blocked'?{}:{...base,...(entry?changes(entry):{})};
    if(entry?.state==='blocked'){row.delete().catch(()=>{});continue;}
    for(const field of editable){const cell=row.getCell(field);if(!cell){if(base)data[field]=values[field];continue;}if(cell.getElement().classList.contains('tabulator-editing'))continue;if(base&&cell.getValue()!==values[field])cell.setValue(values[field]);}
    const tm=row.getCell('last_tm_date');if(tm&&base&&tm.getValue()!==base.last_tm_date)tm.setValue(base.last_tm_date);
    const actionState=JSON.stringify([base?.pending_deletion_request_id,callbacks?.busy,!!callbacks?.pending.value,deletions?.busy,deletions?.busyId,!!deletions?.pending.value,deletions?.isConfirmed(base||data),ai?.busy,queue.paused,entry?.state]);
    row.getCell('_deletion')?.setValue(actionState);
    const noteActions = row.getCell('notes')?.getElement().querySelector('.employee-note-content');
    if (noteActions) updateNoteActions(noteActions, base || data, entry);
    const callback=row.getCell('callback_due_at');if(callback&&!callback.getElement().classList.contains('tabulator-editing'))callback.getElement().replaceChildren(callbackCell(callback));
    rowStyle(row);
  }
}
queue.addEventListener('change',renderStatus);
let nextCursor=null,streamTotal=0,appendFailed=false;
let loadGeneration=0,loadedBusinessDate=null,serverClock=null;
const businessDate=value=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
function refreshTMDate(){
  if(view!=='today'||!serverClock||loading||navigating||document.hidden||!navigator.onLine||activeEditor||queue.entries.size||queue.invalid.size||callbacks?.busy||deletions?.busy||ai?.busy||callbacks?.pending.value||deletions?.pending.value||ai?.pending.value||(queue.paused&&!readOnly))return;
  const current=businessDate(serverClock.at+Date.now()-serverClock.received);
  if(current!==loadedBusinessDate)void runQuery(load).catch(error);
}
const runQuery=createQueryScheduler(guarded);
$('#search').value=state.q;
const queryUI=createQueryUI({getState:()=>state,labels:customerLabels,display,view,grid:$('#employee-grid'),change:mutate=>runQuery(async()=>{mutate(state);await load();}).catch(error)});
$('#list-retry').onclick=()=>runQuery(load).catch(error);
function changeSort(sort){runQuery(async()=>{state.sort=sort;state.page=1;await load();}).catch(error);}
function streamStatus(){
  $('#page-info').textContent='검색 '+streamTotal.toLocaleString()+'명 · '+table.getDataCount().toLocaleString()+' / '+streamTotal.toLocaleString()+'명 표시'+(nextCursor?' · 아래로 스크롤하면 더 불러옵니다.':' · 모두 불러왔습니다.');
  $('#previous').disabled=true;$('#next').disabled=loading||!nextCursor;$('#next').hidden=!nextCursor;
}
async function load(append=false){
  const generation=++loadGeneration;
  loading=true;notice('');if(!append)queryUI.start();else $('#next').disabled=true;
  try{
    const query=params();query.set('pagination','infinite');query.set('page_size',state.size);query.set('sort',state.sort);if(append&&nextCursor)query.set('cursor',nextCursor);
    const data=await request('/api/customers?'+query);if(generation!==loadGeneration)return;
    queue.setRows(data.data);lastPage=data.last_page;
    loadedBusinessDate=businessDate(data.as_of);serverClock={at:new Date(data.as_of).getTime(),received:Date.now()};
    if($('#tm-business-date'))$('#tm-business-date').textContent='기준일 '+loadedBusinessDate+' · 한국 시간';
    const offset = (data.page - 1) * data.page_size;
    const values = data.data.map((row, index) => ({
      ...row, ...(queue.entry(row.id) ? changes(queue.entry(row.id)) : {}), _number: offset + index + 1,
    }));
    if(append){if(values.some(row=>table.getRow(row.id)))throw new Error('목록이 변경되었습니다. 목록 새로고침으로 다시 조회해 주세요.');await table.addData(values);}else{await table.setData(values);$('#employee-grid .tabulator-tableholder').scrollTop=0;}
    nextCursor=data.next_cursor;streamTotal=data.total;appendFailed=false;
    if(generation!==loadGeneration)return;
    syncSortHeaders(table,state.sort);
    loadedState=structuredClone(state);queryUI.success(data);syncEmployeeSiteLinks(state.site,defaultSite);renderStatus();
  }catch(e){if(generation!==loadGeneration)return;if(loadedState){state=structuredClone(loadedState);$('#site').value=state.site;$('#sort').value=state.sort;$('#page-size').value=String(state.size);$('#search').value=state.q;}queryUI.failure(e);if(append){appendFailed=true;if(e.code==='LIST_CHANGED')nextCursor=null;}throw e;}
  finally{if(generation===loadGeneration){loading=false;streamStatus();checkStreamEnd();}}
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
        if(!await confirmAction('이 탭의 저장 대기 변경을 모두 버리고 이동합니다. 이미 서버에 반영된 변경은 유지됩니다.',{title:'저장 대기 변경 버리기',confirmText:'내 변경 버리고 이동',danger:true}))continue;
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
$('#employee-discard').onclick=async()=>{if(!await confirmAction('선택한 고객의 이 브라우저 변경만 버립니다. 이미 서버에 저장된 상담 기록은 유지됩니다.',{title:'내 변경 버리기',confirmText:'내 변경 버리기',danger:true}))return;await queue.discard(comparison.entry);$('#employee-conflict').close();await load().catch(error);};
for(const button of document.querySelectorAll('[data-close]'))button.onclick=()=>button.closest('dialog').close();
$('#save-now').onclick=async()=>{commitEditor();const ok=await queue.flush(true);notice(ok?'저장했습니다.':'저장하지 못한 행을 확인해 주세요.');};
$('#reload-rows').onclick=()=>runQuery(load).catch(error);
$('#site').onchange=event=>{const site=event.target.value;event.target.value=state.site;runQuery(async()=>{state.site=site;state.page=1;$('#site').value=site;await load();}).catch(error);};
$('#sort').onchange=event=>{const sort=event.target.value;event.target.value=state.sort;runQuery(async()=>{state.sort=sort;state.page=1;$('#sort').value=sort;await load();}).catch(error);};
$('#page-size').onchange=event=>{const size=Number(event.target.value);event.target.value=String(state.size);runQuery(async()=>{state.size=size;state.page=1;$('#page-size').value=String(size);await load();}).catch(error);};
$('#search-form').onsubmit=event=>{event.preventDefault();const q=$('#search').value.trim();runQuery(async()=>{state.q=q;state.page=1;await load();}).then(moved=>{if(!moved)queryUI.render({search:true});}).catch(error);};

$('#previous').onclick=()=>runQuery(async()=>{state.page--;await load();}).catch(error);$('#next').onclick=()=>{appendFailed=false;runQuery(()=>load(true)).catch(error);};
let scrollCheckQueued=false;
function checkStreamEnd(){
  if(scrollCheckQueued)return;scrollCheckQueued=true;
  requestAnimationFrame(()=>{scrollCheckQueued=false;const holder=$('#employee-grid .tabulator-tableholder');
    if(nextCursor&&!loading&&!navigating&&!appendFailed&&holder.scrollTop+holder.clientHeight>=holder.scrollHeight-Math.max(320,holder.clientHeight))runQuery(()=>load(true)).catch(error);
  });
}
table.on('scrollVertical',checkStreamEnd);table.on('renderComplete',checkStreamEnd);
document.addEventListener('click',event=>{const link=event.target.closest('a[href]');if(!link||link.target||event.ctrlKey||event.metaKey)return;if(new URL(link.href).origin!==location.origin)return;event.preventDefault();guarded(()=>{location.href=link.href;}).catch(error);},true);
document.addEventListener('submit',event=>{const form=event.target;if(form.action?.endsWith('/auth/logout')){event.preventDefault();event.stopImmediatePropagation();guarded(()=>{HTMLFormElement.prototype.submit.call(form);},true).catch(error);}},true);
for(const name of ['copy','cut','contextmenu'])$('#employee-grid').addEventListener(name,event=>event.preventDefault());
$('#employee-grid').addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&['c','x'].includes(event.key.toLowerCase()))event.preventDefault();});
window.addEventListener('beforeunload',event=>{if(queue.entries.size||queue.invalid.size||callbacks?.pending.value||deletions?.pending.value||ai?.pending.value){event.preventDefault();event.returnValue='';}});
window.addEventListener('offline',()=>{for(const entry of queue.all())if(['dirty','retry'].includes(entry.state))entry.state='offline';renderStatus();});
async function resume(){try{const me=await request('/api/me');if(me.id!==userId||me.role!=='EMPLOYEE'||me.must_change_password){accessRevoked=true;readOnly=false;queue.pause('로그인 정보가 변경되었습니다. 다시 로그인해 주세요.');return;}if(environmentProblem){if(!accessRevoked){readOnly=true;renderStatus();}return;}await queue.resume();refreshTMDate();}catch(e){error(e);}}
window.addEventListener('online',resume);document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')resume();});window.addEventListener('focus',resume);
window.addEventListener('tm-auth-context',event=>{const data=event.detail;if(data.user!==userId||data.role!=='EMPLOYEE'||data.initial){accessRevoked=true;readOnly=false;queue.pause('다른 탭에서 로그인 정보가 변경되었습니다. 대기값 전송을 중단했습니다.');}});
$('#open-filters').onclick=()=>{
  commitEditor();
  openGridFilter({fields:customerFields(),labels:customerLabels,schema,current:state.filters,request,params,display,
    apply:filters=>runQuery(async()=>{state.filters=filters;state.page=1;await load();})});
};

await ready;
const gridHeader=$('#employee-grid .tabulator-header-contents'),gridHolder=$('#employee-grid .tabulator-tableholder');
gridHolder.addEventListener('scroll',checkStreamEnd,{passive:true});
gridHeader.addEventListener('scroll',()=>{if(Math.abs(gridHolder.scrollLeft-gridHeader.scrollLeft)>1)gridHolder.scrollLeft=gridHeader.scrollLeft;});
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
  const sites=await request('/api/sites');defaultSite=sites.default_site_id||'';$('#site').replaceChildren(...sites.items.map(s=>option(s.id,s.name)));state.site=new URL(location.href).searchParams.get('site_id')||defaultSite;$('#site').value=state.site;
  await load();await ai.refreshAvailability();queue.tick();if(view==='today')setInterval(refreshTMDate,30000);
}catch(e){error(e);loading=false;}


listenAdminUpdates(()=>{
  if((queueReady||readOnly)&&!accessRevoked&&!loading&&!navigating&&!activeEditor&&!queue.entries.size&&!queue.invalid.size&&
      !callbacks?.busy&&!deletions?.busy&&!ai?.busy&&!callbacks?.pending.value&&!deletions?.pending.value&&!ai?.pending.value)
    return runQuery(load).catch(error);
});
