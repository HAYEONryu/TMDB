import {confirmAction} from './shared-ui.js';
import {announceAdminUpdate} from './admin-updates.js';
import {newRequestId} from './request-id.js';
import {api,option} from './api.js';
import {PendingOperation} from './pending-operation.js';
const $=selector=>document.querySelector(selector),notice=message=>{$('#assignment-message').textContent=message;};
const operation=new PendingOperation('allocation',$('#assignment-management').dataset.userId,/^\/api\/assignments\/(distribute|recall|tm-recall)$/);
let busy=true,checked=false,recallBody,tmSelection,tmPreview;
function status(){
  const pending=!!operation.value;
  $('#assignment-pending').hidden=!pending;
  $('#assignment-site').disabled=busy||pending;$('#check-availability').disabled=busy||pending||!$('#assignment-site').value;
  for(const id of ['assignment-employee','assignment-quantity','distribute','recall','tm-recall'])$('#'+id).disabled=busy||pending||!checked;
  for(const id of ['distribute','recall','tm-recall'])$('#'+id).disabled ||= !$('#assignment-employee').value;
  for(const id of ['assignment-retry','assignment-discard','recall-confirm','recall-cancel','tm-recall-cancel'])$('#'+id).disabled=busy;
  $('#tm-recall-confirm').disabled=busy||!tmPreview?.target_count;
}
async function availability(){
  const selected=$('#assignment-employee').value;
  const data=await api('/api/assignments/availability?'+new URLSearchParams({site_id:$('#assignment-site').value}));
  $('#availability-count').textContent='분배 가능 '+data.available_count+'명 · 활성 직원 '+data.employees.length+'명';
  $('#assignment-employee').replaceChildren(option('all','전체 직원'),...data.employees.map(person=>option(person.id,person.name+' · '+person.phone.replace(/^(010)(\d{4})(\d{4})$/,'$1-$2-$3'))));
  if(selected&&selected!=='all'&&!data.employees.some(person=>person.id===selected)){
    $('#assignment-employee').prepend(option('','직원을 다시 선택해 주세요.'));$('#assignment-employee').value='';
  }else $('#assignment-employee').value=selected||'all';
  checked=true;
}
async function run(action){if(busy)return;busy=true;status();notice('');try{await action();}catch(error){notice(error.message);}finally{busy=false;status();}}
function body(){return {site_id:$('#assignment-site').value,employee_id:$('#assignment-employee').value};}
function showTMPreview(preview,warning=''){
  tmPreview=preview;$('#tm-recall-context').textContent=preview.site_name+' · '+preview.business_date+' · 합계 '+preview.target_count+'명';
  $('#tm-recall-warning').textContent=warning;
  const table=document.createElement('table');table.className='table';const head=document.createElement('thead'),header=document.createElement('tr');
  for(const label of ['선택 직원','미완료 TM 대상']){const th=document.createElement('th');th.textContent=label;th.scope='col';header.append(th);}head.append(header);table.append(head);
  const rows=document.createElement('tbody');for(const person of preview.employees){const row=document.createElement('tr');for(const value of [person.name,person.count+'명']){const td=document.createElement('td');td.textContent=value;row.append(td);}rows.append(row);}table.append(rows);
  $('#tm-recall-preview').replaceChildren(table);if(!$('#tm-recall-dialog').open)$('#tm-recall-dialog').showModal();status();
}
async function execute(value){
  const original=value||operation.value;
  try{
    const result=await operation.execute(value);
    $('#assignment-result').replaceChildren();
    const summary=document.createElement('p');
    summary.textContent=result.allocated_count!==undefined?'고객 '+result.allocated_count+'명을 배정했습니다.':
      result.recall_kind==='unfinished_tm'?'미완료 TM 고객 '+result.recalled_count+'명을 회수했습니다.':
      result.business_date+' 배정 고객 '+result.recalled_count+'명을 회수했습니다.';
    $('#assignment-result').append(summary);
    for(const person of result.employees||[]){const p=document.createElement('p');p.className='small mb-1';p.textContent=person.name+': '+person.count+'명'+(person.remaining_held!==undefined?' 회수 · 현재 담당 '+person.remaining_held+'명':'');$('#assignment-result').append(p);}
    try{await availability();}catch(error){notice('처리는 완료되었습니다. 잔여 수 조회: '+error.message);checked=false;}
    announceAdminUpdate(result.site_id);
  }catch(error){
    if(error.code==='TM_TARGETS_CHANGED'&&error.data?.error?.fields?.preview){
      tmSelection={site_id:original.body.site_id,employee_id:original.body.employee_id};
      showTMPreview(error.data.error.fields.preview,error.message);return;
    }
    notice(error.message.replace(/([0-9]+)개씩 분배/g,'$1명씩 분배'));if(!operation.value){try{await availability();}catch{checked=false;}}
  }
}
$('#assignment-site').onchange=()=>{checked=false;$('#assignment-employee').replaceChildren();$('#assignment-quantity').value='';$('#availability-count').textContent='현장을 확인해 주세요.';$('#assignment-result').replaceChildren();status();};
$('#check-availability').onclick=()=>run(availability);$('#assignment-employee').onchange=status;
$('#distribute').onclick=()=>run(async()=>{const quantity=Number($('#assignment-quantity').value);if(!Number.isSafeInteger(quantity)||quantity<=0)throw new Error('직원당 수량은 양의 정수로 입력해 주세요.');await execute({endpoint:'/api/assignments/distribute',body:{...body(),quantity,idempotency_key:newRequestId()}});});
$('#recall').onclick=()=>run(async()=>{recallBody=body();const preview=await api('/api/assignments/recall-preview',recallBody);$('#recall-preview').textContent=$('#assignment-site').selectedOptions[0]?.textContent+' · '+$('#assignment-employee').selectedOptions[0]?.textContent+' · '+preview.business_date+' · 직원 '+preview.employee_count+'명 · 현재 대상 고객 '+preview.target_count+'명을 회수하시겠습니까?';$('#recall-dialog').showModal();});
$('#recall-cancel').onclick=()=>$('#recall-dialog').close();
$('#recall-confirm').onclick=()=>run(async()=>{$('#recall-dialog').close();await execute({endpoint:'/api/assignments/recall',body:{...recallBody,idempotency_key:newRequestId()}});});
$('#tm-recall').onclick=()=>run(async()=>{tmSelection=body();showTMPreview(await api('/api/assignments/tm-recall-preview',tmSelection));});
$('#tm-recall-cancel').onclick=()=>$('#tm-recall-dialog').close();
$('#tm-recall-confirm').onclick=()=>run(async()=>{$('#tm-recall-dialog').close();await execute({endpoint:'/api/assignments/tm-recall',body:{...tmSelection,confirmation:tmPreview.confirmation,idempotency_key:newRequestId()}});});
$('#assignment-retry').onclick=()=>run(()=>execute());
$('#assignment-discard').onclick=()=>run(async()=>{if(!await confirmAction('배정·회수 확인 알림을 닫습니다. 서버에서 이미 처리된 작업은 그대로 유지됩니다. 다시 작업하기 전에 현재 고객 상태를 확인하세요.',{title:'이 화면에서 알림 닫기',confirmText:'알림 닫기'}))return;operation.clear();checked=false;notice('이 화면의 알림을 닫았습니다. 서버에서 이미 처리된 작업은 그대로 유지됩니다. 분배 가능 고객을 다시 조회하세요.');});
window.addEventListener('beforeunload',event=>{if(busy||operation.value){event.preventDefault();event.returnValue='';}});
status();
try{const data=await api('/api/sites');$('#assignment-site').replaceChildren(...data.items.map(site=>option(site.id,site.name)));$('#assignment-site').value=operation.value?.body.site_id||new URL(location.href).searchParams.get('site_id')||data.default_site_id||'';if(!data.items.length)notice('등록된 현장이 없습니다. DB 관리에서 현장을 생성해 주세요.');}
catch(error){notice(error.message);}finally{busy=false;status();}
